"""Run a frozen NOP check on the current Windows host; never infer other OS results."""
import argparse
import json
import os
from pathlib import Path
import platform
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if os.name != 'nt':
        raise RuntimeError('Windows is required; Linux results cannot certify this application')
    exe, output = args.exe.resolve(), args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.unlink(missing_ok=True)
    environment = {k: v for k, v in os.environ.items()
                   if not k.upper().startswith(('PYTHON', '_PYI_', 'QT_', 'QML'))}
    environment.pop('YAMI_BACKEND', None)
    environment['PATH'] = os.pathsep.join([str(Path(environment['WINDIR']) / 'System32'), environment['WINDIR']])
    environment['QT_QPA_PLATFORM'] = 'windows'
    native_log = output.with_suffix('.native.log')
    try:
        with native_log.open('wb') as log:
            process = subprocess.run([str(exe), '--nop-functional-check', str(output)],
                cwd=exe.parent, env=environment, stdout=log, stderr=subprocess.STDOUT, timeout=1200)
    except subprocess.TimeoutExpired:
        raise RuntimeError('Functional test exceeded 20 minutes; see ' + str(output) + ' / ' + str(native_log))
    if not output.is_file():
        raise RuntimeError('Frozen EXE produced no report; exit ' + str(process.returncode) + '; see ' + str(native_log))
    result = json.loads(output.read_text('utf-8'))
    for check in result.get('checks', []):
        print(('PASS ' if check.get('ok') else 'FAIL ') + check['name'] + ': ' + check.get('detail', ''))
    if process.returncode or not result.get('ok'):
        raise RuntimeError('Frozen functional checks failed: ' + str(output))
    print('Passed on this host only: ' + result['windows']['platform'])
    print('Manual acceptance items remain: ' + str(len(result['manual_checks'])))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
