"""Read pinned MSI payloads as data. Windows Installer is never started.

The checked-in maps come from the File/Component/Directory/Media tables of the
exact SHA-256-pinned vendor MSIs. CAB keys are mapped to long application paths;
system merge modules and registry/custom actions are deliberately not applied.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent
CATALOGS = ROOT / 'bootstrap' / 'msi'
TOOL = ROOT / '.build-tools' / '7zip-full-26.05' / '7z.exe'
TOOL_HASHES = {'7z.exe': '94205cfc054dd3bbeb978905bc619a65b3f04e9e73bb2717841110b6f46d962e', '7z.dll': '78bf6b668d75801e3aa180b4ccb16e6d8395fba80dec8a065055bb6f8dfabb82'}


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def safe_relative(value):
    if not isinstance(value, str) or not value or '\\' in value:
        raise RuntimeError('Invalid MSI payload path: ' + repr(value))
    path = PurePosixPath(value)
    if path.is_absolute() or any(p in ('.', '..') for p in value.split('/')):
        raise RuntimeError('Unsafe MSI payload path: ' + value)
    for part in path.parts:
        if (part.rstrip(' .') != part or re.search(r'[\x00-\x1f<>:"|?*]', part) or
                re.fullmatch(r'(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', part)):
            raise RuntimeError('Ambiguous Windows MSI payload path: ' + value)
    return path


def safe_key(value):
    # MSI File primary keys are CAB names, not installed file names. Inkscape's
    # official CAB has 29 keys ending in dots. 7-Zip replaces trailing dots/spaces
    # with underscores on Windows; restore the installed name from the file map.
    safe_relative(value.rstrip(' .'))
    if '/' in value or '\\' in value:
        raise RuntimeError('Unsafe MSI cabinet key: ' + value)
    return value


def disk_key(value, windows=None):
    if windows is None:
        windows = os.name == 'nt'
    clean = value.rstrip(' .')
    return clean + '_' * (len(value) - len(clean)) if windows else value


def load_catalog(name, archive_sha256):
    if not isinstance(name, str) or not re.fullmatch(r'[a-z0-9_-]+', name):
        raise RuntimeError('No pinned MSI file map for ' + str(name))
    source = json.loads((CATALOGS / 'SOURCE.json').read_text('utf-8'))
    path = CATALOGS / (name + '.json')
    if digest(path) != source['catalog_sha256'][path.name]:
        raise RuntimeError('MSI file map SHA-256 mismatch: ' + name)
    catalog = json.loads(path.read_text('utf-8'))
    if catalog.get('schema') != 1 or catalog.get('source_sha256') != archive_sha256:
        raise RuntimeError('MSI file map does not match the pinned vendor archive: ' + name)
    safe_relative(catalog['cabinet'])
    if '/' in catalog['cabinet'] or not 0 < len(catalog['files']) <= 100000:
        raise RuntimeError('Invalid MSI cabinet map')
    keys, targets, total = set(), set(), 0
    disk_names = set()
    for key, target, size in catalog['files']:
        safe_key(key)
        normalized = disk_key(key, windows=True).casefold()
        if normalized in disk_names:
            raise RuntimeError('Colliding normalized MSI cabinet keys: ' + key)
        disk_names.add(normalized)
        if '/' in key or key.casefold() in keys or type(size) is not int or size < 0:
            raise RuntimeError('Invalid/duplicate MSI cabinet member: ' + key)
        keys.add(key.casefold()); total += size
        if target is not None:
            safe_relative(target)
            if target.casefold() in targets:
                raise RuntimeError('Colliding MSI application paths: ' + target)
            targets.add(target.casefold())
    if total > 12 * 1024**3 or not targets:
        raise RuntimeError('MSI payload size/file count is invalid')
    return catalog


def verified_tool():
    for name, expected in TOOL_HASHES.items():
        path = TOOL.parent / name
        if not path.is_file() or digest(path) != expected:
            raise RuntimeError('Private full 7-Zip missing/changed: ' + str(path))
    if not TOOL_HASHES or not TOOL.is_file():
        raise RuntimeError('Private full 7-Zip is unavailable: ' + str(TOOL))
    return TOOL


def native(tool, arguments, log, timeout=1200):
    command = [str(tool), *map(str, arguments)]
    with log.open('a', encoding='utf-8') as stream:
        stream.write('COMMAND ' + subprocess.list2cmdline(command) + '\n')
    try:
        result = subprocess.run(command, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding='utf-8',
            errors='replace', timeout=timeout,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError('MSI data extraction could not finish; see ' + str(log) + ': ' + str(error)) from error
    with log.open('a', encoding='utf-8') as stream:
        stream.write('EXIT ' + str(result.returncode) + '\n' + result.stdout + '\n')
    if result.returncode:
        raise RuntimeError('MSI data extraction failed (7-Zip exit ' + str(result.returncode) +
                           '); see ' + str(log) + '\n' + result.stdout[-4000:])
    return result.stdout


def check_cabinet_listing(text, catalog):
    actual = {}
    for block in re.split(r'\r?\n\r?\n', text.strip()):
        values = dict(line.split(' = ', 1) for line in block.splitlines() if ' = ' in line)
        if 'Path' not in values:
            continue
        name = values['Path']; safe_key(name)
        if '/' in name or name in actual or not values.get('Size', '').isdigit():
            raise RuntimeError('Invalid MSI cabinet member listing: ' + name)
        actual[name] = int(values['Size'])
    expected = {key: size for key, _, size in catalog['files']}
    if actual != expected:
        raise RuntimeError('MSI embedded cabinet differs from its pinned file map')


def extract_msi(archive, destination, name, expected_sha256, log):
    archive, destination, log = Path(archive), Path(destination), Path(log)
    catalog = load_catalog(name, expected_sha256)
    if digest(archive) != expected_sha256:
        raise RuntimeError('MSI archive SHA-256 mismatch: ' + archive.name)
    tool = verified_tool()
    if destination.exists() and any(destination.iterdir()):
        raise RuntimeError('MSI extraction requires an empty destination: ' + str(destination))
    destination.mkdir(parents=True, exist_ok=True)
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text('Read-only MSI payload extraction; no msiexec, services or custom actions.\n', 'utf-8')
    print('Extracting MSI files without Windows Installer:', archive.name, flush=True)
    with tempfile.TemporaryDirectory(prefix='.cab-', dir=destination.parent) as work:
        work = Path(work); cab_dir = work / 'cab'; flat = work / 'files'
        cab_dir.mkdir(); flat.mkdir()
        common = ['-y', '-bd', '-bsp0', '-sccUTF-8']
        native(tool, ['x', *common, '-tCompound', '-o' + str(cab_dir.resolve()),
                      '--', archive.resolve(), catalog['cabinet']], log)
        cab = cab_dir / catalog['cabinet']
        if not cab.is_file() or cab.is_symlink() or len(list(cab_dir.iterdir())) != 1:
            raise RuntimeError('Pinned embedded MSI cabinet is missing or ambiguous')
        listing = native(tool, ['l', '-slt', '-ba', '-sccUTF-8', '--', cab], log)
        check_cabinet_listing(listing, catalog)
        native(tool, ['x', *common, '-o' + str(flat.resolve()), '--', cab], log)
        actual = {p.name for p in flat.iterdir() if p.is_file() and not p.is_symlink()}
        if actual != {disk_key(key) for key, _, _ in catalog['files']}:
            raise RuntimeError('Unexpected/missing files in extracted MSI cabinet')
        restored = 0
        for key, target, size in catalog['files']:
            source = flat / disk_key(key)
            if source.stat().st_size != size:
                raise RuntimeError('Wrong size of extracted MSI file: ' + key)
            if target is not None:
                output = destination.joinpath(*PurePosixPath(target).parts)
                output.parent.mkdir(parents=True, exist_ok=True)
                source.replace(output)
                restored += 1
    with log.open('a', encoding='utf-8') as stream:
        stream.write('Restored application files: ' + str(restored) + '\n')
    print('MSI cabinet CRC, file count, sizes and directory map passed:', restored, flush=True)
    return restored
