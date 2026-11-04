"""Stage private conversion engines; never install them system-wide.

Pinned MSI cabinets are read as data, without msiexec or installer actions.
Logs and extracted files stay inside the BuildKit. Errors block packaging.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import urllib.parse

from prepare_components import ROOT, RUNTIME, download, sha256, write_json, pe_machine, filesystem_path
from prepare_runtime import extract_zip

CONFIG = ROOT / 'converter_sources.json'
TARGET = filesystem_path(RUNTIME / 'converters')
LOCK = ROOT / 'converter_sources.lock.json'
METADATA = ROOT / 'bootstrap' / 'converters'
CACHE = ROOT / '.build-tools' / 'converter-downloads'


def winget_x64(text, version):
    """Read only the scalar fields in the pinned Microsoft package manifest."""
    actual = re.search(r'(?m)^PackageVersion:\s*[\'\"]?([^\s\'\"]+)', text)
    if not actual or actual[1] != version:
        raise RuntimeError('Upstream manifest version does not match ' + version)
    blocks = re.split(r'(?m)^\s*- Architecture:\s*', text)[1:]
    selected = []
    for block in blocks:
        if block.splitlines()[0].strip() != 'x64':
            continue
        urls = re.findall(r'(?m)^\s+InstallerUrl:\s*(https://\S+)\s*$', block)
        if len(urls) != 1:
            raise RuntimeError('Ambiguous installer URL in an x64 manifest block')
        if urllib.parse.urlsplit(urls[0]).path.lower().endswith('.msi'):
            selected.append(block)
    if len(selected) != 1:
        raise RuntimeError('Expected one Windows x64 MSI in the pinned manifest')
    block = selected[0]
    url = re.search(r'(?m)^\s+InstallerUrl:\s*(https://\S+)\s*$', block)
    digest = re.search(r'(?m)^\s+InstallerSha256:\s*([0-9A-Fa-f]{64})\s*$', block)
    if not url or not digest or not urllib.parse.urlsplit(url[1]).path.lower().endswith('.msi'):
        raise RuntimeError('Manifest has no unique SHA-256-verified MSI')
    minimums = re.findall(r'(?m)^\s*MinimumOSVersion:\s*([\d.]+)', text)
    for minimum in minimums:
        if tuple(map(int, minimum.split('.'))) > (10, 0, 17763, 0):
            raise RuntimeError('Converter vendor requires a newer OS than LTSC 1809: ' + minimum)
    return {'url': url[1], 'sha256': digest[1].lower(), 'version': version, 'kind': 'msi'}


def load_sources(config):
    """Use complete, bundled upstream evidence; never fetch metadata while building."""
    try:
        records = json.loads(LOCK.read_text('utf-8-sig'))
    except (OSError, ValueError) as error:
        raise RuntimeError('Cannot read bundled converter source lock: ' + str(LOCK)) from error
    if not isinstance(records, dict) or set(records) != set(config):
        raise RuntimeError('Bundled converter source lock must contain all configured engines')
    for name, entry in config.items():
        record = records[name]
        if not isinstance(record, dict):
            raise RuntimeError('Invalid pinned converter record: ' + name)
        for field in ('sha256', 'metadata_sha256'):
            value = record.get(field)
            if not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{64}', value):
                raise RuntimeError('Invalid pinned ' + field + ' for ' + name)
        evidence = METADATA / (name + '.installer.yaml' if entry['kind'] == 'msi' else 'blender.sha256')
        if not evidence.is_file() or sha256(evidence) != record['metadata_sha256']:
            raise RuntimeError('Missing/changed bundled converter evidence: ' + str(evidence))
        text = evidence.read_text('utf-8-sig')
        if entry['kind'] == 'msi':
            actual = winget_x64(text, entry['version'])
            if (urllib.parse.urlsplit(actual['url']).hostname or '') not in entry['allowed_hosts']:
                raise RuntimeError('Unexpected converter vendor host for ' + name)
            origin = entry['manifest']
        else:
            version = record.get('version', '')
            if not isinstance(version, str) or not re.fullmatch(r'4\.2\.\d+', version):
                raise RuntimeError('Pinned Blender must belong to the 4.2 LTS branch')
            filename = 'blender-' + version + '-windows-x64.zip'
            match = re.search(r'(?m)^([0-9a-fA-F]{64})\s+\*?' + re.escape(filename) + r'\s*$', text)
            if not match:
                raise RuntimeError('No upstream checksum for pinned ' + filename)
            actual = {'url':entry['directory'] + filename, 'sha256':match[1].lower(),
                      'version':version, 'kind':'zip'}
            origin = entry['directory'] + 'blender-' + version + '.sha256'
        if any(record.get(key) != value for key, value in actual.items()) or record.get('metadata_source') != origin:
            raise RuntimeError('Pinned converter source differs from bundled upstream evidence: ' + name)
    return records


def file_manifest(directory):
    return {p.relative_to(directory).as_posix(): sha256(p)
            for p in sorted(directory.rglob('*')) if p.is_file()}


def locate_engine(directory, engine):
    matches = [p for p in directory.rglob(engine) if p.is_file()]
    if len(matches) != 1:
        raise RuntimeError('Engine missing or ambiguous after extraction: ' + engine)
    return matches[0]


def stage_one(name, entry, resolved):
    if resolved['kind'] == 'msi':
        recipe = {'mode': 'cab-file-map-v1', 'catalog_sha256': sha256(ROOT / 'bootstrap/msi' / (name + '.json'))}
    else:
        recipe = {'mode': 'zip-v1', 'private_blender_config': 'portable/config'}
    target = TARGET / name
    marker = target / 'NOP_ENGINE_MANIFEST.json'
    if marker.is_file():
        try:
            previous = json.loads(marker.read_text('utf-8'))
            if not isinstance(previous, dict):
                previous = {}
        except (OSError, ValueError):
            previous = {}
        if previous.get('archive_sha256') == resolved['sha256'] and previous.get('recipe') == recipe:
            expected = previous.get('files', {})
            actual = {k: v for k, v in file_manifest(target).items() if k != marker.name}
            if actual and expected == actual:
                print('Verified cached conversion engine:', name, flush=True)
                return previous
    filename = Path(urllib.parse.urlsplit(resolved['url']).path).name
    archive = CACHE / filename
    download(resolved['url'], archive, resolved['sha256'], minimum=1024 * 1024)
    TARGET.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.' + name + '-', dir=str(TARGET)) as temp:
        temp = Path(temp)
        unpacked = temp / 'unpacked'
        unpacked.mkdir()
        if resolved['kind'] == 'zip':
            extract_zip(archive, unpacked)
        else:
            from msi_payload import extract_msi
            log = ROOT / 'logs' / ('extract-' + name + '.log')
            extract_msi(archive, unpacked, name, resolved['sha256'], log)
        exe = locate_engine(unpacked, entry['engine'])
        if pe_machine(exe) != 0x8664:
            raise RuntimeError('Not an x64 conversion engine: ' + str(exe))
        engine_root = exe.parent
        for _ in Path(entry['engine_relative']).parts[:-1]:
            engine_root = engine_root.parent
        stage = temp / 'engine'
        engine_root.replace(stage)
        if not (stage / entry['engine_relative']).is_file():
            raise RuntimeError('Incorrect private engine layout: ' + name)
        # Portable Blender configuration stays with the private engine.
        if name == 'blender':
            (stage / 'portable' / 'config').mkdir(parents=True, exist_ok=True)
        record = {**resolved, 'archive_sha256': resolved['sha256'], 'recipe': recipe, 'engine': entry['engine_relative'],
                  'files': file_manifest(stage)}
        write_json(stage / marker.name, record)
        backup = target.with_name(target.name + '.previous')
        if backup.exists():
            shutil.rmtree(backup)
        if target.exists():
            target.replace(backup)
        try:
            stage.replace(target)
        except BaseException:
            if backup.exists() and not target.exists():
                backup.replace(target)
            raise
        if backup.exists():
            shutil.rmtree(backup)
    return record


def main():
    if os.name != 'nt':
        raise RuntimeError('Prepare the Windows conversion engines on Windows x64')
    config = json.loads(CONFIG.read_text('utf-8'))
    locked = load_sources(config)
    print('Validated bundled converter sources: ' + str(len(locked)) + '; no live metadata requests.', flush=True)
    records = {}
    for name, entry in config.items():
        print('Preparing private converter:', name, flush=True)
        records[name] = stage_one(name, entry, locked[name])
    write_json(RUNTIME / 'converters-manifest.json', records)
    print('All four private conversion engines prepared; no global applications installed.')


if __name__ == '__main__':
    main()
