"""Version-stage regression: static conditional checks and real Windows ISCC checks.

The C preprocessor checks only the shared #ifdef/#include/#error syntax on Linux.
It is not an Inno/Pascal compiler and does not certify an installer.
"""
from pathlib import Path
import os
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
ISCC = ROOT / '.build-tools' / 'InnoSetup-7.1.1' / 'ISCC.exe'
CPP = shutil.which('cpp')


def versions_header():
    source = (ROOT / 'assemble_bundle.py').read_text('utf-8')
    block = source.split('    macros = {', 1)[1].split('\n    }', 1)[0]
    names = re.findall(r'"([A-Za-z]+Version)"\s*:', block)
    return '\n'.join('#define ' + name + ' "99.1"' for name in names) + '\n'


def fixture(root, versions):
    shutil.copy2(ROOT / 'NOP_installer.iss', root / 'NOP_installer.iss')
    if versions is not None:
        (root / 'installer_versions.iss').write_text(versions, 'utf-8-sig')


@unittest.skipUnless(CPP and os.name != 'nt', 'Linux static preprocessor check only')
class StaticInnoConditionTests(unittest.TestCase):
    def preprocess(self, root, preflight):
        args = [CPP, '-traditional-cpp', '-P']
        if preflight:
            args.append('-DNOP_BUILDKIT_PREFLIGHT=1')
        return subprocess.run(args + [str(root / 'NOP_installer.iss')],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)

    def test_preflight_ignores_missing_placeholder_and_old_generated_versions(self):
        for header in (None, '#error GENERATED_VERSIONS_MUST_NOT_BE_READ\n', versions_header()):
            with self.subTest(header=header), tempfile.TemporaryDirectory(prefix='nop-inno я (1) ') as temp:
                root = Path(temp)
                fixture(root, header)
                result = self.preprocess(root, True)
                self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', 'replace'))
                output = result.stdout.decode('utf-8')
                self.assertIn('OutputBaseFilename=compiler-check', output)
                self.assertNotIn('OutputBaseFilename=NOP_Setup', output)
                self.assertIn('function InitializeSetup(): Boolean;', output)
                self.assertNotIn('Source: "dist', output)

    def test_release_still_requires_actual_generated_versions(self):
        for header in (None, '#error ACTUAL_VERSIONS_NOT_READY\n'):
            with self.subTest(header=header), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                fixture(root, header)
                self.assertNotEqual(self.preprocess(root, False).returncode, 0)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixture(root, versions_header())
            result = self.preprocess(root, False)
            self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', 'replace'))
            output = result.stdout.decode('utf-8')
            self.assertIn('OutputBaseFilename=NOP_Setup', output)
            self.assertNotIn('PREFLIGHT', output)
            self.assertNotIn('function InitializeSetup(): Boolean;', output)


@unittest.skipUnless(os.name == 'nt', 'Requires a real Windows Inno compiler')
class WindowsInnoCompilerTests(unittest.TestCase):
    def setUp(self):
        if not ISCC.is_file():
            self.skipTest('Private ISCC is not prepared; build.py prepares it before this suite')

    def run_iscc(self, root, *options):
        return subprocess.run([str(ISCC), *options, str(root / 'NOP_installer.iss')],
                              cwd=root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              timeout=180, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))

    def test_real_preflight_compiles_with_poisoned_versions_in_unicode_directory(self):
        with tempfile.TemporaryDirectory(prefix='nop-inno я (1) ') as temp:
            root = Path(temp)
            fixture(root, '#error GENERATED_VERSIONS_MUST_NOT_BE_READ\n')
            for name in ('assets/nop.ico', 'installer-art/wizard.png', '.build-tools/7zip-full-26.05/7z.exe'):
                dest = root / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / name, dest)
            result = self.run_iscc(root, '/DNOP_BUILDKIT_PREFLIGHT=1')
            self.assertEqual(result.returncode, 0, result.stdout.decode('utf-8', 'replace'))
            exe = root / '.build-tools/inno-preflight/compiler-check.exe'
            self.assertTrue(exe.is_file())
            with exe.open('rb') as stream:
                self.assertEqual(stream.read(2), b'MZ')
            self.assertFalse((root / 'release/staging/win10/NOP_Setup.exe').exists())

    def test_real_release_preprocessor_rejects_placeholder(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixture(root, '#error ACTUAL_VERSIONS_NOT_READY\n')
            result = self.run_iscc(root, '--preprocess')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(b'ACTUAL_VERSIONS_NOT_READY', result.stdout)

    def test_real_release_preprocessor_accepts_generated_header_without_preflight_labels(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixture(root, versions_header())
            result = self.run_iscc(root, '--preprocess')
            self.assertEqual(result.returncode, 0, result.stdout.decode('utf-8', 'replace'))
            self.assertNotIn(b'PREFLIGHT', result.stdout)
            self.assertIn(b'OutputBaseFilename=NOP_Setup', result.stdout)


if __name__ == '__main__':
    unittest.main()
