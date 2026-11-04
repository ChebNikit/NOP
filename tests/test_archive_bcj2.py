"""Regression coverage for the native BCJ2 archive extractor."""
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

import archive_tools

ROOT = Path(archive_tools.__file__).resolve().parent
FIXTURE = ROOT / '.build-tools' / '7zip-26.05' / 'bcj2-test.7z'
MEMBER = '\u043a\u0430\u0442\u0430\u043b\u043e\u0433 \u0441 \u043f\u0440\u043e\u0431\u0435\u043b\u0430\u043c\u0438/\u0442\u0435\u0441\u0442 BCJ2.bin'
CONTENT_SHA256 = '05f9d5fd24ab92c2797747a3a9f1afbae187feb02833fd16c69dc5e6c7391fc6'


class BCJ2RegressionTests(unittest.TestCase):
    def test_fixture_really_uses_bcj2(self):
        import py7zr
        with py7zr.SevenZipFile(FIXTURE) as archive:
            self.assertTrue(any('BCJ2' in m for m in archive.archiveinfo().method_names))

    @unittest.skipUnless(os.name == 'nt', 'Windows 7za.exe must be run on Windows')
    def test_native_bcj2_roundtrip_in_unicode_path(self):
        with tempfile.TemporaryDirectory(prefix='NOP BCJ2 \u044f ') as temp:
            target = Path(temp) / 'output with spaces \u044f'
            archive_tools.extract_7z(FIXTURE, target)
            self.assertEqual(hashlib.sha256((target / MEMBER).read_bytes()).hexdigest(), CONTENT_SHA256)

    def test_changed_native_tool_is_not_started(self):
        with tempfile.TemporaryDirectory() as temp:
            wrong = Path(temp) / '7za.exe'
            wrong.write_bytes(b'truncated or substituted executable')
            with mock.patch.object(archive_tools, 'SEVENZIP', wrong), \
                 mock.patch.object(archive_tools.subprocess, 'run') as run:
                with self.assertRaisesRegex(RuntimeError, 'SHA-256 mismatch'):
                    archive_tools.extract_7z(FIXTURE, Path(temp) / 'out')
                run.assert_not_called()

    def test_missing_native_tool_has_specific_diagnostic(self):
        with tempfile.TemporaryDirectory() as temp:
            with mock.patch.object(archive_tools, 'SEVENZIP', Path(temp) / 'missing.exe'):
                with self.assertRaisesRegex(RuntimeError, 'Private 7-Zip 26.05 is unavailable'):
                    archive_tools.extract_7z(FIXTURE, Path(temp) / 'out')

    def test_native_failure_includes_exit_and_diagnostic(self):
        with tempfile.TemporaryDirectory() as temp:
            with mock.patch.object(archive_tools.subprocess, 'run',
                    return_value=subprocess.CompletedProcess([], 2, 'ERROR: archive CRC failed')):
                with self.assertRaisesRegex(RuntimeError, 'exit 2.*') as error:
                    archive_tools.extract_7z(FIXTURE, Path(temp) / 'out')
                self.assertIn('archive CRC failed', str(error.exception))

    def test_native_timeout_is_not_reported_as_success(self):
        with tempfile.TemporaryDirectory() as temp:
            with mock.patch.object(archive_tools.subprocess, 'run',
                    side_effect=subprocess.TimeoutExpired('7za.exe', 900)):
                with self.assertRaisesRegex(RuntimeError, 'Cannot finish private 7-Zip extraction'):
                    archive_tools.extract_7z(FIXTURE, Path(temp) / 'out')


if __name__ == '__main__':
    unittest.main()
