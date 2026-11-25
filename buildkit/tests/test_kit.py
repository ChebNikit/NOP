"""Kit self-tests. Run:  python -m unittest discover -s tests -v   (any OS; Windows-only steps are not exercised)."""
import ast
import hashlib
import os
import http.server
import inspect
import json
import re
import sys
import tempfile
import threading
import unittest
from unittest import mock
import xml.dom.minidom
import zipfile
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT / "build"))
import build_kit  # noqa: E402
import kitlib  # noqa: E402


class Handler(http.server.BaseHTTPRequestHandler):
    hits = 0
    payload = b"nop-test-payload" * 1000

    def log_message(self, *args):
        pass

    def do_GET(self):
        Handler.hits += 1
        if self.path == "/flaky" and Handler.hits < 3:
            self.send_response(503)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(self.payload)))
        self.end_headers()
        self.wfile.write(self.payload)


class DownloadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def url(self, path="/file"):
        return f"http://127.0.0.1:{self.port}{path}"

    def test_download_verifies_and_caches(self):
        digest = hashlib.sha256(Handler.payload).hexdigest()
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "sub dir" / "ф.bin"             # space and Cyrillic in the path
            kitlib.download(self.url(), target, digest)
            self.assertEqual(target.read_bytes(), Handler.payload)
            before = Handler.hits
            kitlib.download(self.url(), target, digest)             # cache hit: no request
            self.assertEqual(Handler.hits, before)

    def test_hash_mismatch_is_fatal_and_leaves_no_file(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "x.bin"
            with self.assertRaises(kitlib.KitError):
                kitlib.download(self.url(), target, "0" * 64, retries=3)
            self.assertFalse(target.exists())
            self.assertFalse(Path(str(target) + ".part").exists())

    def test_corrupt_cache_is_replaced(self):
        digest = hashlib.sha256(Handler.payload).hexdigest()
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "x.bin"
            target.write_bytes(b"corrupt")
            kitlib.download(self.url(), target, digest)
            self.assertEqual(target.read_bytes(), Handler.payload)

    def test_retries_after_server_error(self):
        Handler.hits = 0
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "flaky.bin"
            kitlib.download(self.url("/flaky"), target, retries=4)
            self.assertTrue(target.is_file())


class ArchiveTests(unittest.TestCase):
    def test_zip_slip_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            archive = Path(folder) / "evil.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("../escape.txt", "x")
            with self.assertRaises(kitlib.KitError):
                kitlib.safe_extract_zip(archive, Path(folder) / "out")
            self.assertFalse((Path(folder) / "escape.txt").exists())

    def test_normal_zip_extracts(self):
        with tempfile.TemporaryDirectory() as folder:
            archive = Path(folder) / "ok.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("bin/ffmpeg.exe", "x")
            kitlib.safe_extract_zip(archive, Path(folder) / "out")
            self.assertTrue((Path(folder) / "out" / "bin" / "ffmpeg.exe").is_file())

    def test_python_series_picks_highest_stable(self):
        index = json.dumps({"versions": ["3.12.9", "3.13.0-rc1", "3.13.9", "3.13.10", "3.13.17", "3.14.0"]})
        self.assertEqual(kitlib.newest_series_version(index, "3.13."), "3.13.17")
        with self.assertRaises(kitlib.KitError):
            kitlib.newest_series_version(json.dumps({"versions": ["3.12.1"]}), "3.13.")


class LockTests(unittest.TestCase):
    def test_components_pinned(self):
        lock = json.loads((KIT / "config" / "components.lock.json").read_text(encoding="utf-8"))
        self.assertEqual(set(lock["components"]), {"7zr", "libmpv", "ffmpeg", "deno"})
        for name, item in lock["components"].items():
            self.assertRegex(item["sha256"], r"^[0-9a-f]{64}$", name)
            self.assertTrue(item["url"].startswith("https://"), name)
            self.assertTrue(item["url"].endswith(item["file"]), name)
            self.assertNotIn("latest", item["url"], f"{name}: a moving 'latest' URL cannot be pinned")

    def test_equalizer_apo_pinned_and_embedded(self):
        lock = json.loads((KIT / "config" / "components.lock.json").read_text(encoding="utf-8"))
        apo = lock["installers"]["equalizer_apo"]
        self.assertRegex(apo["sha256"], r"^[0-9a-f]{64}$")
        self.assertTrue(apo["url"].startswith("https://"))
        self.assertTrue(apo["url"].endswith(apo["file"]))
        self.assertNotIn("latest", apo["url"])
        text = (KIT / "installer" / "NOP_Setup.iss.template").read_text(encoding="utf-8-sig")
        for needle in ('Source: "{#ApoInstaller}"; Flags: dontcopy', "ExtractTemporaryFile('{#ApoFile}')",
                       "function EqualizerAPOInstalled", "if WizardSilent then", "CustomMessage('ApoFail')"):
            self.assertIn(needle, text)
        self.assertNotIn("не входит в этот установщик", text)
        self.assertNotIn("is not included in this installer.", text)
        notices = build_kit.third_party_notices(lock)
        self.assertIn("Equalizer APO " + apo["version"], notices)

    def test_apo_installer_failure_modes(self):
        from types import SimpleNamespace
        payload = b"fake apo installer"
        spec = {"installers": {"equalizer_apo": {"version": "9.9", "url": "https://example.invalid/apo.exe",
                                                 "sha256": hashlib.sha256(payload).hexdigest(), "file": "apo.exe",
                                                 "source": "https://example.invalid/page"}}}
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(build_kit, "CACHE", Path(tmp)), \
                mock.patch.object(build_kit, "lock_components", return_value=spec):
            with self.assertRaises(kitlib.KitError) as ctx:  # offline and not cached: must stop, not silently skip APO
                build_kit.apo_installer(SimpleNamespace(offline=True))
            self.assertIn("Equalizer APO", str(ctx.exception))
            (Path(tmp) / "apo.exe").write_bytes(payload)  # cached with the right hash: reused offline
            self.assertEqual(build_kit.apo_installer(SimpleNamespace(offline=True)), Path(tmp) / "apo.exe")

    def test_apo_download_tries_other_ways_after_403(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(build_kit, "CACHE", Path(tmp)):
            calls = []

            def fake(url, destination, sha256=None, size=None, retries=4, label="", user_agent=None):
                calls.append((url, user_agent))
                if len(calls) < 3:
                    raise kitlib.KitError("HTTP Error 403: Forbidden")
                return Path(destination)

            with mock.patch.object(build_kit.kitlib, "download", side_effect=fake):
                result = build_kit.apo_installer(SimpleNamespace(offline=False))
            self.assertEqual(len(calls), 3)
            self.assertEqual(result.name, "EqualizerAPO-x64-1.4.2.exe")
            with mock.patch.object(build_kit.kitlib, "download", side_effect=kitlib.KitError("403")):
                with self.assertRaises(kitlib.KitError) as ctx:
                    build_kit.apo_installer(SimpleNamespace(offline=False))
            self.assertIn("in a browser", str(ctx.exception))
            self.assertIn("7403be74", str(ctx.exception))

    def test_report_components_includes_apo_and_skips_comments(self):
        lock = json.loads((KIT / "config" / "components.lock.json").read_text(encoding="utf-8"))
        info = build_kit.report_components(lock)  # the real lock, including the string 'comment' keys
        self.assertEqual(set(info), {"7zr", "libmpv", "ffmpeg", "deno", "equalizer_apo"})
        self.assertEqual(info["equalizer_apo"]["version"], "1.4.2")
        json.dumps(info)

    def test_requirements_fully_hashed(self):
        text = (KIT / "config" / "requirements.lock").read_text(encoding="utf-8")
        entries = re.findall(r"^([A-Za-z0-9_.\-]+)==([^\s\\]+) \\\n    --hash=sha256:([0-9a-f]{64})$", text, re.M)
        names = {name.lower() for name, _v, _h in entries}
        self.assertGreaterEqual(len(entries), 20)
        self.assertTrue({"pyqt6", "pyqt6-qt6", "numpy", "pillow", "pymupdf", "mutagen", "yt-dlp", "yt-dlp-ejs", "pyinstaller",
                         "pefile", "pywin32-ctypes", "brotli", "certifi", "websockets", "requests"} <= names, names)
        pins = [line for line in text.splitlines() if "==" in line]
        self.assertEqual(len(pins), len(entries), "every requirement must carry a hash")

    def test_application_third_party_imports_are_locked(self):
        tree = ast.parse((KIT / "source" / "NOP_1_3.py").read_text(encoding="utf-8"))
        used = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                used |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                used.add(node.module.split(".")[0])
        locked = (KIT / "config" / "requirements.lock").read_text(encoding="utf-8").lower().replace("-", "_")
        third_party = {m for m in used if m not in sys.stdlib_module_names and m not in {"nop_validation", "youtube_stage_test"}}
        mapping = {"PIL": "pillow", "fitz": "pymupdf", "PyQt6": "pyqt6", "yt_dlp": "yt_dlp", "numpy": "numpy", "mutagen": "mutagen"}
        for module in third_party:
            self.assertIn(mapping.get(module, module).lower().replace("-", "_"), locked, f"{module} is imported but not locked")


class InnoProvisioningTests(unittest.TestCase):
    def setUp(self):
        self.spec = json.loads((KIT / "config" / "components.lock.json").read_text(encoding="utf-8"))["signed_downloads"]["innosetup"]

    def test_urls_use_valid_github_release_assets(self):
        tags = "releases/tag/is-6_7_3 releases/tag/is-6_7_4 releases/tag/is-7_0_0_1 releases/tag/is-7_1_1"
        urls = build_kit.inno_urls(self.spec, tags)
        expected = "https://github.com/jrsoftware/issrc/releases/download/is-6_7_4/innosetup-6.7.4.exe"
        self.assertEqual(urls[0], expected)
        self.assertTrue(all("files.jrsoftware.org" not in url for url in urls))
        self.assertTrue(all("download.php" not in url for url in urls))
        self.assertTrue(all("is-7_1_1" not in url for url in urls))
        self.assertEqual(len(urls), len(set(urls)))

    def test_urls_work_without_github_tags(self):
        urls = build_kit.inno_urls(self.spec, "")
        self.assertEqual(urls, ["https://github.com/jrsoftware/issrc/releases/download/is-6_7_4/innosetup-6.7.4.exe"])

    def test_version_compare(self):
        self.assertGreater(build_kit.version_tuple("6.7.4"), build_kit.version_tuple("6.6.0"))
        self.assertEqual(self.spec["min_version"], "6.5.0")

    def test_urls_skip_versions_older_than_minimum(self):
        spec = dict(self.spec)
        spec["preferred_versions"] = ["6.4.0", "6.7.4"]
        tags = "releases/tag/is-6_4_0 releases/tag/is-6_6_2 releases/tag/is-7_1_1"
        urls = build_kit.inno_urls(spec, tags)
        self.assertNotIn("https://github.com/jrsoftware/issrc/releases/download/is-6_4_0/innosetup-6.4.0.exe", urls)
        self.assertIn("https://github.com/jrsoftware/issrc/releases/download/is-6_6_2/innosetup-6.6.2.exe", urls)
        self.assertNotIn("is-7_1_1", "\n".join(urls))

    def test_resume_option_exists(self):
        self.assertEqual(build_kit.main(["--list"]), 0)


class GeneratedFilesTests(unittest.TestCase):
    def test_manifest_is_well_formed(self):
        document = xml.dom.minidom.parseString(build_kit.manifest_xml())
        self.assertEqual(document.getElementsByTagName("requestedExecutionLevel")[0].getAttribute("level"), "asInvoker")

    def test_version_info_and_spec_compile(self):
        text = build_kit.version_info_text("1.3")
        self.assertIn("filevers=(1, 3, 0, 0)", text)
        spec = build_kit.spec_text(Path("C:/kit/source/NOP_1_3.py"), Path("C:/a/nop.ico"), Path("C:/a/v.txt"), Path("C:/a/m.xml"), None)
        compile(spec, "NOP.spec", "exec")                           # must be valid Python
        self.assertIn('name="NOP"', spec)
        self.assertIn("console=False", spec)

    def test_associations(self):
        exts = build_kit.media_extensions(KIT / "source" / "NOP_1_3.py")
        self.assertIn(".mp3", exts)
        self.assertIn(".mkv", exts)
        include = build_kit.associations_inc(exts)
        self.assertEqual(include.count("Tasks: openwith"), 2 * len(exts))
        self.assertIn('Software\\Classes\\.flac\\OpenWithList\\NOP.exe', include)

    def test_installer_template(self):
        text = (KIT / "installer" / "NOP_Setup.iss.template").read_text(encoding="utf-8")
        for needle in ("DisableWelcomePage=no", "ArchitecturesAllowed=x64compatible", "MinVersion=10.0.17763", "--nop-warm-capabilities",
                       "--nop-selftest", "russian.TaskOpenWith", "english.TaskOpenWith", "#include \"associations.iss.inc\"",
                       "WizardStyle=modern dark includetitlebar hidebevels", "WizardBackColor=#0D0F14", "AppId={{"):
            self.assertIn(needle, text)
        self.assertIn("#if Ver >= 0x06060000", text)
        self.assertIn("#if Ver >= 0x06070000", text)
        self.assertIn("#if Ver < 0x06060000", text)
        self.assertNotIn("WizardDarkStyle=dark", text)
        # every {cm:...} message used must exist in both languages
        used = set(re.findall(r"\{cm:(\w+)\}", text)) | set(re.findall(r"CustomMessage\('(\w+)'\)", text))
        builtin = {"CreateDesktopIcon", "AdditionalIcons", "UninstallProgram"}
        for name in used - builtin:
            self.assertIn(f"russian.{name}=", text, name)
            self.assertIn(f"english.{name}=", text, name)

    def test_generated_inno_script_has_exactly_one_utf8_bom(self):
        template = KIT / "installer" / "NOP_Setup.iss.template"
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "NOP_Setup.iss"
            build_kit.write_inno_script(template, output)
            raw = output.read_bytes()
            bom = b"\xef\xbb\xbf"
            self.assertTrue(raw.startswith(bom))
            self.assertFalse(raw.startswith(bom + bom))
            self.assertTrue(raw[len(bom):].startswith(b"; ==="))

    def test_installer_package_manifest_uses_locked_versions(self):
        manifest = build_kit.installer_package_manifest()
        components = json.loads((KIT / "config" / "components.lock.json").read_text(encoding="utf-8"))["components"]
        for component in ("libmpv", "ffmpeg", "deno"):
            self.assertIn(components[component]["version"], manifest)
        requirements = build_kit._locked_requirement_versions()
        for name, _label in build_kit.RUNTIME_PACKAGE_LABELS:
            self.assertIn(requirements[name], manifest, name)
            self.assertIn(_label.lower(), manifest.lower(), name)
        engines = json.loads((KIT / "config" / "engines.lock.json").read_text(encoding="utf-8"))["engines"]
        for item in engines.values():
            self.assertIn(item["title"], manifest)
        for build_only in ("pyinstaller", "pyinstaller-hooks-contrib", "setuptools", "altgraph", "packaging", "pefile", "pywin32-ctypes"):
            self.assertNotIn(build_only, manifest.lower())

    def test_welcome_and_package_pages_are_in_setup_flow(self):
        text = (KIT / "installer" / "NOP_Setup.iss.template").read_text(encoding="utf-8")
        self.assertIn("DisableWelcomePage=no", text)
        self.assertIn("WizardForm.WelcomeLabel1.Caption := CustomMessage('WelcomeTitle')", text)
        self.assertNotIn("WelcomeVersionLabel", text)  # no floating window-level version label
        art = (KIT / "build" / "make_art.py").read_text(encoding="utf-8")
        self.assertIn('f"{version}  /  Windows x64"', art)  # version is baked into the left welcome artwork
        self.assertIn("def build_all(source: Path, output: Path, version: str)", art)
        self.assertIn("return art.build_all(SOURCE, ART, APP_VERSION)", (KIT / "build" / "build_kit.py").read_text(encoding="utf-8"))
        self.assertIn("CreateCustomPage(wpSelectTasks", text)
        self.assertIn("PackageInfoPage := CreateCustomPage(wpSelectTasks", text)  # contents page never overlays the type page
        self.assertEqual(text.count("CreateCustomPage(wpSelectComponents"), 1)  # only the converters page follows the type page
        self.assertIn("PackageInfoMemo.Parent := PackageInfoPage.Surface", text)
        self.assertIn("if CurPageID = PackageInfoPage.ID then", text)
        self.assertIn('#include "package_manifest.iss.inc"', text)
        self.assertIn("WizardIsComponentSelected('engines')", text)
        self.assertIn("russian.PackagesApoNote=", text)
        self.assertIn("english.PackagesApoNote=", text)

    def test_selection_focus_cues_are_hidden_without_changing_selection_state(self):
        text = (KIT / "installer" / "NOP_Setup.iss.template").read_text(encoding="utf-8-sig")
        self.assertIn("WM_CHANGEUISTATE = $0127", text)
        self.assertIn("UIS_SET_HIDEFOCUS = $00010001", text)
        self.assertIn("HideFocusCues(WizardForm.ComponentsList.Handle)", text)
        self.assertIn("HideFocusCues(WizardForm.TypesCombo.Handle)", text)
        self.assertIn("if CurPageID = wpPreparing then", text)
        self.assertIn("HideFocusCues(WizardForm.PreparingMemo.Parent.Handle)", text)
        self.assertNotIn("HideFocusCues(WizardForm.Handle)", text)
        self.assertIn("WizardForm.ComponentsList.OnClick := @DropListSelection", text)
        self.assertIn("WizardForm.TypesCombo.OnClick := @DropControlFocus", text)
        self.assertIn("WizardForm.PreparingYesRadio.OnClick := @DropControlFocus", text)
        self.assertIn("WizardForm.PreparingNoRadio.OnClick := @DropControlFocus", text)
        self.assertNotIn("ComponentsList.Checked", text)
        self.assertNotIn("TypesCombo.ItemIndex :=", text)

    def test_application_has_installer_hooks(self):
        source = (KIT / "source" / "NOP_1_3.py").read_text(encoding="utf-8")
        self.assertIn('APP_VERSION = "1.3"', source)
        for flag in ("--nop-warm-capabilities", "--nop-selftest"):
            self.assertIn(flag, source)

    def test_art_generation(self):
        import make_art
        art_source = (KIT / "build" / "make_art.py").read_text(encoding="utf-8")
        self.assertIn('f"{version}  /  Windows x64"', art_source)
        with tempfile.TemporaryDirectory() as folder:
            result = make_art.build_all(KIT / "source" / "NOP_1_3.py", Path(folder), "1.3")
            from PIL import Image
            with Image.open(Path(folder) / "wizard_preview.png") as preview:
                self.assertEqual(preview.size, (656, 1256))
            for name in result["wizard"] + result["small"] + [result["icon"]]:
                self.assertTrue((Path(folder) / name).is_file(), name)

    def test_step_10_refreshes_artwork_even_when_resuming(self):
        compile_source = inspect.getsource(build_kit.compile_installer)
        self.assertIn("refresh_installer_art()", compile_source)
        self.assertIn("--from-step 10", inspect.getdoc(build_kit.refresh_installer_art))


if __name__ == "__main__":
    unittest.main()


class InnoDetectionTests(unittest.TestCase):
    def test_finds_inno_in_any_inno_setup_folder(self):
        import os
        with tempfile.TemporaryDirectory() as folder:
            local = Path(folder) / "Local"
            (local / "Programs" / "Inno Setup 7").mkdir(parents=True)
            (local / "Programs" / "Inno Setup 7" / "ISCC.exe").write_bytes(b"x")
            (Path(folder) / "PF" / "Inno Setup 6").mkdir(parents=True)
            (Path(folder) / "PF" / "Inno Setup 6" / "ISCC.exe").write_bytes(b"x")
            old = {k: os.environ.get(k) for k in ("LOCALAPPDATA", "ProgramFiles", "ProgramFiles(x86)", "ProgramW6432", "PATH")}
            try:
                os.environ.update({"LOCALAPPDATA": str(local), "ProgramFiles": str(Path(folder) / "PF"),
                                   "ProgramFiles(x86)": str(Path(folder) / "none"), "ProgramW6432": str(Path(folder) / "none")})
                found = [str(p) for p in build_kit.installed_iscc_candidates()]
            finally:
                for key, value in old.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value
            self.assertEqual(len(found), 2, found)
            self.assertTrue(any("Inno Setup 7" in p for p in found))
            self.assertTrue(any("Inno Setup 6" in p for p in found))


class InnoVersionTests(unittest.TestCase):
    def test_version_comes_from_dll_not_from_iscc(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder) / "Inno Setup 6"
            home.mkdir()
            (home / "ISCC.exe").write_bytes(b"x")
            (home / "ISCmplr.dll").write_bytes(b"x")
            reader = lambda path: "0.0.0.0" if path.name == "ISCC.exe" else "6.7.4.0"
            self.assertEqual(build_kit.inno_version(home / "ISCC.exe", reader), (6, 7, 4))

    def test_falls_back_to_folder_name(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder) / "Inno Setup 6"
            home.mkdir()
            (home / "ISCC.exe").write_bytes(b"x")
            self.assertEqual(build_kit.inno_version(home / "ISCC.exe", lambda path: "0.0.0.0"), (6,))
            self.assertEqual(build_kit.inno_version(home / "ISCC.exe", lambda path: ""), (6,))

    def test_zero_version_without_hint_is_unknown(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "ISCC.exe").write_bytes(b"x")
            self.assertEqual(build_kit.inno_version(Path(folder) / "ISCC.exe", lambda path: "0.0.0.0"), (0,))

    def test_find_iscc_accepts_explicit_compiler_without_brittle_minor_probe(self):
        with tempfile.TemporaryDirectory() as folder:
            compiler = Path(folder) / "ISCC.exe"
            compiler.write_bytes(b"x")
            with mock.patch.dict(os.environ, {"NOP_ISCC": str(compiler)}), \
                 mock.patch.object(build_kit, "INNO_DIR", Path(folder) / "private-inno"):
                self.assertEqual(build_kit._find_iscc(), compiler)

    def test_installed_compiler_accepts_major_only_install_path(self):
        with tempfile.TemporaryDirectory() as folder:
            compiler = Path(folder) / "ISCC.exe"
            compiler.write_bytes(b"x")
            with mock.patch.object(build_kit, "installed_iscc_candidates", return_value=[compiler]), \
                 mock.patch.object(build_kit, "inno_version", return_value=(6,)):
                self.assertEqual(build_kit._accept_existing_iscc("6.5.0"), compiler)

    def test_find_iscc_rediscovers_installed_compiler_when_resuming_step_10(self):
        """Step 9's NOP_ISCC environment change is process-local; step 10 must rediscover Inno."""
        with tempfile.TemporaryDirectory() as folder:
            compiler = Path(folder) / "Inno Setup 6" / "ISCC.exe"
            compiler.parent.mkdir()
            compiler.write_bytes(b"x")
            with mock.patch.dict(os.environ, {}, clear=True), \
                 mock.patch.object(build_kit, "INNO_DIR", Path(folder) / "private-inno"), \
                 mock.patch.object(build_kit, "installed_iscc_candidates", return_value=[compiler]), \
                 mock.patch.object(build_kit, "inno_version", return_value=(6, 7, 4)):
                self.assertEqual(build_kit._find_iscc(), compiler)

    def test_installed_compiler_rejects_known_version_below_minimum(self):
        with tempfile.TemporaryDirectory() as folder:
            compiler = Path(folder) / "ISCC.exe"
            compiler.write_bytes(b"x")
            with mock.patch.object(build_kit, "installed_iscc_candidates", return_value=[compiler]), \
                 mock.patch.object(build_kit, "inno_version", return_value=(6, 4, 0)):
                self.assertIsNone(build_kit._accept_existing_iscc("6.5.0"))


class ZstdGuardTests(unittest.TestCase):
    def test_broken_backports_zstd_is_hidden(self):
        """Regression: 'module backports.zstd has no attribute ZstdError' aborted start-up of the frozen app."""
        import subprocess
        tree = ast.parse((KIT / "source" / "NOP_1_3.py").read_text(encoding="utf-8"))
        guard = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_guard_optional_zstd")
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "backports" / "zstd").mkdir(parents=True)
            code = ("import sys\n" + ast.unparse(guard) + "\n_guard_optional_zstd()\n"
                    "try:\n    from backports import zstd\n    print('IMPORTED')\nexcept ImportError:\n    print('HIDDEN')\n")
            result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                                    env={"PYTHONPATH": folder, "PATH": os.environ.get("PATH", "")})
            self.assertEqual(result.stdout.strip(), "HIDDEN", result.stderr)


