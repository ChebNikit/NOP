"""Reduce converter payloads, with reversible changes and native before/after checks.

Full vendor caches and runtime_deps are retained. Only dist/NOP/converters is
trimmed. A smaller engine is accepted only if its actual frozen-worker results
and advertised formats are preserved on the current Windows build machine.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import time
from xml.dom import minidom

ROOT = Path(__file__).resolve().parent
ENGINES = ('libreoffice', 'blender', 'inkscape', 'calibre')
POLICY = 'nop-converters-resources-v1'
REGISTRY = 'http://openoffice.org/2001/registry'
FONT_SUFFIXES = {'.ttf', '.otf', '.ttc', '.woff', '.woff2', '.pfb', '.afm'}
NATIVE_SUFFIXES = {'.dll', '.pyd', '.exe', '.com', '.so', '.dylib'}


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def kept_locale(value):
    return value.replace('_', '-').split('-', 1)[0].casefold() in ('en', 'ru')


def protected(relative):
    p = PurePosixPath(relative)
    name = p.name.casefold()
    return (p.suffix.casefold() in FONT_SUFFIXES | NATIVE_SUFFIXES or
            any(word in name for word in ('license', 'licence', 'copying', 'copyright', 'notice')) or
            name.startswith('hyph_') or '/hyphenation/' in '/' + relative.casefold())


def resource_reason(engine, relative):
    """Only named non-conversion resources, never general DLL/dependency pruning."""
    p = PurePosixPath(relative)
    parts = p.parts
    name = p.name.casefold()
    low = relative.casefold()
    if protected(relative):
        return None
    if name.endswith('.pdb'):
        return 'debug symbols'
    if engine == 'libreoffice':
        if len(parts) >= 4 and parts[:2] == ('program', 'resource') and not kept_locale(parts[2]):
            return 'unused engine UI translation'
        if parts[:3] == ('share', 'registry', 'res'):
            match = re.fullmatch(r'(?:registry|fcfg_langpack)_(.+)\.xcd', name)
            if match and not kept_locale(match[1]):
                return 'unused engine UI translation'
        if parts[:2] == ('share', 'config') and name.startswith('images_') and name.endswith('.zip'):
            if name not in ('images_colibre.zip', 'images_breeze.zip'):
                return 'alternate editor icon theme'
    elif engine == 'blender':
        if parts and re.fullmatch(r'\d+\.\d+', parts[0]):
            tail = parts[1:]
            if len(tail) >= 5 and tail[:4] == ('scripts', 'addons_core', 'cycles', 'lib'):
                if name.startswith('kernel_') and not name.startswith('kernel_cpu'):
                    return 'Cycles GPU render kernels; NOP only imports/exports models'
            if len(tail) >= 4 and tail[:2] == ('datafiles', 'locale') and not kept_locale(tail[2]):
                return 'unused engine UI translation'
            if tail[:2] == ('datafiles', 'studiolights'):
                return 'interactive 3D viewport studio lighting'
    elif engine == 'inkscape':
        if parts[:3] == ('share', 'inkscape', 'tutorials'):
            return 'interactive editor tutorials'
        if parts[:4] == ('share', 'inkscape', 'extensions', 'docs'):
            return 'extension developer documentation'
        if len(parts) >= 4 and parts[:2] == ('share', 'locale') and not kept_locale(parts[2]):
            return 'unused engine UI translation'
        if parts[0] == 'include' or (parts[0] == 'lib' and name.endswith('.a')):
            return 'C/C++ development headers or static import library'
        if low.startswith(('lib/pkgconfig/', 'lib/cmake/', 'share/gtk-doc/', 'share/gdb/')):
            return 'build or debugger documentation'
    elif engine == 'calibre':
        if parts[:2] == ('app', 'translations') and len(parts) >= 4 and parts[2] == 'qtwebengine_locales':
            if p.suffix.casefold() == '.pak' and not kept_locale(p.stem):
                return 'unused engine UI translation'
        if low.startswith('app/share/espeak-ng-data/'):
            return 'standalone calibre text-to-speech voice data'
        if low.startswith('app/resources/content-server/'):
            return 'standalone calibre HTTP server interface'
        if low == 'app/resources/builtin_recipes.zip':
            return 'standalone calibre news fetching recipes'
    return None


def dictionary_changes(folder):
    """Remove spelling/thesaurus data while retaining every hyphenation entry.

    minidom retains XML namespace declarations used in attribute values such as
    oor:type="xs:string". Plain ElementTree serialization can lose xmlns:xs.
    """
    changes = []
    for path in sorted((folder / 'share/extensions').glob('dict-*/dictionaries.xcu')):
        document = minidom.parse(str(path))
        obsolete, required, remove_nodes = set(), set(), []
        for node in document.getElementsByTagName('node'):
            props = {p.getAttributeNS(REGISTRY, 'name'): ''.join(
                child.data for v in p.getElementsByTagName('value') for child in v.childNodes
                if child.nodeType in (child.TEXT_NODE, child.CDATA_SECTION_NODE)).strip()
                for p in node.childNodes if p.nodeType == p.ELEMENT_NODE and p.localName == 'prop'}
            if 'Format' not in props:
                continue
            locations = []
            for value in props.get('Locations', '').split():
                if not value.startswith('%origin%/'):
                    raise RuntimeError('Unexpected dictionary path in ' + str(path))
                rel = PurePosixPath(value[len('%origin%/'):])
                if rel.is_absolute() or '..' in rel.parts or '\\' in str(rel):
                    raise RuntimeError('Unsafe dictionary path')
                locations.append(path.parent.joinpath(*rel.parts))
            if props['Format'] in ('DICT_SPELL', 'DICT_THES'):
                remove_nodes.append(node)
                obsolete.update(locations)
                if props['Format'] == 'DICT_THES':
                    obsolete.update(p.with_suffix('.idx') for p in locations if p.suffix == '.dat')
            else:
                required.update(locations)
        if remove_nodes:
            for node in remove_nodes:
                node.parentNode.removeChild(node)
            changes.append({'path': path.relative_to(folder).as_posix(), 'reason': 'disable editor spelling/thesaurus registrations',
                            'data': document.toxml(encoding='utf-8')})
            for item in sorted(obsolete - required):
                relative = item.relative_to(folder).as_posix()
                if item.is_file() and not protected(relative):
                    changes.append({'path': relative, 'reason': 'editor spelling/thesaurus dictionary', 'data': None})
    return changes


def plan_engine(folder, engine):
    folder = Path(folder)
    if engine not in ENGINES or not folder.is_dir() or folder.is_symlink():
        raise RuntimeError('Invalid private converter directory: ' + str(folder))
    changes = []
    for path in sorted(folder.rglob('*')):
        if path.is_symlink():
            raise RuntimeError('Symlink in converter runtime: ' + str(path))
        if path.is_file():
            relative = path.relative_to(folder).as_posix()
            reason = resource_reason(engine, relative)
            if reason:
                changes.append({'path': relative, 'reason': reason, 'data': None})
    if engine == 'libreoffice':
        changes += dictionary_changes(folder)
    if len({row['path'] for row in changes}) != len(changes):
        raise RuntimeError('Conflicting compact-converter actions')
    return changes


class Transaction:
    """Move originals to a same-volume journal outside the application bundle."""
    def __init__(self, root, backup):
        self.root, self.backup = Path(root), Path(backup)
        self.entries = []
        self.by_path = {}
        self.journal = self.backup / 'journal.jsonl'
        self.backup.mkdir(parents=True, exist_ok=False)

    def log(self, row):
        with self.journal.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(row, ensure_ascii=False) + '\n')

    def change(self, relative, data):
        rel = PurePosixPath(relative)
        if rel.is_absolute() or '..' in rel.parts or '\\' in relative or ':' in relative:
            raise RuntimeError('Unsafe compaction destination')
        target, saved = self.root.joinpath(*rel.parts), self.backup.joinpath('originals', *rel.parts)
        if relative not in self.by_path:
            if not target.is_file() or target.is_symlink():
                raise RuntimeError('Compaction source is not a regular file: ' + relative)
            row = {'path': relative, 'sha256': digest(target), 'backed_up': False}
            self.entries.append(row)
            self.by_path[relative] = row
            self.log({'op': 'backup', 'path': relative, 'sha256': row['sha256']})
            saved.parent.mkdir(parents=True, exist_ok=True)
            target.replace(saved)
            row['backed_up'] = True
        if data is not None:
            temporary = target.with_name(target.name + '.nop-compact.tmp')
            temporary.write_bytes(data)
            temporary.replace(target)
        elif target.exists():
            target.unlink()

    def rollback(self, engine=None):
        prefix = engine + '/' if engine else None
        for index in range(len(self.entries) - 1, -1, -1):
            row = self.entries[index]
            if prefix and not row['path'].startswith(prefix):
                continue
            target = self.root / row['path']
            saved = self.backup / 'originals' / row['path']
            # A process can stop after rename but before the second journal write.
            if saved.is_file():
                if digest(saved) != row['sha256']:
                    raise RuntimeError('Compaction backup changed: ' + row['path'])
                if target.exists():
                    target.unlink()
                target.parent.mkdir(parents=True, exist_ok=True)
                saved.replace(target)
            elif row['backed_up']:
                raise RuntimeError('Missing compaction backup: ' + row['path'])
            temporary = target.with_name(target.name + '.nop-compact.tmp')
            temporary.unlink(missing_ok=True)
            self.log({'op': 'restored', 'path': row['path']})
            self.entries.pop(index)
            del self.by_path[row['path']]


def regressions(before, after):
    """Only preserved real successes can certify a smaller runtime."""
    rejected = set()
    old = {row['id']: row for row in before['cases']}
    new = {row['id']: row for row in after['cases']}
    if old.keys() != new.keys():
        raise RuntimeError('Before/after conversion matrix differs')
    for key, row in old.items():
        if row.get('export_ok') and not new[key].get('export_ok'):
            rejected.add(row['engine'])
        if row['ok'] and (not new[key]['ok'] or row['signature'] != new[key].get('signature')):
            rejected.add(row['engine'])
    for name in ENGINES:
        a = before['capabilities'].get(name)
        b = after['capabilities'].get(name)
        if a != b:
            rejected.add(name)
    for engine, key in (('libreoffice', 'office'), ('blender', 'model'), ('inkscape', 'vector'), ('calibre', 'ebook')):
        if key in after.get('capability_errors', {}) and key not in before.get('capability_errors', {}):
            rejected.add(engine)
    return rejected


def native_audit(exe, report, allow_failed=False):
    environment = {k: v for k, v in os.environ.items() if not k.upper().startswith(('PYTHON', 'QT_', 'QML', '_PYI_'))}
    for key in list(environment):
        if key.upper().startswith(('BLENDER_', 'CALIBRE_', 'INKSCAPE_')):
            environment.pop(key)
    windows = Path(environment['WINDIR'])
    environment['PATH'] = os.pathsep.join((str(windows / 'System32'), str(windows)))
    environment['NOP_CONVERTER_AUDIT'] = '1'
    report.unlink(missing_ok=True)
    seen = set()
    with report.with_suffix('.native.log').open('wb') as log:
        process = subprocess.Popen([str(exe), '--nop-functional-check', str(report)], cwd=exe.parent,
            env=environment, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        deadline = time.monotonic() + 2400
        try:
            while process.poll() is None:
                try:
                    partial = json.loads(report.read_text('utf-8'))
                    for row in partial.get('cases', []):
                        if row['id'] not in seen:
                            seen.add(row['id'])
                            print(('PASS ' if row['ok'] else 'UNAVAILABLE/FAIL ') + row['id'], flush=True)
                except (OSError, ValueError):
                    pass
                if time.monotonic() >= deadline:
                    raise RuntimeError('Converter audit exceeded 40 minutes: ' + str(report))
                time.sleep(0.5)
        finally:
            if process.poll() is None:
                subprocess.run([str(windows / 'System32/taskkill.exe'), '/PID', str(process.pid), '/T', '/F'],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
                process.wait(timeout=30)
    if not report.is_file():
        raise RuntimeError('Frozen converter audit produced no report: ' + str(report))
    result = json.loads(report.read_text('utf-8'))
    if (result.get('scope') != 'frozen Windows ConverterWorker' or not result.get('complete') or
            (not allow_failed and (process.returncode or not result.get('ok')))):
        raise RuntimeError('Required converter checks failed: ' + str(report))
    return result


def files(folder):
    return {p.relative_to(folder).as_posix(): digest(p) for p in sorted(folder.rglob('*'))
            if p.is_file() and p.name != 'NOP_ENGINE_MANIFEST.json'}


def clear_generated(bundle, expected, destination, originals=None):
    """Preserve vendor bytes; quarantine only files created by acceptance tests."""
    destination = Path(destination)
    moved = []
    for name in ENGINES:
        folder = bundle / 'converters' / name
        actual = files(folder)
        for relative, sha in expected[name].items():
            if actual.get(relative) != sha:
                canonical = Path(originals) / name / relative if originals is not None else None
                # Extracted source timestamps can invalidate supplied .pyc files.
                # Restore vendor bytecode; never drop a sourceless original .pyc.
                if (relative.casefold().endswith('.pyc') and canonical is not None and
                        canonical.is_file() and digest(canonical) == sha):
                    target = folder / relative
                    temporary = target.with_name(target.name + '.nop-compact-cache.tmp')
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(canonical, temporary)
                    if digest(temporary) != sha:
                        raise RuntimeError('Vendor bytecode restoration SHA-256 mismatch')
                    temporary.replace(target)
                    moved.append({'path': name + '/' + relative, 'action': 'restored vendor bytecode'})
                else:
                    raise RuntimeError('Converter changed or removed supplied runtime data: ' + name + '/' + relative)
        for relative in sorted(actual.keys() - expected[name].keys()):
            source = folder / relative
            target = destination / name / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            source.replace(target)
            moved.append({'path': name + '/' + relative, 'action': 'quarantined acceptance-generated file'})
    return moved


def finalize():
    if os.name != 'nt':
        raise RuntimeError('Finalize the validated Windows bundle on Windows')
    from prepare_components import filesystem_path
    bundle = filesystem_path(ROOT / 'dist/NOP')
    manifest = json.loads((bundle / 'converters-manifest.json').read_text('utf-8'))
    if any('compaction' not in manifest[name] for name in ENGINES):
        raise RuntimeError('Missing accepted converter-compaction manifest')
    moved = clear_generated(bundle, {name: manifest[name]['files'] for name in ENGINES},
                            filesystem_path(ROOT / 'build/converter-compaction' / ('generated-final-' + str(time.time_ns()))),
                            filesystem_path(ROOT / 'runtime_deps/converters'))
    report_path = bundle / 'CONVERTER_COMPACTION_REPORT.json'
    result = json.loads(report_path.read_text('utf-8'))
    result['acceptance_artifact_cleanup'] = moved
    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf-8')
    print('Converter byte manifests verified; acceptance-generated cache/profile files excluded: ' + str(len(moved)), flush=True)


def stamp(bundle, original, statistics, transaction):
    records = copy.deepcopy(original)
    for name in ENGINES:
        records[name]['files'] = files(bundle / 'converters' / name)
        records[name]['compaction'] = statistics[name]
        data = (json.dumps(records[name], ensure_ascii=False, indent=2) + '\n').encode('utf-8')
        transaction.change('converters/' + name + '/NOP_ENGINE_MANIFEST.json', data)
    transaction.change('converters-manifest.json', (json.dumps(records, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
    manifest = json.loads((bundle / 'bundle-manifest.json').read_text('utf-8'))
    manifest['converters'] = records
    transaction.change('bundle-manifest.json', (json.dumps(manifest, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))


def main():
    if os.name != 'nt':
        raise RuntimeError('Native before/after compaction checks must run on Windows')
    from prepare_components import filesystem_path
    bundle = filesystem_path(ROOT / 'dist/NOP')
    work = ROOT / 'build/converter-compaction'
    work.mkdir(parents=True, exist_ok=True)
    backup = filesystem_path(work / 'backup')
    original = json.loads((bundle / 'converters-manifest.json').read_text('utf-8'))
    for name in ENGINES:
        if files(bundle / 'converters' / name) != original[name]['files'] or original[name].get('compaction'):
            raise RuntimeError('Compaction needs the complete assembled engine: ' + name + '. Run build_windows.bat to rebuild dist from the retained full cache.')
    if backup.exists():
        # A normal build has just rebuilt dist from full caches, verified above.
        # Preserve an old interrupted journal instead of blocking every retry.
        backup.replace(work / ('interrupted-' + str(time.time_ns())))
    plans = {name: plan_engine(bundle / 'converters' / name, name) for name in ENGINES}
    print('Checking all converter target formats before reducing the payload...', flush=True)
    before = native_audit(ROOT / 'dist/NOP/NOP.exe', work / 'before.json')
    clear_generated(bundle, {name: original[name]['files'] for name in ENGINES},
                    filesystem_path(work / ('generated-baseline-' + str(time.time_ns()))),
                    filesystem_path(ROOT / 'runtime_deps/converters'))
    statistics = {}
    transaction = Transaction(bundle, backup)
    try:
        for name, plan in plans.items():
            folder = bundle / 'converters' / name
            before_bytes = sum(p.stat().st_size for p in folder.rglob('*') if p.is_file() and p.name != 'NOP_ENGINE_MANIFEST.json')
            removed = []
            for row in plan:
                path = folder / row['path']
                old_size = path.stat().st_size
                transaction.change('converters/' + name + '/' + row['path'], row['data'])
                removed.append({'path': row['path'], 'reason': row['reason'], 'before_bytes': old_size,
                                'after_bytes': len(row['data']) if row['data'] is not None else 0})
            after_bytes = sum(p.stat().st_size for p in folder.rglob('*') if p.is_file() and p.name != 'NOP_ENGINE_MANIFEST.json')
            statistics[name] = {'policy': POLICY, 'before_bytes': before_bytes, 'after_bytes': after_bytes,
                                'saved_bytes': before_bytes - after_bytes, 'actions': removed, 'accepted': True}
            print(name + ': payload reduced by %.1f MiB' % ((before_bytes - after_bytes) / 2**20), flush=True)
        print('Rechecking real conversions with the reduced engines...', flush=True)
        expected_after = {name: files(bundle / 'converters' / name) for name in ENGINES}
        after = native_audit(ROOT / 'dist/NOP/NOP.exe', work / 'after.json', allow_failed=True)
        clear_generated(bundle, expected_after, filesystem_path(work / ('generated-after-' + str(time.time_ns()))),
                        filesystem_path(ROOT / 'runtime_deps/converters'))
        rejected = regressions(before, after)
        for name in sorted(rejected):
            print('Keeping the original complete engine after a regression: ' + name, flush=True)
            transaction.rollback('converters/' + name)
            statistics[name].update(accepted=False, saved_bytes=0, after_bytes=statistics[name]['before_bytes'],
                                    reason='Real conversion or available-format regression; original files restored')
        if rejected:
            expected_restored = {name: files(bundle / 'converters' / name) for name in ENGINES}
            after = native_audit(ROOT / 'dist/NOP/NOP.exe', work / 'after-restore.json')
            clear_generated(bundle, expected_restored, filesystem_path(work / ('generated-restored-' + str(time.time_ns()))),
                            filesystem_path(ROOT / 'runtime_deps/converters'))
            if regressions(before, after):
                raise RuntimeError('Converter regression remains after restoring original engines')
        stamp(bundle, original, statistics, transaction)
        final = {'policy': POLICY, 'status': 'проверено на Windows/ВМ', 'windows': after['windows'],
                 'size_scope': 'Uncompressed converter files excluding generated manifests; not the compressed installer size',
                 'scope': 'Build-PC real conversions only; clean installation and other Windows releases remain untested',
                 'engines': statistics, 'baseline': str(work / 'before.json'), 'after': str(work / ('after-restore.json' if rejected else 'after.json')),
                 'saved_payload_bytes': sum(row['saved_bytes'] for row in statistics.values()),
                 'unavailable_before_compaction': [row for row in before['cases'] if not row['ok']]}
        (bundle / 'CONVERTER_COMPACTION_REPORT.json').write_text(json.dumps(final, ensure_ascii=False, indent=2), 'utf-8')
        (work / 'summary.json').write_text(json.dumps(final, ensure_ascii=False, indent=2), 'utf-8')
    except BaseException:
        transaction.rollback()
        raise
    finally:
        if not transaction.entries:
            shutil.rmtree(backup)
    # The complete vendor engines remain in runtime_deps; this backup is not shipped.
    shutil.rmtree(backup)
    print('Converter payload accepted after native before/after checks. Full SDK caches retained.', flush=True)


if __name__ == '__main__':
    if sys.argv[1:] == ['--finalize']:
        finalize()
    elif not sys.argv[1:]:
        main()
    else:
        raise SystemExit('Usage: compact_converters.py [--finalize]')
