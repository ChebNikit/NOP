"""Security regression checks for the hash-pinned pip bootstrap."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("nop_secure_pip", ROOT / "bootstrap_secure_pip.py")
secure_pip = importlib.util.module_from_spec(spec)
spec.loader.exec_module(secure_pip)


class SecurePipBootstrapTests(unittest.TestCase):
    def test_pinned_hash_has_expected_digest_length(self):
        self.assertEqual(len(secure_pip.WHEEL_SHA256), 64)

    def test_wrong_or_truncated_wheel_is_rejected(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as temp:
            wheel = Path(temp) / secure_pip.WHEEL_NAME
            wheel.write_bytes(b"not a wheel")
            self.assertFalse(secure_pip.valid_wheel(wheel))

    def test_bundled_pip_is_verified_and_requires_no_network(self):
        from unittest import mock
        from tempfile import TemporaryDirectory
        self.assertTrue(secure_pip.valid_wheel(ROOT / "bootstrap" / secure_pip.WHEEL_NAME))
        with TemporaryDirectory() as temp, mock.patch.object(secure_pip.urllib.request, "urlopen", side_effect=AssertionError("Network not allowed")):
            destination = Path(temp) / secure_pip.WHEEL_NAME
            secure_pip.download_pinned_wheel(destination)
            self.assertTrue(secure_pip.valid_wheel(destination))


if __name__ == "__main__":
    unittest.main()
