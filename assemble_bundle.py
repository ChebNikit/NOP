"""Assemble native runtimes outside Qt's private DLL directory and write real versions."""
from __future__ import annotations

import importlib.metadata
import datetime
from prepare_components import sha256
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys

from prepare_components import filesystem_path, write_json
from nop_bundle_check import check_author_assets
from native_conflicts import check_inprocess_conflicts

ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / "runtime_deps"
DIST = ROOT / "dist" / "NOP"


def copy_directory(source: Path, destination: Path) -> None:
    source, destination = filesystem_path(source), filesystem_path(destination)
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)


def version_line(path: Path, option: str) -> str:
    result = subprocess.run([str(path), option], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode:
        raise RuntimeError(f"Cannot launch {path.name}: {result.returncode}")
    return result.stdout.decode("utf-8", "replace").splitlines()[0]


def inno_string(value: str) -> str:
    return value.replace('"', '""').replace("\r", " ").replace("\n", " ")


def main() -> None:
    if not (DIST / "NOP.exe").is_file():
        raise FileNotFoundError("PyInstaller did not produce dist/NOP/NOP.exe")
    prepared = json.loads((RUNTIME / "component-manifest.json").read_text(encoding="utf-8"))
    components = {key: prepared[key] for key in ("apo", "vc_redist")}
    for filename in ("ffmpeg.exe", "ffprobe.exe", "deno.exe"):
        shutil.copy2(RUNTIME / filename, DIST / filename)
    copy_directory(RUNTIME / "mpv", DIST / "mpv")
    # Each engine keeps its own DLLs; none are copied into the Qt/Python directory.
    copy_directory(RUNTIME / "converters", DIST / "converters")
    shutil.copy2(RUNTIME / "converters-manifest.json", DIST / "converters-manifest.json")
    shutil.copy2(ROOT / "CHECK_INSTALLED.bat", DIST / "CHECK_INSTALLED.bat")
    (DIST / "source").mkdir(exist_ok=True)
    shutil.copy2(ROOT / "NOP_1.0.py", DIST / "source" / "NOP_1.0.py")
    copy_directory(ROOT / "assets", DIST / "assets")
    check_author_assets(DIST)
    check_inprocess_conflicts(DIST)
    (DIST / "licenses").mkdir(exist_ok=True)
    for filename in ("FFMPEG-LICENSE.txt", "FFMPEG-SOURCE.txt", "DENO-SOURCE.txt"):
        if not (RUNTIME / filename).is_file():
            raise FileNotFoundError("Upstream runtime notice missing: " + filename)
        shutil.copy2(RUNTIME / filename, DIST / "licenses" / filename)
    shutil.copy2(ROOT / "THIRD_PARTY_NOTICES.txt", DIST / "THIRD_PARTY_NOTICES.txt")
    shutil.copy2(ROOT / "README_RU.txt", DIST / "README_RU.txt")
    write_json(DIST / "component-manifest.json", components)
    shutil.copy2(RUNTIME / "runtime-manifest.json", DIST / "runtime-manifest.json")
    packages = {name: importlib.metadata.version(name) for name in (
        "PyQt6", "PyQt6-Qt6", "numpy", "yt-dlp", "yt-dlp-ejs", "Pillow", "mutagen", "PyMuPDF")}
    manifest = {
        "application": "NOP - NikOmniPlayer", "version": "1.0", "python": platform.python_version(),
        "application_source_sha256": sha256(ROOT / "NOP_1.0.py"),
        "built_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "packages": packages, "ffmpeg": version_line(DIST / "ffmpeg.exe", "-version"),
        "ffprobe": version_line(DIST / "ffprobe.exe", "-version"), "deno": version_line(DIST / "deno.exe", "--version"),
        "components": components,
        "converters": json.loads((RUNTIME / "converters-manifest.json").read_text(encoding="utf-8")),
        "minimum_windows_build": 17763,
        "compatibility_certified": False,
        "note": "Build PC checks do not certify clean-VM installation or other Windows versions",
    }
    (DIST / "bundle-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    dependencies = [
        "ВСТРОЕНО В NOP", "",
        f"Python {manifest['python']} — среда работы приложения",
        f"PyQt6 {packages['PyQt6']} / Qt {packages['PyQt6-Qt6']} — интерфейс, окна и мультимедиа",
        f"NumPy {packages['numpy']} — обработка аудио и изображения",
        f"yt-dlp {packages['yt-dlp']} / EJS {packages['yt-dlp-ejs']} — загрузка медиа",
        manifest["ffmpeg"], manifest["ffprobe"], manifest["deno"],
        "libmpv LGPL x64 — основной видеодвижок",
        f"Pillow {packages['Pillow']}, Mutagen {packages['mutagen']}, PyMuPDF {packages['PyMuPDF']} — изображения и свойства файлов",
        "", "УСТАНАВЛИВАЕТСЯ АВТОМАТИЧЕСКИ ПРИ ОТСУТСТВИИ", "",
    ]
    dependencies.extend([
        f"Equalizer APO {components['apo']['version']} — эквалайзер для звука других программ",
        "", f"Visual C++ Runtime {components['vc_redist']['version']} — проверяется и при необходимости устанавливается отдельно.",
        "", "Python, pip и медиабиблиотеки вручную устанавливать не нужно.",
        "LibreOffice, Inkscape, calibre и Blender размещены в converters и включены в установщик для соответствующих категорий конвертации.",
    ])
    (DIST / "DEPENDENCIES_RU.txt").write_text("\n".join(dependencies) + "\n", encoding="utf-8-sig")
    macros = {
        "PythonVersion": manifest["python"], "QtVersion": packages["PyQt6-Qt6"], "PyQtVersion": packages["PyQt6"],
        "YtDlpVersion": packages["yt-dlp"], "NumPyVersion": packages["numpy"],
        "PillowVersion": packages["Pillow"], "MutagenVersion": packages["mutagen"], "MuPDFVersion": packages["PyMuPDF"],
        "FfmpegVersion": manifest["ffmpeg"], "DenoVersion": manifest["deno"],
        "APOVersion": components["apo"]["version"], "VCVersion": components["vc_redist"]["version"],
    }
    (ROOT / "installer_versions.iss").write_text("; Generated from the verified payloads; do not enter guessed versions.\n" +
        "\n".join(f'#define {key} "{inno_string(str(value))}"' for key, value in macros.items()) + "\n", encoding="utf-8-sig")
    freeze = subprocess.check_output([sys.executable, "-m", "pip", "freeze"], text=True, encoding="utf-8")
    (DIST / "BUILD_REQUIREMENTS_LOCK.txt").write_text(freeze, encoding="utf-8")
    print("Media runtimes, author images, application icon, licenses and actual version manifest assembled.")


if __name__ == "__main__":
    main()
