"""Compaction must preserve conversion resources and restore real bytes on failure."""
import copy
import json
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
from xml.dom import minidom
import zipfile

import compact_converters as compact
from converter_validation import glb_signature


class CompactionTests(unittest.TestCase):
    def put(self, root, relative, data=b'original bytes'):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def test_dictionary_data_and_registrations_are_removed_without_losing_hyphenation_or_xml_types(self):
        xml = b'''<oor:component-data xmlns:oor="http://openoffice.org/2001/registry" xmlns:xs="http://www.w3.org/2001/XMLSchema"><node oor:name="Dictionaries">
        <node oor:name="Spell"><prop oor:name="Locations" oor:type="oor:string-list"><value>%origin%/test.aff %origin%/test.dic</value></prop><prop oor:name="Format" oor:type="xs:string"><value>DICT_SPELL</value></prop></node>
        <node oor:name="Thes"><prop oor:name="Locations"><value>%origin%/th_test.dat</value></prop><prop oor:name="Format"><value>DICT_THES</value></prop></node>
        <node oor:name="Hyph"><prop oor:name="Locations"><value>%origin%/hyph_test.dic</value></prop><prop oor:name="Format" oor:type="xs:string"><value>DICT_HYPH</value></prop></node></node></oor:component-data>'''
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = 'share/extensions/dict-test/'
            self.put(root, base + 'dictionaries.xcu', xml)
            for name in ('test.aff', 'test.dic', 'th_test.dat', 'th_test.idx', 'hyph_test.dic', 'COPYING'):
                self.put(root, base + name)
            plan = compact.plan_engine(root, 'libreoffice')
            deletes = {row['path'] for row in plan if row['data'] is None}
            self.assertEqual(deletes, {base + name for name in ('test.aff', 'test.dic', 'th_test.dat', 'th_test.idx')})
            data = next(row['data'] for row in plan if row['path'].endswith('.xcu'))
            document = minidom.parseString(data)
            self.assertEqual(document.documentElement.getAttribute('xmlns:xs'), 'http://www.w3.org/2001/XMLSchema')
            self.assertIn(b'DICT_HYPH', data)
            self.assertNotIn(b'DICT_SPELL', data)
            self.assertNotIn(b'DICT_THES', data)
            # A second plan on an already compacted tree is empty.
            for row in plan:
                path = root / row['path']
                if row['data'] is None:
                    path.unlink()
                else:
                    path.write_bytes(row['data'])
            self.assertEqual(compact.plan_engine(root, 'libreoffice'), [])

    def test_native_libraries_fonts_hyphenation_and_licenses_are_not_pruned(self):
        for engine, relative in (
            ('blender', 'cycles_kernel_oneapi_aot.dll'),
            ('blender', '4.2/python/bin/python311.dll'),
            ('blender', '4.2/scripts/addons_core/io_scene_gltf2/__init__.py'),
            ('blender', '4.2/datafiles/fonts/Noto Sans CJK Regular.woff2'),
            ('libreoffice', 'share/extensions/dict-ja/hyph_ja.dic'),
            ('libreoffice', 'program/swlo.dll'),
            ('libreoffice', 'share/fonts/truetype/NotoSansDevanagari.ttf'),
            ('libreoffice', 'program/resource/ru/LC_MESSAGES/sw.mo'),
            ('inkscape', 'share/inkscape/extensions/dxf_outlines.py'),
            ('inkscape', 'share/inkscape/tutorials/COPYING'),
            ('inkscape', 'share/poppler/cMap/Adobe-Japan1/UniJIS-UTF8-H'),
            ('calibre', 'app/bin/Qt6WebEngineCore.dll'),
            ('calibre', 'app/translations/qtwebengine_locales/en-US.pak'),
            ('calibre', 'app/translations/qtwebengine_locales/ru.pak'),
            ('calibre', 'app/resources/hyphenation/dictionaries.tar.xz'),
        ):
            with self.subTest(engine=engine, path=relative):
                self.assertIsNone(compact.resource_reason(engine, relative))

    def test_calibre_locale_archive_is_kept_including_all_language_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / 'app/resources/localization/locales.zip'
            path.parent.mkdir(parents=True)
            with zipfile.ZipFile(path, 'w') as archive:
                for name in ('ru/messages.mo', 'en_GB/messages.mo', 'fr/messages.mo', 'fr/lcdata.calibre_msgpack', 'fr/iso639.mo'):
                    archive.writestr(name, name)
            before = path.read_bytes()
            self.assertEqual(compact.plan_engine(root, 'calibre'), [])
            self.assertEqual(path.read_bytes(), before)

    def test_transaction_can_restore_one_engine_then_all_remaining_files(self):
        with tempfile.TemporaryDirectory(prefix='nop compact я (1) ') as temporary:
            root = Path(temporary) / 'bundle'
            self.put(root, 'converters/libreoffice/a.xml', b'original office')
            self.put(root, 'converters/blender/kernel.zst', b'original kernel')
            tx = compact.Transaction(root, Path(temporary) / 'outside-bundle-backup')
            tx.change('converters/libreoffice/a.xml', b'first edit')
            tx.change('converters/libreoffice/a.xml', b'second edit')
            tx.change('converters/blender/kernel.zst', None)
            tx.rollback('converters/libreoffice')
            self.assertEqual((root / 'converters/libreoffice/a.xml').read_bytes(), b'original office')
            self.assertFalse((root / 'converters/blender/kernel.zst').exists())
            tx.rollback()
            self.assertEqual((root / 'converters/blender/kernel.zst').read_bytes(), b'original kernel')
            self.assertEqual(tx.entries, [])

    def test_filesystem_failure_after_a_replacement_restores_original_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'bundle'
            self.put(root, 'engine/first', b'first original')
            tx = compact.Transaction(root, Path(temporary) / 'backup')
            try:
                tx.change('engine/first', b'changed')
                tx.change('engine/missing', None)
                self.fail('Missing file must not be silently removed')
            except RuntimeError:
                tx.rollback()
            self.assertEqual((root / 'engine/first').read_bytes(), b'first original')

    def test_failed_readback_does_not_hide_a_lost_successful_export(self):
        before = {'cases': [{'id': 'vector -> eps', 'engine': 'inkscape', 'export_ok': True, 'ok': False}],
                  'capabilities': dict.fromkeys(compact.ENGINES)}
        after = copy.deepcopy(before)
        after['cases'][0]['export_ok'] = False
        self.assertEqual(compact.regressions(before, after), {'inkscape'})

    def test_semantic_or_capability_regression_restores_the_affected_engine(self):
        before = {'cases': [{'id': 'document -> pdf', 'engine': 'libreoffice', 'ok': True, 'export_ok': True,
                             'signature': {'text': 'same document', 'pages': 1}}],
                  'capabilities': dict.fromkeys(compact.ENGINES)}
        after = copy.deepcopy(before)
        after['cases'][0]['signature']['pages'] = 2
        after['capabilities']['blender'] = ['obj']
        self.assertEqual(compact.regressions(before, after), {'libreoffice', 'blender'})

    def test_changed_test_matrix_cannot_certify_a_compact_runtime(self):
        before = {'cases': [{'id': 'one', 'engine': 'blender', 'ok': False}], 'capabilities': {}}
        with self.assertRaisesRegex(RuntimeError, 'matrix differs'):
            compact.regressions(before, {'cases': [], 'capabilities': {}})

    def test_glb_validation_rejects_wrong_length_and_empty_geometry(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'triangle.glb'
            doc = {'meshes': [{'primitives': [{'attributes': {'POSITION': 0}}]}],
                   'accessors': [{'count': 3, 'min': [0, 0, 0], 'max': [1, 1, 0]}]}
            data = json.dumps(doc).encode()
            path.write_bytes(struct.pack('<4sIIII', b'glTF', 2, len(data) + 20, len(data), 0x4E4F534A) + data)
            self.assertEqual(glb_signature(path)['meshes'][0]['positions'], 3)
            path.write_bytes(path.read_bytes()[:-1])
            with self.assertRaisesRegex(RuntimeError, 'Invalid GLB'):
                glb_signature(path)

    def controller_fixture(self, kit):
        bundle = kit / 'dist/NOP'
        optional = {'libreoffice': 'program/resource/fr/LC_MESSAGES/sw.mo',
                    'blender': '4.2/scripts/addons_core/cycles/lib/kernel_sm_75.cubin',
                    'inkscape': 'include/developer.h', 'calibre': 'app/share/espeak-ng-data/voice'}
        records = {}
        for engine, name in optional.items():
            folder = bundle / 'converters' / engine
            self.put(folder, 'core.dll', b'preserve this native library')
            self.put(folder, name, b'optional resource')
            records[engine] = {'files': compact.files(folder), 'version': 'unit-fixture'}
            self.put(folder, 'NOP_ENGINE_MANIFEST.json', json.dumps(records[engine]).encode())
        self.put(bundle, 'converters-manifest.json', json.dumps(records).encode())
        self.put(bundle, 'bundle-manifest.json', json.dumps({'converters': records}).encode())
        self.put(kit, 'runtime_deps/preserved-cache', b'keep the complete SDK cache')
        report = {'ok': True, 'complete': True, 'windows': {'platform': 'UNIT SIMULATION, not Windows'},
                  'cases': [{'id': engine, 'engine': engine, 'ok': True, 'export_ok': True, 'signature': {'content': 42}}
                            for engine in compact.ENGINES],
                  'capabilities': {engine: ['existing-format'] for engine in compact.ENGINES}}
        return bundle, optional, report

    def test_controller_unit_simulation_restores_one_regressed_engine_and_accepts_the_others(self):
        with tempfile.TemporaryDirectory() as temporary:
            kit = Path(temporary)
            bundle, optional, before = self.controller_fixture(kit)
            after = copy.deepcopy(before)
            after['cases'][-1]['signature'] = {'content': 'regression'}
            stale = kit / 'build/converter-compaction/backup'
            self.put(stale, 'previous-interrupted-journal', b'preserve for diagnosis')
            with mock.patch.object(compact, 'ROOT', kit), mock.patch.object(compact, 'os', SimpleNamespace(name='nt')), \
                    mock.patch.object(compact, 'native_audit', side_effect=[before, after, before]) as audit:
                compact.main()
            self.assertEqual(audit.call_count, 3)
            summary = json.loads((bundle / 'CONVERTER_COMPACTION_REPORT.json').read_text())
            for engine, name in optional.items():
                self.assertEqual((bundle / 'converters' / engine / name).exists(), engine == 'calibre')
                marker = json.loads((bundle / 'converters' / engine / 'NOP_ENGINE_MANIFEST.json').read_text())
                self.assertEqual(marker['files'], compact.files(bundle / 'converters' / engine))
                self.assertEqual(summary['engines'][engine]['accepted'], engine != 'calibre')
            self.assertEqual((kit / 'runtime_deps/preserved-cache').read_bytes(), b'keep the complete SDK cache')
            self.assertTrue(list((kit / 'build/converter-compaction').glob('interrupted-*/previous-interrupted-journal')))
            self.assertFalse(stale.exists())

    def test_controller_unit_simulation_rolls_back_all_files_if_native_audit_cannot_finish(self):
        with tempfile.TemporaryDirectory() as temporary:
            kit = Path(temporary)
            bundle, optional, before = self.controller_fixture(kit)
            original = {p.relative_to(bundle).as_posix(): p.read_bytes() for p in bundle.rglob('*') if p.is_file()}
            with mock.patch.object(compact, 'ROOT', kit), mock.patch.object(compact, 'os', SimpleNamespace(name='nt')), \
                    mock.patch.object(compact, 'native_audit', side_effect=[before, RuntimeError('native audit interrupted')]):
                with self.assertRaisesRegex(RuntimeError, 'audit interrupted'):
                    compact.main()
            self.assertEqual({p.relative_to(bundle).as_posix(): p.read_bytes() for p in bundle.rglob('*') if p.is_file()}, original)
            self.assertFalse((kit / 'build/converter-compaction/backup').exists())

    def test_generated_cache_is_quarantined_while_vendor_bytecode_is_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            kit = Path(temporary)
            bundle, _, _ = self.controller_fixture(kit)
            vendor = self.put(bundle / 'converters/blender', '4.2/python/original.pyc', b'vendor supplied bytecode')
            expected = {name: compact.files(bundle / 'converters' / name) for name in compact.ENGINES}
            generated = self.put(bundle / 'converters/blender', '4.2/scripts/__pycache__/created.pyc', b'created during acceptance')
            moved = compact.clear_generated(bundle, expected, kit / 'outside-bundle')
            self.assertEqual(moved, [{'path': 'blender/4.2/scripts/__pycache__/created.pyc', 'action': 'quarantined acceptance-generated file'}])
            self.assertFalse(generated.exists())
            self.assertEqual(vendor.read_bytes(), b'vendor supplied bytecode')
            self.assertEqual((kit / 'outside-bundle/blender/4.2/scripts/__pycache__/created.pyc').read_bytes(), b'created during acceptance')

    def test_cleanup_does_not_silently_accept_a_modified_vendor_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            kit = Path(temporary)
            bundle, _, _ = self.controller_fixture(kit)
            expected = {name: compact.files(bundle / 'converters' / name) for name in compact.ENGINES}
            (bundle / 'converters/calibre/core.dll').write_bytes(b'unexpected modification')
            with self.assertRaisesRegex(RuntimeError, 'changed or removed supplied'):
                compact.clear_generated(bundle, expected, kit / 'outside-bundle')

    def test_rewritten_vendor_bytecode_is_restored_from_the_verified_full_cache(self):
        with tempfile.TemporaryDirectory() as temporary:
            kit = Path(temporary)
            bundle, _, _ = self.controller_fixture(kit)
            vendor = self.put(bundle / 'converters/blender', '4.2/python/sourceless.pyc', b'original vendor bytecode')
            canonical = kit / 'full-cache'
            self.put(canonical, 'blender/4.2/python/sourceless.pyc', b'original vendor bytecode')
            expected = {name: compact.files(bundle / 'converters' / name) for name in compact.ENGINES}
            vendor.write_bytes(b'rebuilt during acceptance')
            actions = compact.clear_generated(bundle, expected, kit / 'outside-bundle', canonical)
            self.assertEqual(vendor.read_bytes(), b'original vendor bytecode')
            self.assertEqual(actions[0]['action'], 'restored vendor bytecode')


if __name__ == '__main__':
    unittest.main()