class EngineTests(unittest.TestCase):
    def test_lock_describes_four_engines(self):
        spec = json.loads((KIT / "config" / "engines.lock.json").read_text(encoding="utf-8"))["engines"]
        self.assertEqual(set(spec), {"libreoffice", "inkscape", "calibre", "blender"})
        expected = {"libreoffice": "program/soffice.exe", "inkscape": "bin/inkscape.exe", "calibre": "ebook-convert.exe", "blender": "blender.exe"}
        for name, item in spec.items():
            self.assertEqual(item["tool"], expected[name])
            self.assertEqual(item["dest"], name)
            self.assertTrue(item["winget"])

    def test_layout_matches_what_nop_looks_for(self):
        """NOP searches converters/<libreoffice/program | inkscape/bin | calibre | blender>/ - keep the kit in sync."""
        source = (KIT / "source" / "NOP_1_3.py").read_text(encoding="utf-8")
        for fragment in ('"libreoffice/program"', '"inkscape/bin"', '"calibre"', '"blender"'):
            self.assertIn(fragment, source)

    def test_engine_root_and_prune(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            (base / "PFiles" / "LibreOffice" / "program").mkdir(parents=True)
            (base / "PFiles" / "LibreOffice" / "program" / "soffice.exe").write_bytes(b"x")
            (base / "PFiles" / "LibreOffice" / "help").mkdir()
            root = build_kit.engine_root(base, "program/soffice.exe")
            self.assertEqual(root, base / "PFiles" / "LibreOffice")
            build_kit.prune_engine(root, ["help", "nothing"])
            self.assertFalse((root / "help").exists())
            self.assertTrue((root / "program" / "soffice.exe").is_file())
            (base / "Blender" / "4.5" / "datafiles" / "locale").mkdir(parents=True)
            (base / "Blender" / "blender.exe").write_bytes(b"x")
            blender = build_kit.engine_root(base, "blender.exe")
            build_kit.prune_engine(blender, ["*/datafiles/locale"])
            self.assertFalse((blender / "4.5" / "datafiles" / "locale").exists())
            self.assertIsNone(build_kit.engine_root(base, "bin/inkscape.exe"))

    def test_installer_offers_each_converter_separately(self):
        text = (KIT / "installer" / "NOP_Setup.iss.template").read_text(encoding="utf-8-sig")
        engines = json.loads((KIT / "config" / "engines.lock.json").read_text(encoding="utf-8"))["engines"]
        for item in engines.values():
            dest = item["dest"]
            self.assertIn(f'converters\\{dest}\\*"; DestDir: "{{app}}\\converters\\{dest}"', text, dest)
            self.assertIn(f"Check: EngineSelected('{dest}')", text, dest)
            self.assertIn(f"#define EngineMB_{dest} 0", text, dest)
            self.assertIn(f"return '{dest}'".replace("return ", "Result := "), text, dest)
        self.assertEqual(len(engines), 4)
        self.assertIn("EngineTotal = 4", text)
        # the whole converters folder is no longer copied as one block
        self.assertNotIn('converters\\*"; DestDir: "{app}\\converters"', text)
        # expandable section header + silent-install switch
        for needle in ("EngineHeader.OnClick := @EngineHeaderClick", "EngineList.Visible := EngineExpanded",
                       "{param:engines|all}", "function ShouldSkipPage", "RegisterPreviousData",
                       "russian.EnginesHeader=", "english.EnginesHeader="):
            self.assertIn(needle, text, needle)
        for name in ("EngLibreOffice", "EngInkscape", "EngCalibre", "EngBlender"):
            for lang in ("russian", "english"):
                self.assertIn(f"{lang}.{name}=", text)

    def test_every_step_decorator_sits_directly_on_its_function(self):
        lines = (KIT / "build" / "build_kit.py").read_text(encoding="utf-8").splitlines()
        for number, line in enumerate(lines):
            if line.startswith("@step"):
                self.assertTrue(lines[number + 1].startswith("def "), f"line {number + 1}: {lines[number + 1]}")
        self.assertEqual(len(build_kit.STEPS), 12) if hasattr(build_kit, "STEPS") else None

    def test_engine_size_defines(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name, size in (("libreoffice", 3 * 1024 * 1024), ("inkscape", 1), ("calibre", 5 * 1024 * 1024), ("blender", 2 * 1024 * 1024)):
                (root / name).mkdir()
                (root / name / "x.bin").write_bytes(b"0" * size)
            defines = build_kit.engine_size_defines(root)
            self.assertEqual(defines, ["/DEngineMB_libreoffice=3", "/DEngineMB_inkscape=1", "/DEngineMB_calibre=5", "/DEngineMB_blender=2"])
            kitlib.rmtree(root / "blender")
            with self.assertRaises(build_kit.KitError):
                build_kit.engine_size_defines(root)

    def test_update_cleans_library_folders_but_not_user_data(self):
        text = (KIT / "installer" / "NOP_Setup.iss.template").read_text(encoding="utf-8-sig")
        section = text.split("[InstallDelete]")[1].split("\n[")[0]
        for folder in ("_internal", "mpv", "licenses"):
            self.assertIn(f'Type: filesandordirs; Name: "{{app}}\\{folder}"', section)
        for protected in ("converters", "YamiFM", "appdata"):
            self.assertNotIn(f'Name: "{{app}}\\{protected}', section)
            self.assertNotIn(f"Name: \"{{userappdata}}", section)
        spec = build_kit.spec_text(Path("C:/k/s.py"), Path("C:/a/i.ico"), Path("C:/a/v.txt"), Path("C:/a/m.xml"), None)
        self.assertIn('contents_directory="_internal"', spec)

    def test_start_menu_folder_with_uninstaller(self):
        text = (KIT / "installer" / "NOP_Setup.iss.template").read_text(encoding="utf-8-sig")
        self.assertIn("DisableProgramGroupPage=no", text)
        self.assertIn("AllowNoIcons=yes", text)  # "Don't create a Start Menu folder" checkbox
        self.assertIn("DefaultGroupName=NOP", text)
        self.assertIn('Name: "{group}\\NOP"', text)
        self.assertIn('Name: "{group}\\{cm:UninstallProgram,NOP}"; Filename: "{uninstallexe}"', text)
        self.assertIn('Name: "{group}\\{cm:IconCheck}"; Filename: "{app}\\Check_NOP.bat"', text)
        self.assertNotIn('Name: "{autoprograms}\\NOP"', text)  # no loose shortcut any more
        self.assertIn('Type: files; Name: "{autoprograms}\\NOP.lnk"', text)  # removed on upgrade from older installers
        for name in ("IconCheck", "IconSite"):
            self.assertIn(f"russian.{name}=", text)
            self.assertIn(f"english.{name}=", text)

    def test_installer_has_engine_component(self):
        text = (KIT / "installer" / "NOP_Setup.iss.template").read_text(encoding="utf-8")
        self.assertIn('Name: "engines"', text)
        self.assertIn('Excludes: "converters\\*"', text)
        self.assertNotIn("winget", text)

    def test_selftest_checks_engines(self):
        source = (KIT / "source" / "NOP_1_3.py").read_text(encoding="utf-8")
        for needle in ("NOP_SELFTEST_REQUIRE_ENGINES", "LibreOffice", "Inkscape", "Calibre", "Blender"):
            self.assertIn(needle, source)


class EngineFallbackTests(unittest.TestCase):
    def test_zip_urls_from_winget_msi_url(self):
        rule = json.loads((KIT / "config" / "engines.lock.json").read_text(encoding="utf-8"))["engines"]["blender"]["zip_fallback"]
        zip_url, hash_url = build_kit.zip_fallback_urls("https://download.blender.org/release/Blender5.3/blender-5.3.0-windows-x64.msi", rule)
        self.assertEqual(zip_url, "https://download.blender.org/release/Blender5.3/blender-5.3.0-windows-x64.zip")
        self.assertEqual(hash_url, "https://download.blender.org/release/Blender5.3/blender-5.3.0.sha256")
        self.assertIsNone(build_kit.zip_fallback_urls("", rule))
        self.assertIsNone(build_kit.zip_fallback_urls("https://x/y.exe", rule))

    def test_sha_list_parsing(self):
        digest = "a" * 64
        text = f"{'b' * 64}  blender-5.3.0-linux-x64.tar.xz\n{digest}  blender-5.3.0-windows-x64.zip\n"
        self.assertEqual(build_kit.sha_from_list(text, "blender-5.3.0-windows-x64.zip"), digest)
        self.assertIsNone(build_kit.sha_from_list(text, "missing.zip"))
        self.assertIsNone(build_kit.sha_from_list("nothex  blender-5.3.0-windows-x64.zip", "blender-5.3.0-windows-x64.zip"))


class BlenderProbeTests(unittest.TestCase):
    def test_probe_script_survives_operators_that_raise_keyerror(self):
        """Blender 5.x can raise KeyError for a missing exporter; the probe must still print the format list."""
        import subprocess
        import tempfile as tf
        source = (KIT / "source" / "NOP_1_3.py").read_text(encoding="utf-8")
        start = source.index('code = "import bpy,json')
        line = source[start:source.index("\n", start)]
        namespace = {}
        exec(line, {"operators": {"obj": ["wm.obj_export"], "fbx": ["export_scene.fbx"], "stl": ["wm.stl_export", "export_mesh.stl"]}}, namespace)
        fake = (
            "import sys, types\n"
            "class Op:\n"
            "    def __init__(s, ok): s.ok = ok\n"
            "    def get_rna_type(s):\n"
            "        if not s.ok: raise KeyError('not found')\n"
            "class NS:\n"
            "    def __init__(s, path): s.path = path\n"
            "    def __getattr__(s, part):\n"
            "        full = (s.path + '.' + part) if s.path else part\n"
            "        return Op(full in ('wm.obj_export', 'export_mesh.stl')) if '.' in full else NS(full)\n"
            "bpy = types.ModuleType('bpy'); bpy.ops = NS(''); sys.modules['bpy'] = bpy\n")
        with tf.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as handle:
            handle.write(fake + namespace["code"])
        result = subprocess.run([sys.executable, handle.name], capture_output=True, text=True)
        os.unlink(handle.name)
        self.assertIn('NOP_FORMATS=["obj", "stl"]', result.stdout, result.stderr)


class RmtreeTests(unittest.TestCase):
    def test_removes_read_only_files_and_missing_paths(self):
        import stat
        with tempfile.TemporaryDirectory() as folder:
            tree = Path(folder) / "payload" / "converters" / "calibre" / "ossl-modules"
            tree.mkdir(parents=True)
            locked = tree / "legacy.dll"
            locked.write_bytes(b"x")
            locked.chmod(stat.S_IREAD)                       # what MSI-unpacked files look like
            (tree.parent / "readonly-dir-file.txt").write_bytes(b"y")
            kitlib.rmtree(Path(folder) / "payload")
            self.assertFalse((Path(folder) / "payload").exists())
            kitlib.rmtree(Path(folder) / "does-not-exist")   # no error


class CustomSourceTests(unittest.TestCase):
    def test_kit_source_is_valid_and_version_read(self):
        self.assertEqual(build_kit.validate_source(KIT / "source" / "NOP_1_3.py"), "1.3")

    def test_modified_source_without_hooks_is_rejected_with_explanation(self):
        with tempfile.TemporaryDirectory() as folder:
            bad = Path(folder) / "mine.py"
            bad.write_text('APP_VERSION = "1.2"\nprint("hi")\n', encoding="utf-8")
            with self.assertRaises(kitlib.KitError) as ctx:
                build_kit.validate_source(bad)
            self.assertIn("--nop-selftest", str(ctx.exception))
            broken = Path(folder) / "broken.py"
            broken.write_text("def (:\n", encoding="utf-8")
            with self.assertRaises(kitlib.KitError):
                build_kit.validate_source(broken)

    def test_modified_copy_with_new_version_is_accepted(self):
        with tempfile.TemporaryDirectory() as folder:
            mine = Path(folder) / "NOP_mine.py"
            mine.write_text((KIT / "source" / "NOP_1_3.py").read_text(encoding="utf-8").replace('APP_VERSION = "1.3"', 'APP_VERSION = "1.4"'), encoding="utf-8")
            self.assertEqual(build_kit.validate_source(mine), "1.4")
