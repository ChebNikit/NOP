"""Repair a damaged workspace cache from the complete kit without a network request."""
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import prepare_components as c

class PayloadRestoreTests(unittest.TestCase):
    def test_bad_cache_is_repaired_from_the_supplied_archive_without_network(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);work=root/'workspace';source=root/'source я (1)'
            dest=work/'.build-tools/converter-downloads/tool.msi';original=source/dest.relative_to(work)
            original.parent.mkdir(parents=True);original.write_bytes(b'complete pinned package')
            dest.parent.mkdir(parents=True);dest.write_bytes(b'truncated')
            with mock.patch.object(c,'ROOT',work),mock.patch.dict(c.os.environ,{'NOP_OUTPUT_ROOT':str(source)}),mock.patch.object(c.urllib.request,'urlopen',side_effect=AssertionError('network')):
                c.download('https://vendor.example/tool.msi',dest,c.sha256(original),minimum=1)
            self.assertEqual(dest.read_bytes(),original.read_bytes())
            self.assertFalse(dest.with_name(dest.name+'.part').exists())

if __name__=='__main__':unittest.main()
