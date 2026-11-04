"""Offline source completeness and HTTP 429 regression coverage."""
import hashlib
import io
import json
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
import urllib.error

import prepare_components as components
import prepare_converters as converters


class BundledSourceTests(unittest.TestCase):
    def snapshot(self, directory):
        root = Path(directory)
        lock = root/'converter_sources.lock.json'
        metadata = root/'bootstrap/converters'
        shutil.copyfile(converters.LOCK,lock)
        shutil.copytree(converters.METADATA,metadata)
        return root,lock,metadata

    def test_all_four_sources_validate_with_metadata_network_blocked(self):
        config = json.loads(converters.CONFIG.read_text('utf-8'))
        with mock.patch('urllib.request.urlopen',side_effect=urllib.error.HTTPError('https://metadata.example',429,'limited',{},None)) as http:
            records = converters.load_sources(config)
        self.assertEqual(set(records),{'libreoffice','blender','inkscape','calibre'})
        http.assert_not_called()

    def test_partial_legacy_cache_cannot_override_complete_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            root,lock,metadata = self.snapshot(temp)
            legacy = root/'.build-tools/converter-sources.lock.json'
            legacy.parent.mkdir()
            legacy.write_text('{"blender": {"old": true}}')
            before = legacy.read_bytes()
            with mock.patch.object(converters,'LOCK',lock), mock.patch.object(converters,'METADATA',metadata):
                records = converters.load_sources(json.loads(converters.CONFIG.read_text()))
            self.assertEqual(len(records),4)
            self.assertEqual(legacy.read_bytes(),before)

    def test_missing_component_is_rejected_before_any_download(self):
        with tempfile.TemporaryDirectory() as temp:
            _,lock,metadata = self.snapshot(temp)
            records = json.loads(lock.read_text());del records['inkscape']
            lock.write_text(json.dumps(records))
            with mock.patch.object(converters,'LOCK',lock), mock.patch.object(converters,'METADATA',metadata), \
                 mock.patch.object(converters,'download') as download:
                with self.assertRaisesRegex(RuntimeError,'all configured engines'):
                    converters.load_sources(json.loads(converters.CONFIG.read_text()))
                download.assert_not_called()

    def test_changed_upstream_evidence_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            _,lock,metadata = self.snapshot(temp)
            (metadata/'libreoffice.installer.yaml').write_text('tampered metadata')
            with mock.patch.object(converters,'LOCK',lock), mock.patch.object(converters,'METADATA',metadata):
                with self.assertRaisesRegex(RuntimeError,'Missing/changed bundled converter evidence'):
                    converters.load_sources(json.loads(converters.CONFIG.read_text()))

    def test_pinned_binary_hash_must_match_upstream_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            _,lock,metadata = self.snapshot(temp)
            records = json.loads(lock.read_text());records['libreoffice']['sha256']='0'*64
            lock.write_text(json.dumps(records))
            with mock.patch.object(converters,'LOCK',lock), mock.patch.object(converters,'METADATA',metadata):
                with self.assertRaisesRegex(RuntimeError,'differs from bundled upstream evidence'):
                    converters.load_sources(json.loads(converters.CONFIG.read_text()))

    def test_x64_msi_is_selected_alongside_x64_exe_and_arm64_msi(self):
        text = ('PackageVersion: 1.2.3\nInstallers:\n'
                '- Architecture: x64\n  InstallerType: wix\n  InstallerUrl: https://vendor.example/tool.msi\n  InstallerSha256: '+ 'A'*64+'\n'
                '- Architecture: arm64\n  InstallerType: wix\n  InstallerUrl: https://vendor.example/tool-x64.msi\n  InstallerSha256: '+ 'B'*64+'\n'
                '- Architecture: x64\n  InstallerType: nullsoft\n  InstallerUrl: https://vendor.example/tool.exe\n  InstallerSha256: '+ 'C'*64+'\n')
        result = converters.winget_x64(text,'1.2.3')
        self.assertEqual(result['url'],'https://vendor.example/tool.msi')
        self.assertEqual(result['sha256'],'a'*64)

    def test_preparation_uses_snapshot_without_rewriting_it(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            before = converters.LOCK.read_bytes()
            staged = []
            def stage(name,entry,record):
                staged.append(name)
                return record
            with mock.patch.object(converters,'os',SimpleNamespace(name='nt')), \
                 mock.patch.object(converters,'RUNTIME',root), \
                 mock.patch.object(converters,'stage_one',side_effect=stage), \
                 mock.patch('urllib.request.urlopen',side_effect=AssertionError('Metadata network request')):
                converters.main()
            self.assertEqual(len(staged),4)
            self.assertEqual(converters.LOCK.read_bytes(),before)
            self.assertEqual(len(json.loads((root/'converters-manifest.json').read_text())),4)


class Response(io.BytesIO):
    def __init__(self,data):
        super().__init__(data)
        self.headers = {'Content-Length':str(len(data))}
    def geturl(self):return 'https://vendor.example/payload'


class RateLimitTests(unittest.TestCase):
    def error(self,after=None):
        return urllib.error.HTTPError('https://vendor.example/payload',429,'limited',
                                      {'Retry-After':after} if after is not None else {},None)

    def test_valid_cached_download_needs_no_network(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'cached.msi';path.write_bytes(b'verified cached binary')
            expected = hashlib.sha256(path.read_bytes()).hexdigest()
            with mock.patch.object(components.urllib.request,'urlopen',side_effect=self.error()) as http:
                components.download('https://vendor.example/payload',path,expected,minimum=1)
            http.assert_not_called()

    def test_download_retries_429_then_verifies_sha256(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'payload.msi';data = b'complete package bytes'
            with mock.patch.object(components.urllib.request,'urlopen',side_effect=[self.error('3'),Response(data)]) as http, \
                 mock.patch.object(components,'trusted_ssl_context',return_value=object()), \
                 mock.patch.object(components.time,'sleep') as sleep:
                components.download('https://vendor.example/payload',path,hashlib.sha256(data).hexdigest(),minimum=1)
            self.assertEqual(http.call_count,2)
            sleep.assert_called_once_with(3)
            self.assertEqual(path.read_bytes(),data)
            self.assertFalse(path.with_name(path.name+'.part').exists())

    def test_persistent_429_stops_after_three_attempts_and_preserves_cache(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'payload.msi';path.write_bytes(b'old cache bytes')
            with mock.patch.object(components.urllib.request,'urlopen',side_effect=self.error()) as http, \
                 mock.patch.object(components,'trusted_ssl_context',return_value=object()), \
                 mock.patch.object(components.time,'sleep') as sleep:
                with self.assertRaisesRegex(RuntimeError,'HTTP 429'):
                    components.download('https://vendor.example/payload',path,'0'*64,minimum=1)
            self.assertEqual(http.call_count,3)
            self.assertEqual(sleep.call_count,2)
            self.assertEqual(path.read_bytes(),b'old cache bytes')

    def test_long_retry_after_does_not_retry_before_the_requested_time(self):
        with self.assertRaisesRegex(RuntimeError,'resume later'):
            components.rate_limit_delay(self.error('120'),0)

    def test_http_date_retry_after_is_understood(self):
        from datetime import datetime,timezone
        from email.utils import format_datetime
        now = 1700000000
        after = format_datetime(datetime.fromtimestamp(now+5,timezone.utc),usegmt=True)
        with mock.patch.object(components.time,'time',return_value=now):
            delay = components.rate_limit_delay(self.error(after),0)
        self.assertGreaterEqual(delay,5)
        self.assertLessEqual(delay,6)

    def test_json_request_retries_429(self):
        with mock.patch.object(components.urllib.request,'urlopen',side_effect=[self.error('2'),Response(b'{"ok":true}')]) as http, \
             mock.patch.object(components,'trusted_ssl_context',return_value=object()), \
             mock.patch.object(components.time,'sleep') as sleep:
            self.assertEqual(components.request_json('https://vendor.example/payload'),{'ok':True})
        self.assertEqual(http.call_count,2)
        sleep.assert_called_once_with(2)


if __name__ == '__main__':unittest.main()
