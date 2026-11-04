"""Windows-only build coordinator. Every failing stage stops packaging."""
from __future__ import annotations
import datetime
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import threading
import traceback

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
PYTHON = ROOT / '.build-python' / 'python.exe'
LOG = None


def note(message):
    print(message, flush=True)
    if LOG:
        LOG.write(message + '\n')
        LOG.flush()


def run(args, timeout=1800):
    args = [str(x) for x in args]
    note('\nRUN ' + subprocess.list2cmdline(args))
    process = subprocess.Popen(args, cwd=ROOT, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        env=os.environ.copy(), creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    timed_out = threading.Event()
    def stop():
        timed_out.set()
        # Terminate this build's process tree, never a process selected by name.
        if os.name == 'nt':
            subprocess.run([str(Path(os.environ['WINDIR']) / 'System32' / 'taskkill.exe'),
                            '/PID', str(process.pid), '/T', '/F'], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=30)
        else:
            process.kill()
    timer = threading.Timer(timeout, stop)
    timer.start()
    try:
        for data in iter(process.stdout.readline, b''):
            note(data.decode('utf-8', 'replace').rstrip('\r\n'))
        code = process.wait()
    except BaseException:
        if process.poll() is None:
            stop()
            process.wait(timeout=30)
        raise
    finally:
        timer.cancel()
        process.stdout.close()
    if code or timed_out.is_set():
        raise RuntimeError(('Timed out: ' if timed_out.is_set() else 'Exit ' + str(code) + ': ') + args[0])


def verify_wheels():
    from hashlib import sha256
    records = json.loads((ROOT / 'wheelhouse-manifest.json').read_text('utf-8'))
    if not records:
        raise RuntimeError('Empty Windows wheel manifest')
    for record in records:
        path = ROOT / 'wheelhouse' / record['file']
        if path.name != record['file'] or not path.is_file():
            raise RuntimeError('Missing Windows dependency wheel: ' + record['file'])
        if sha256(path.read_bytes()).hexdigest() != record['sha256']:
            raise RuntimeError('Windows dependency wheel SHA-256 mismatch: ' + path.name)
    note('Windows dependency wheel hashes verified: ' + str(len(records)))


def main():
    global LOG
    if os.name != 'nt' or platform.machine().upper() not in ('AMD64', 'X86_64'):
        raise RuntimeError('This BuildKit must run on Windows x64, not Linux or ARM64')
    if sys.version_info[:3] != (3, 13, 17) or Path(sys.executable).resolve() != PYTHON.resolve():
        raise RuntimeError('Run build_windows.bat; the global Python must not be used')
    os.chdir(ROOT)
    for key in list(os.environ):
        if key.upper().startswith(('PYTHON', 'PIP_', 'QT_', 'QML', '_PYI_')):
            os.environ.pop(key, None)
    os.environ.update(PYTHONNOUSERSITE='1', PYTHONUTF8='1', PIP_CONFIG_FILE=os.devnull)
    os.environ['PATH'] = os.pathsep.join([str(PYTHON.parent), str(PYTHON.parent / 'Scripts'), str(Path(os.environ['WINDIR']) / 'System32' / 'WindowsPowerShell' / 'v1.0'), str(Path(os.environ['WINDIR']) / 'System32'),
                                        os.environ['WINDIR']])
    (ROOT / 'logs').mkdir(exist_ok=True)
    log_path = ROOT / 'logs' / ('build-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S') + '.log')
    stage = 'preflight'
    outcome = {'ok': False, 'windows': platform.platform(), 'build': sys.getwindowsversion().build,
               'status': 'не проверено', 'stages': [], 'log': str(log_path)}
    with log_path.open('w', encoding='utf-8') as LOG:
        try:
            if sys.getwindowsversion().build < 17763:
                raise RuntimeError('Qt 6 build requires Windows 10 1809 / 17763 or newer')
            if shutil.disk_usage(ROOT).free < 18 * 1024**3:
                raise RuntimeError('At least 18 GiB of free build space is required for all conversion engines')
            stage_dir = ROOT / 'release' / 'staging' / 'win10'
            stage_dir.mkdir(parents=True, exist_ok=True)
            for path in stage_dir.iterdir():
                if path.is_file():
                    path.unlink()
            from verify_kit import verify
            verify()
            verify_wheels()
            stages = [
                ('hashed Python dependencies', [PYTHON, '-I', '-m', 'pip', '--isolated', '--disable-pip-version-check',
                    'install', '--no-index', '--force-reinstall', '--find-links', ROOT / 'wheelhouse', '--require-hashes', '--no-warn-script-location',
                    '-r', ROOT / 'requirements-win64.lock']),
                ('dependency consistency', [PYTHON, '-I', '-m', 'pip', '--isolated', 'check']),
                ('installer prerequisites', [PYTHON, ROOT / 'prepare_components.py']),
                ('build VC runtime', [Path(os.environ['WINDIR']) / 'System32' / 'WindowsPowerShell' / 'v1.0' / 'powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                                      '-File', ROOT / 'ensure_build_vc.ps1', '-Root', ROOT]),
                ('private Inno compiler and script preflight', [Path(os.environ['WINDIR']) / 'System32' / 'WindowsPowerShell' / 'v1.0' / 'powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ROOT / 'prepare_inno.ps1', '-Root', ROOT]),
                ('static regression suite', [PYTHON, '-m', 'unittest', 'discover', '-s', 'tests', '-v']),
                ('pinned media runtimes', [PYTHON, ROOT / 'prepare_runtime.py']),
                ('private conversion engines', [PYTHON, ROOT / 'prepare_converters.py']),
                ('YouTube runtime preflight', [PYTHON, ROOT / 'youtube_stage_test.py', 'preflight']),
            ]
            for stage, command in stages:
                run(command)
                outcome['stages'].append({'stage': stage, 'ok': True})
            stage = 'PyInstaller'
            for path in (ROOT / 'dist' / 'NOP', ROOT / 'build' / 'NOP'):
                if path.exists():
                    shutil.rmtree(path)
            command = [PYTHON, '-m', 'PyInstaller', '--noconfirm', '--clean', '--windowed', '--onedir',
                '--name', 'NOP', '--icon', ROOT / 'assets' / 'nop.ico', '--version-file', ROOT / 'version_info.txt',
                '--runtime-hook', ROOT / 'runtime_hook.py', '--manifest', ROOT / 'NOP.exe.manifest']
            for module in ('nop_bundle_check', 'youtube_stage_test', 'nop_validation', 'converter_validation', 'fitz'):
                command += ['--hidden-import', module]
            for module in ('yt_dlp', 'yt_dlp_ejs', 'numpy', 'PIL', 'mutagen', 'pymupdf', 'certifi'):
                command += ['--collect-all', module]
            for package in ('PyQt6', 'numpy', 'yt-dlp', 'yt-dlp-ejs', 'Pillow', 'mutagen', 'PyMuPDF'):
                command += ['--copy-metadata', package]
            command.append(ROOT / 'NOP_1.0.py')
            run(command, timeout=3600)
            outcome['stages'].append({'stage': stage, 'ok': True})
            for stage, command in [
                ('bundle assembly', [PYTHON, ROOT / 'assemble_bundle.py']),
                ('frozen bundle check', [PYTHON, ROOT / 'check_frozen_bundle.py']),
                ('converter compaction and A/B checks', [PYTHON, ROOT / 'compact_converters.py']),
                ('frozen offline functional checks', [PYTHON, ROOT / 'validate_windows.py', '--exe', ROOT / 'dist/NOP/NOP.exe',
                   '--output', ROOT / 'build' / 'functional-self-test.json']),
                ('clean converter acceptance artifacts', [PYTHON, ROOT / 'compact_converters.py', '--finalize']),
                ('offline installer', [ROOT / '.build-tools/InnoSetup-7.1.1/ISCC.exe', ROOT / 'NOP_installer.iss']),
            ]:
                run(command, timeout=9000 if stage == 'converter compaction and A/B checks' else 3600)
                outcome['stages'].append({'stage': stage, 'ok': True})
            if os.environ.get('NOP_TEST_ONLINE') == '1':
                stage = 'frozen YouTube download (explicit online check)'
                run([PYTHON, ROOT / 'youtube_stage_test.py', 'frozen'], timeout=900)
                outcome['stages'].append({'stage': stage, 'ok': True})
            else:
                outcome['stages'].append({'stage': 'YouTube live network download', 'status': 'не проверено', 'reason': 'Online check is optional; set NOP_TEST_ONLINE=1 to run it. Offline runtime/import checks remain mandatory.'})
            setup = stage_dir / 'NOP_Setup.exe'
            if not setup.is_file() or setup.stat().st_size < 10000000:
                raise RuntimeError('Inno Setup did not create a complete NOP_Setup.exe')
            with setup.open('rb') as stream:
                if stream.read(2) != b'MZ':
                    raise RuntimeError('Inno Setup output has no Windows executable signature')
            from promote_release import sha256, promote_release
            (stage_dir / 'SHA256.txt').write_text(sha256(setup) + '  NOP_Setup.exe\n', 'ascii')
            for name in ('bundle-manifest.json', 'DEPENDENCIES_RU.txt', 'CONVERTER_COMPACTION_REPORT.json'):
                shutil.copy2(ROOT / 'dist' / 'NOP' / name, stage_dir / name)
            compact_report_path = stage_dir / 'CONVERTER_COMPACTION_REPORT.json'
            compact_report = json.loads(compact_report_path.read_text('utf-8'))
            compact_report['installer_bytes'] = setup.stat().st_size
            compact_report['original_installer_bytes'] = None
            compact_report_path.write_text(json.dumps(compact_report, ensure_ascii=False, indent=2), 'utf-8')
            promote_release(ROOT, 'win10')
            outcome['ok'] = True
            outcome['status'] = 'проверено на Windows/ВМ'
            outcome['scope'] = 'Build PC checks only; not proof of clean-OS installation or LTSC 1809 compatibility'
            note('\nCREATED: ' + str(ROOT / 'release' / 'NOP_Setup.exe'))
            note('Clean-VM installation, upgrade, uninstallation and the target Windows matrix still require acceptance tests.')
            return 0
        except BaseException as error:
            outcome.update(failed_stage=stage, error=str(error), traceback=traceback.format_exc())
            note('BUILD FAILED at ' + stage + ': ' + str(error))
            note(traceback.format_exc())
            return 1
        finally:
            LOG.flush()
            (ROOT / 'logs' / 'last-build.json').write_text(json.dumps(outcome, ensure_ascii=False, indent=2), 'utf-8')
    LOG = None


if __name__ == '__main__':
    raise SystemExit(main())
