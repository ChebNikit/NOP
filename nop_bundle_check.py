"""A frozen-process check, run without Python or tool directories on PATH."""
from __future__ import annotations

import ctypes
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import traceback


def check_author_assets(root: Path) -> str:
    """Require all bundled author images to decode.

    Prefer Qt's decoder in the frozen application. Use Pillow only for source-tree
    tests that deliberately run without the large Qt runtime installed; the full
    frozen smoke test imports QApplication and QtGui independently, so this fallback
    cannot conceal a missing Qt runtime in a packaged build.
    """
    try:
        from PyQt6.QtGui import QImageReader
    except ImportError:
        QImageReader = None

    details = []
    for filename in ("avatar.jpg", "donate_crypto_qr.jpg", "donate_ozon_qr.jpg"):
        path = root / "assets" / filename
        if not path.is_file():
            raise FileNotFoundError("Required author image missing: " + str(path))
        if QImageReader is not None:
            reader = QImageReader(str(path))
            image = reader.read()
            if image.isNull():
                raise RuntimeError(f"Cannot decode {path}: {reader.errorString()}")
            width, height = image.width(), image.height()
            decoder = "Qt"
        else:
            try:
                from PIL import Image
                with Image.open(path) as image:
                    image.verify()
                with Image.open(path) as image:
                    width, height = image.size
            except Exception as error:
                raise RuntimeError(f"Cannot decode {path} with Pillow: {error}") from error
            decoder = "Pillow (source-tree fallback)"
        details.append(f"{filename}: {width}x{height} [{decoder}]")
    return "; ".join(details)


def run_check(root: Path, report: Path) -> int:
    checks = []
    report.parent.mkdir(parents=True, exist_ok=True)

    def checkpoint(stage):
        report.write_text(json.dumps({"ok": False, "stage": stage, "checks": checks}, ensure_ascii=False, indent=2), encoding="utf-8")

    checkpoint("loading Qt")

    def check(name, function):
        checkpoint(name)
        try:
            detail = function()
            checks.append({"name": name, "ok": True, "detail": str(detail)})
        except Exception as error:
            checks.append({"name": name, "ok": False, "detail": str(error), "trace": traceback.format_exc()})
        checkpoint(name + " finished")

    def version_command(path: Path, option: str):
        if not path.is_file():
            raise FileNotFoundError(path)
        environment = {key: value for key, value in os.environ.items()
                       if not key.upper().startswith(("QT_", "QML", "PYTHON", "_PYI_"))}
        # PyInstaller's inherited DLL directory must not override a media tool's DLLs.
        kernel = ctypes.windll.kernel32
        kernel.GetDllDirectoryW.argtypes = [ctypes.c_uint32, ctypes.c_wchar_p]
        kernel.GetDllDirectoryW.restype = ctypes.c_uint32
        kernel.SetDllDirectoryW.argtypes = [ctypes.c_wchar_p]
        kernel.SetDllDirectoryW.restype = ctypes.c_int
        buffer = ctypes.create_unicode_buffer(32768)
        kernel.GetDllDirectoryW(len(buffer), buffer)
        kernel.SetDllDirectoryW(None)
        try:
            process = subprocess.run([str(path), option], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, timeout=45, env=environment,
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        finally:
            kernel.SetDllDirectoryW(buffer.value or None)
        if process.returncode:
            raise RuntimeError(f"Exit code {process.returncode}: {path.name}")
        lines = process.stdout.decode("utf-8", "replace").splitlines()
        return lines[0] if lines else path.name + " launched successfully"

    def check_windows_plugin():
        path = root / "_internal" / "PyQt6" / "Qt6" / "plugins" / "platforms" / "qwindows.dll"
        if not path.is_file():
            raise FileNotFoundError(path)
        return path

    def check_icon():
        from PyQt6.QtGui import QIcon
        icon = QIcon(str(root / "assets" / "nop.ico"))
        if icon.isNull() or len(icon.availableSizes()) < 7:
            raise RuntimeError("Bundled icon is missing or incomplete")
        return ", ".join(str(size.width()) for size in icon.availableSizes())

    def check_mpv():
        directory = root / "mpv"
        handle = os.add_dll_directory(str(directory))
        try:
            library = ctypes.CDLL(str(directory / "libmpv-2.dll"))
            library.mpv_client_api_version.restype = ctypes.c_ulong
            return "client API " + str(library.mpv_client_api_version())
        finally:
            handle.close()

    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    check("frozen Python", lambda: sys.version if getattr(sys, "frozen", False) else (_ for _ in ()).throw(RuntimeError("Not a frozen process")))
    check("Qt icon", check_icon)
    check("Author avatar and donation QR images", lambda: check_author_assets(root))
    check("Qt Windows plugin", check_windows_plugin)
    check("Qt multimedia", lambda: importlib.import_module("PyQt6.QtMultimedia"))
    for module in ("numpy", "yt_dlp", "yt_dlp_ejs", "PIL.Image", "mutagen", "fitz"):
        check(module, lambda name=module: importlib.import_module(name))
    check("FFmpeg", lambda: version_command(root / "ffmpeg.exe", "-version"))
    check("FFprobe", lambda: version_command(root / "ffprobe.exe", "-version"))
    check("Deno", lambda: version_command(root / "deno.exe", "--version"))
    check("libmpv", check_mpv)
    result = {"ok": all(row["ok"] for row in checks), "root": str(root), "checks": checks}
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    app.processEvents()
    return 0 if result["ok"] else 1
