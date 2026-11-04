"""MSI data extraction regression tests. No Windows Installer service is used."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock
import msi_payload as m


class MsiPayloadTests(unittest.TestCase):
    def test_all_actual_vendor_maps_are_valid(self):
        source = json.loads((m.ROOT / 'converter_sources.lock.json').read_text('utf-8'))
        for name in ('libreoffice','inkscape','calibre'):
            with self.subTest(name=name):
                c=m.load_catalog(name,source[name]['sha256'])
                self.assertGreater(len(c['files']),1000)
                self.assertTrue(all(target is None or not target.startswith(('System/','System64/')) for _,target,_ in c['files']))

    def test_wrong_archive_cannot_use_a_map(self):
        with self.assertRaisesRegex(RuntimeError,'does not match'):
            m.load_catalog('libreoffice','0'*64)

    def test_incorrect_cabinet_file_size_is_rejected(self):
        c={'files':[['file_a','program/a.txt',12]]}
        m.check_cabinet_listing('Path = file_a\nSize = 12\n',c)
        with self.assertRaisesRegex(RuntimeError,'differs'):
            m.check_cabinet_listing('Path = file_a\nSize = 11\n',c)

    def test_unsafe_installed_names_are_rejected(self):
        for name in ('../escape','/absolute','C:/drive','a/../../escape','a/CON.txt','a/trailing.','a\\b','a/./b','a:b'):
            with self.subTest(name=name),self.assertRaises(RuntimeError):m.safe_relative(name)

    def test_inkscape_trailing_dot_keys_are_mapped_explicitly(self):
        m.safe_key('CM_name...')
        self.assertEqual(m.disk_key('CM_name...',True),'CM_name___')
        self.assertEqual(m.disk_key('CM_name...',False),'CM_name...')
        c={'files':[['CM_name...','valid.png',5]]}
        m.check_cabinet_listing('Path = CM_name...\nSize = 5\n',c)

    def test_changed_private_dll_blocks_native_execution(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'7z.exe').write_bytes(b'exe');(root/'7z.dll').write_bytes(b'changed')
            expected={'7z.exe':m.digest(root/'7z.exe'),'7z.dll':'0'*64}
            with mock.patch.object(m,'TOOL',root/'7z.exe'),mock.patch.object(m,'TOOL_HASHES',expected),mock.patch.object(m.subprocess,'run') as run:
                with self.assertRaisesRegex(RuntimeError,'missing/changed'):m.verified_tool()
                run.assert_not_called()

    def test_native_exit_code_and_diagnostic_are_retained(self):
        with tempfile.TemporaryDirectory() as temp:
            log=Path(temp)/'extract.log'
            with mock.patch.object(m.subprocess,'run',return_value=subprocess.CompletedProcess([],2,'CRC failed')):
                with self.assertRaisesRegex(RuntimeError,'exit 2'):m.native('7z.exe',['t','payload.cab'],log)
            self.assertIn('CRC failed',log.read_text())

    @unittest.skipUnless(os.name=='nt','Real private Windows 7-Zip requires Windows')
    def test_real_private_tool_extracts_msi_without_msiexec(self):
        with tempfile.TemporaryDirectory(prefix='nop-data я (1) ') as temp:
            root=Path(temp);out=root/'output я';log=root/'extract.log'
            fixture=m.ROOT/'tests/fixtures/msi-quote-test.msi'
            self.assertEqual(m.extract_msi(fixture,out,'fixture',m.digest(fixture),log),1)
            payload=out/'folder/payload.txt'
            self.assertEqual(payload.stat().st_size,75)
            self.assertEqual(m.digest(payload),'6b0559efc8ee6372ce4162d254dec51e0c9f741547a2b1e1cb48ffdaf3b2e808')
            self.assertNotIn('msiexec.exe',log.read_text('utf-8'))

if __name__=='__main__':unittest.main()
