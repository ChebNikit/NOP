"""Regression checks for stderr banners, real exit codes and interrupted r1 caches."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location("nop_runtime", ROOT / "prepare_runtime.py")
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


class NativeRuntimeRegressionTests(unittest.TestCase):
    def test_stderr_banner_with_exit_zero_is_success(self):
        output = runtime.command_output([sys.executable, "-c", "import sys;sys.stderr.write('ffmpeg version 9.0.2\\n')"])
        self.assertIn("ffmpeg version 9.0.2", output)

    def test_real_nonzero_exit_is_not_hidden_by_version_text(self):
        with self.assertRaisesRegex(RuntimeError, "exited with 7"):
            runtime.command_output([sys.executable, "-c", "print('ffmpeg version 9.0.2');raise SystemExit(7)"])

    def test_large_stdout_and_stderr_do_not_deadlock(self):
        output = runtime.command_output([sys.executable, "-c", "import sys;sys.stdout.write('o'*1048576);sys.stderr.write('e'*1048576)"], timeout=10)
        self.assertEqual(len(output), 2 * 1048576)

    def test_native_command_timeout_is_reported(self):
        with self.assertRaisesRegex(RuntimeError, "Timeout"):
            runtime.command_output([sys.executable, "-c", "import time;time.sleep(15)"], timeout=0.2)

    def test_spaces_quotes_and_unicode_arguments_are_preserved(self):
        import json
        arguments = ['a value with spaces', 'a "quoted" value', 'папка Никиты', 'C:\\work with spaces\\']
        result = runtime.command_output([sys.executable, "-c", "import json,sys;print(json.dumps(sys.argv[1:]))", *arguments])
        self.assertEqual(json.loads(result), arguments)

    def test_interrupted_r1_cache_repairs_notices_without_downloading(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            (directory / "ffmpeg.exe").write_bytes(b"already-validated-ffmpeg")
            (directory / "ffprobe.exe").write_bytes(b"already-validated-ffprobe")
            import json
            (directory / "runtime-manifest.json").write_text(json.dumps({"ffmpeg": {"archive_sha256": runtime.NATIVE_LOCK["ffmpeg"]["sha256"], "files": {
                "ffmpeg.exe": runtime.sha256(directory / "ffmpeg.exe"),
                "ffprobe.exe": runtime.sha256(directory / "ffprobe.exe")}}}), encoding="utf-8")
            def cached(path, *_):
                return path.stem + " version 9.0.2"
            with mock.patch.object(runtime, "RUNTIME", directory), \
                 mock.patch.object(runtime, "cached_version", side_effect=cached), \
                 mock.patch.object(runtime, "command_output", return_value="FFmpeg original license\n"), \
                 mock.patch.object(runtime, "download") as download:
                result = runtime.prepare_ffmpeg()
            download.assert_not_called()
            self.assertIn("9.0.2", result["version"])
            self.assertIn("original license", (directory / "FFMPEG-LICENSE.txt").read_text(encoding="utf-8-sig"))
            self.assertTrue((directory / "FFMPEG-SOURCE.txt").is_file())

    def test_cached_deno_repairs_source_notice(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            (directory / "deno.exe").write_bytes(b"already-validated-deno")
            import json
            (directory / "runtime-manifest.json").write_text(json.dumps({"deno": {"archive_sha256": runtime.required_asset_digest(runtime.NATIVE_LOCK["deno"]["assets"][0]), "files": {
                "deno.exe": runtime.sha256(directory / "deno.exe")}}}), encoding="utf-8")
            with mock.patch.object(runtime, "RUNTIME", directory), \
                 mock.patch.object(runtime, "cached_version", return_value="deno 2.9.8"), \
                 mock.patch.object(runtime, "request_json") as fetch:
                runtime.prepare_deno()
            fetch.assert_not_called()
            self.assertTrue((directory / "DENO-SOURCE.txt").is_file())

    def test_truncated_cached_executable_is_marked_for_repair(self):
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / "ffmpeg.exe"
            path.write_bytes(b"MZ")
            with mock.patch.object(runtime, "note"):
                self.assertIsNone(runtime.cached_version(path, "-version", "ffmpeg version "))

    def test_libmpv_selects_only_x64_lgpl(self):
        assets = [
            {"name": "libmpv-v0.41.0-x86_64-w64-mingw32-gpl.zip"},
            {"name": "libmpv-v0.41.0-aarch64-w64-mingw32-lgpl.zip"},
            {"name": "libmpv-v0.41.0-x86_64-w64-mingw32-lgpl.zip"},
        ]
        self.assertEqual(runtime.select_asset(assets, runtime.MPV_PATTERN), assets[2])
        unversioned = {"name": "libmpv-x86_64-w64-mingw32-lgpl.zip"}
        self.assertEqual(runtime.select_asset([unversioned], runtime.MPV_PATTERN), unversioned)

    def test_cached_binary_must_match_previous_sha256_manifest(self):
        import json
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            binary = directory / "deno.exe"
            binary.write_bytes(b"validated executable")
            (directory / "runtime-manifest.json").write_text(json.dumps({"deno": {"archive_sha256": runtime.required_asset_digest(runtime.NATIVE_LOCK["deno"]["assets"][0]), "files": {
                "deno.exe": "0" * 64}}}), encoding="utf-8")
            with mock.patch.object(runtime, "RUNTIME", directory), mock.patch.object(runtime, "note"):
                self.assertFalse(runtime.cached_files_match("deno", {"deno.exe": binary}))
                (directory / "runtime-manifest.json").write_text(json.dumps({"deno": {"archive_sha256": runtime.required_asset_digest(runtime.NATIVE_LOCK["deno"]["assets"][0]), "files": {
                    "deno.exe": runtime.sha256(binary)}}}), encoding="utf-8")
                self.assertTrue(runtime.cached_files_match("deno", {"deno.exe": binary}))

    def test_cached_binary_without_hash_manifest_is_not_trusted(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            binary = directory / "deno.exe"
            binary.write_bytes(b"looks executable enough for a mocked version command")
            with mock.patch.object(runtime, "RUNTIME", directory), mock.patch.object(runtime, "note"):
                self.assertFalse(runtime.cached_files_match("deno", {"deno.exe": binary}))

    def test_html_is_not_a_checksum(self):
        with self.assertRaises(RuntimeError):
            runtime.digest_from_text("<html>" + "a" * 64 + "</html>")

    def test_release_asset_without_upstream_digest_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "no SHA-256 digest"):
            runtime.required_asset_digest({"name": "release.zip"})

    def test_release_asset_sha256_digest_is_required_and_normalized(self):
        digest = "A" * 64
        self.assertEqual(runtime.required_asset_digest({"name": "release.zip", "digest": "sha256:" + digest}), "a" * 64)

    def test_zip_parent_path_is_rejected_before_extraction(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            archive = root / "unsafe.zip"
            with ZipFile(archive, "w") as output:
                output.writestr("../outside.txt", "not allowed")
            with self.assertRaises(RuntimeError):
                runtime.extract_zip(archive, root / "stage")
            self.assertFalse((root / "outside.txt").exists())


if __name__ == "__main__":
    unittest.main()
