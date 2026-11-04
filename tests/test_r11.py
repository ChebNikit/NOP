"""Regression cases for path precedence, pinned sources and resume-safe preparation."""
import ast
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import prepare_runtime as runtime
from prepare_converters import winget_x64, locate_engine
from prepare_components import trusted_ssl_context
from archive_tools import safe_member
from nop_validation import make_fixtures
from build import verify_wheels
from native_conflicts import check_inprocess_conflicts


def source_function(name, namespace):
    tree = ast.parse((ROOT / 'NOP_1.0.py').read_text('utf-8'))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), '<source-function>', 'exec'), namespace)
    return namespace[name]


class BundlePathTests(unittest.TestCase):
    def test_private_alias_wins_over_another_alias_in_path(self):
        with tempfile.TemporaryDirectory(prefix='NOP папка ') as folder:
            root = Path(folder)
            bundled = root / 'converters/libreoffice/program/soffice.exe'
            bundled.parent.mkdir(parents=True)
            bundled.touch()
            namespace = dict(Path=Path, os=os, sys=sys, shutil=shutil, APP_DIR=root)
            find = source_function('find_converter_tool', namespace)
            with mock.patch.object(shutil, 'which', return_value='C:/wrong-version/soffice.com') as which:
                self.assertEqual(find('soffice.com', 'soffice.exe'), str(bundled))
                which.assert_not_called()

    def test_bundled_ffmpeg_wins_over_system_ffmpeg(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'ffmpeg.exe').touch()
            find = source_function('find_converter_tool', dict(Path=Path, os=os, sys=sys, shutil=shutil, APP_DIR=root))
            with mock.patch.object(shutil, 'which', return_value='C:/wrong-ffmpeg.exe') as which:
                self.assertEqual(find('ffmpeg.exe', 'ffmpeg'), str(root / 'ffmpeg.exe'))
                which.assert_not_called()

    def test_missing_private_engine_can_still_find_a_source_installation(self):
        with tempfile.TemporaryDirectory() as folder:
            find = source_function('find_converter_tool', dict(Path=Path, os=os, sys=sys, shutil=shutil, APP_DIR=Path(folder)))
            with mock.patch.object(shutil, 'which', return_value='/installed/blender'):
                self.assertEqual(find('blender'), '/installed/blender')


class VendorMetadataTests(unittest.TestCase):
    def manifest(self, architecture='x64', url='https://example.org/tool.msi', digest='A' * 64):
        return 'PackageVersion: 1.2.3\nInstallers:\n- Architecture: ' + architecture + '\n  InstallerUrl: ' + url + '\n  InstallerSha256: ' + digest + '\n'

    def test_pinned_x64_manifest(self):
        value = winget_x64(self.manifest(), '1.2.3')
        self.assertEqual(value['sha256'], 'a' * 64)
        self.assertEqual(value['kind'], 'msi')

    def test_version_drift_blocks_conversion_download(self):
        with self.assertRaises(RuntimeError):
            winget_x64(self.manifest(), '1.2.4')

    def test_arm64_cannot_be_mistaken_for_x64(self):
        with self.assertRaises(RuntimeError):
            winget_x64(self.manifest(architecture='arm64'), '1.2.3')

    def test_missing_or_truncated_sha_is_rejected(self):
        with self.assertRaises(RuntimeError):
            winget_x64(self.manifest(digest='abc'), '1.2.3')

    def test_html_substituted_for_manifest_is_rejected(self):
        with self.assertRaises(RuntimeError):
            winget_x64('<html>service unavailable</html>', '1.2.3')

    def test_later_os_requirement_is_not_hidden(self):
        with self.assertRaisesRegex(RuntimeError, 'newer OS'):
            winget_x64('MinimumOSVersion: 10.0.19041.0\n' + self.manifest(), '1.2.3')

    def test_multiple_x64_installers_are_not_silently_chosen(self):
        with self.assertRaises(RuntimeError):
            winget_x64(self.manifest() + self.manifest(), '1.2.3')

    def test_non_msi_payload_is_not_executed_as_msi(self):
        with self.assertRaises(RuntimeError):
            winget_x64(self.manifest(url='https://example.org/page.html'), '1.2.3')

    def test_ambiguous_extracted_engine_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ('a', 'b'):
                (root / name).mkdir()
                (root / name / 'blender.exe').touch()
            with self.assertRaises(RuntimeError):
                locate_engine(root, 'blender.exe')


