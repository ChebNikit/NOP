"""The installed bundle must retain and decode all three author images."""
import ast
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from assemble_bundle import copy_directory
from nop_bundle_check import check_author_assets


class AuthorAssetsTests(unittest.TestCase):
    def test_images_survive_relocation_and_are_found_from_another_working_directory(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name) / "Установленный NOP with spaces"
            root.mkdir()
            copy_directory(ROOT / "assets", root / "assets")
            original_cwd = Path.cwd()
            try:
                os.chdir(name)
                detail = check_author_assets(root)
                # Execute the player's actual asset lookup without starting the player.
                tree = ast.parse((ROOT / "NOP_1.0.py").read_text(encoding="utf-8-sig"))
                lookup = next(node for node in tree.body
                              if isinstance(node, ast.FunctionDef) and node.name == "find_asset")
                namespace = {"Path": Path, "ASSET_DIRS": [root / "assets"]}
                exec(compile(ast.Module(body=[lookup], type_ignores=[]), "asset-lookup", "exec"), namespace)
                for filename in ("avatar.jpg", "donate_crypto_qr.jpg", "donate_ozon_qr.jpg"):
                    self.assertIn(filename, detail)
                    self.assertEqual(namespace["find_asset"](Path(filename).stem), root / "assets" / filename)
                    self.assertEqual((root / "assets" / filename).read_bytes(), (ROOT / "assets" / filename).read_bytes())
            finally:
                os.chdir(original_cwd)

    def test_missing_avatar_blocks_validation(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            copy_directory(ROOT / "assets", root / "assets")
            (root / "assets" / "avatar.jpg").unlink()
            with self.assertRaisesRegex(FileNotFoundError, "avatar.jpg"):
                check_author_assets(root)

    def test_missing_either_donation_qr_blocks_validation(self):
        for filename in ("donate_crypto_qr.jpg", "donate_ozon_qr.jpg"):
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as name:
                root = Path(name)
                copy_directory(ROOT / "assets", root / "assets")
                (root / "assets" / filename).unlink()
                with self.assertRaisesRegex(FileNotFoundError, filename):
                    check_author_assets(root)

    def test_corrupt_jpeg_blocks_validation(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            copy_directory(ROOT / "assets", root / "assets")
            (root / "assets" / "donate_ozon_qr.jpg").write_bytes(b"not an image")
            with self.assertRaisesRegex(RuntimeError, "donate_ozon_qr.jpg"):
                check_author_assets(root)


if __name__ == "__main__":
    unittest.main()