class PreparationResumeTests(unittest.TestCase):
    def test_later_component_hashes_survive_the_first_completed_stage(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            before = {'deno': {'files': {'deno.exe': 'old-hash'}}, 'mpv': {'files': {'libmpv-2.dll': 'old-hash'}}}
            (root / 'runtime-manifest.json').write_text(json.dumps(before), 'utf-8')
            def deno():
                stored = json.loads((root / 'runtime-manifest.json').read_text('utf-8'))
                self.assertEqual(stored['mpv'], before['mpv'])
                self.assertEqual(stored['deno'], before['deno'])
                return {'version': 'checked-deno'}
            with mock.patch.object(runtime.sys, 'platform', 'win32'), \
                 mock.patch.object(runtime, 'RUNTIME', root), \
                 mock.patch.object(runtime, 'CACHE', root / 'cache'), \
                 mock.patch.object(runtime, 'LOG', root / 'prepare.log'), \
                 mock.patch.object(runtime, 'prepare_ffmpeg', return_value={'version': 'checked-ffmpeg'}), \
                 mock.patch.object(runtime, 'prepare_deno', side_effect=deno), \
                 mock.patch.object(runtime, 'prepare_mpv', return_value={'version': 'checked-mpv'}):
                self.assertEqual(runtime.main(), 0)
            after = json.loads((root / 'runtime-manifest.json').read_text('utf-8'))
            self.assertEqual(set(after), {'ffmpeg', 'deno', 'mpv'})


class ArchiveAndFixtureTests(unittest.TestCase):
    def test_vendor_archive_rejects_windows_escape_paths(self):
        for path in ('../outside', '/absolute', 'C:/outside', 'dir/file:stream', 'dir/file. ', '\\server\\share'):
            with self.subTest(path=path), self.assertRaises(RuntimeError):
                safe_member(path, 1)

    def test_safe_cyrillic_vendor_path(self):
        self.assertEqual(safe_member('Каталог с пробелами/file.dll', 123), 123)

    def test_document_fixtures_have_valid_xml_and_zip(self):
        import zipfile
        from xml.etree import ElementTree
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            make_fixtures(root)
            for file in (root / 'книга.epub', root / 'презентация.odp'):
                with zipfile.ZipFile(file) as z:
                    self.assertIsNone(z.testzip())
                    for name in z.namelist():
                        if name.endswith(('.xml', '.opf', '.ncx', '.xhtml')):
                            ElementTree.fromstring(z.read(name))

    def test_shipped_windows_wheels_have_not_changed(self):
        verify_wheels()


class NativeConflictTests(unittest.TestCase):
    def test_different_same_named_media_dlls_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'mpv').mkdir()
            (root / '_internal/Qt').mkdir(parents=True)
            (root / 'mpv/avcodec-62.dll').write_bytes(b'mpv-version')
            (root / '_internal/Qt/avcodec-62.dll').write_bytes(b'qt-version')
            with self.assertRaisesRegex(RuntimeError, 'DLL conflict'):
                check_inprocess_conflicts(root)

    def test_identical_media_dlls_do_not_conflict(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'mpv').mkdir()
            (root / '_internal/Qt').mkdir(parents=True)
            for name in ('mpv', '_internal/Qt'):
                (root / name / 'avcodec-62.dll').write_bytes(b'exact-same-library')
            check_inprocess_conflicts(root)


class TLSContextTests(unittest.TestCase):
    def test_os_roots_and_certifi_keep_certificate_and_hostname_validation(self):
        import ssl
        context = trusted_ssl_context()
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertGreater(context.cert_store_stats()['x509_ca'], 0)


if __name__ == '__main__':
    unittest.main()
