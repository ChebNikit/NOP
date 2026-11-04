"""Install a hash-pinned, CA-incident-fixed pip wheel without using pip for downloads.

This bootstrap uses only the Python standard library, so it also repairs a missing
or broken pip inside the private NuGet Python runtime.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import ssl
import sys
import sysconfig
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parent
TOOLS = ROOT / ".build-tools"
WHEEL_NAME = "pip-26.2.2-py3-none-any.whl"
WHEEL_URL = (
    "https://files.pythonhosted.org/packages/3f/06/3e4420302363fbb71be3c7f35ce042f54bfca330e3e66b3a2e3c4cca579f/"
    + WHEEL_NAME
)
WHEEL_SHA256 = "fd7f4dfa8190e014013b9f08f3e973f4e4c26ffd179a204895533a7254813a70"
MINIMUM_BYTES = 1_000_000
USER_AGENT = "NOP-Installer-BuildKit/2026.10.28-secure-pip-bootstrap"


def valid_wheel(path: Path) -> bool:
    if not path.is_file() or path.stat().st_size < MINIMUM_BYTES:
        return False
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    if digest.hexdigest().lower() != WHEEL_SHA256:
        return False
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if archive.testzip() is not None:
                return False
            for name in names:
                member = Path(name)
                if member.is_absolute() or ".." in member.parts:
                    return False
            if "pip/__init__.py" not in names:
                return False
            metadata = next((name for name in names if name.endswith(".dist-info/METADATA") and name.startswith("pip-")), None)
            if not metadata:
                return False
            text = archive.read(metadata).decode("utf-8", errors="strict")
            if "\nName: pip\n" not in "\n" + text or "\nVersion: 26.2.2\n" not in "\n" + text:
                return False
    except (OSError, zipfile.BadZipFile, UnicodeError, KeyError):
        return False
    return True


def download_pinned_wheel(destination: Path) -> None:
    bundled = ROOT / "bootstrap" / WHEEL_NAME
    if bundled != destination and valid_wheel(bundled):
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(bundled, destination)
    if valid_wheel(destination):
        print("Cached pip wheel SHA-256 verified.", flush=True)
        return
    if destination.exists():
        destination.unlink()
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".part")
    for attempt in range(1, 4):
        try:
            if partial.exists():
                partial.unlink()
            request = urllib.request.Request(WHEEL_URL, headers={"User-Agent": USER_AGENT})
            context = ssl.create_default_context()
            with urllib.request.urlopen(request, timeout=120, context=context) as response, partial.open("wb") as output:
                final_url = urllib.parse.urlsplit(response.geturl())
                if final_url.scheme != "https" or final_url.hostname != "files.pythonhosted.org":
                    raise RuntimeError("Unexpected pip wheel redirect; refusing a non-official source")
                total = 0
                while True:
                    block = response.read(1024 * 1024)
                    if not block:
                        break
                    output.write(block)
                    total += len(block)
            if total < MINIMUM_BYTES:
                raise RuntimeError("Downloaded pip wheel is unexpectedly small")
            digest = hashlib.sha256()
            with partial.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            if digest.hexdigest().lower() != WHEEL_SHA256:
                raise RuntimeError("Pinned pip wheel SHA-256 mismatch")
            if not valid_wheel(partial):
                raise RuntimeError("Pinned pip wheel failed SHA-256 / ZIP / metadata validation")
            os.replace(str(partial), str(destination))
            print("Downloaded pip 26.2.2; pinned SHA-256 and wheel structure verified.", flush=True)
            return
        except Exception as error:
            try:
                partial.unlink(missing_ok=True)
            except OSError:
                pass
            if attempt == 3:
                raise RuntimeError("Cannot obtain the verified pip wheel after three attempts: " + str(error)) from error
            print("pip wheel fetch attempt %d failed: %s; retrying" % (attempt, error), flush=True)
            time.sleep(2 * attempt)


def install_wheel(wheel: Path) -> None:
    site_packages = Path(sysconfig.get_paths()["purelib"]).resolve()
    site_packages.mkdir(parents=True, exist_ok=True)
    if not (Path(sys.executable).resolve().parent / "Lib" / "site-packages").resolve() == site_packages:
        # A private NuGet Python should resolve purelib inside its own root. Stop if
        # sysconfig would direct this bootstrap into a global/system installation.
        python_root = Path(sys.executable).resolve().parent
        if python_root not in site_packages.parents:
            raise RuntimeError("Refusing to install pip outside the isolated private Python runtime: " + str(site_packages))
    with tempfile.TemporaryDirectory(prefix=".pip-stage-", dir=str(site_packages.parent)) as temp:
        stage = Path(temp) / "unpacked"
        stage.mkdir()
        with zipfile.ZipFile(wheel) as archive:
            archive.extractall(stage)
        dist_info = next((p for p in stage.glob("pip-*.dist-info") if p.is_dir()), None)
        staged_pip = stage / "pip"
        if not staged_pip.is_dir() or dist_info is None:
            raise RuntimeError("Verified pip wheel is missing its package or dist-info folder")

        # Move both package and metadata aside first. If either installation or the
        # runtime version test fails, restore the old pair for a clean retry.
        backup = Path(temp) / "backup"
        backup.mkdir()
        old_pip = site_packages / "pip"
        old_infos = [p for p in site_packages.glob("pip-*.dist-info") if p.is_dir()]
        had_old_pip = old_pip.exists()
        old_info_map = []
        if had_old_pip:
            os.replace(str(old_pip), str(backup / "pip"))
        for index, old_info in enumerate(old_infos):
            backup_info = backup / ("dist-info-%d" % index)
            os.replace(str(old_info), str(backup_info))
            old_info_map.append((backup_info, old_info.name))
        try:
            os.replace(str(staged_pip), str(old_pip))
            new_info = site_packages / dist_info.name
            os.replace(str(dist_info), str(new_info))
            # Run the private interpreter in isolated mode; no package index/network
            # access happens in this step, and the version must match the pinned wheel.
            import subprocess
            result = subprocess.run(
                [sys.executable, "-I", "-c", "import pip,sys;print(pip.__version__);sys.exit(0 if pip.__version__ == '26.2.2' else 1)"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=30,
            )
            if result.returncode != 0:
                raise RuntimeError("Installed pip failed the exact-version check: " + result.stdout[-2000:])
        except Exception:
            if old_pip.exists():
                shutil.rmtree(old_pip, ignore_errors=True)
            for current_info in site_packages.glob("pip-*.dist-info"):
                if current_info.name == dist_info.name:
                    shutil.rmtree(current_info, ignore_errors=True)
            if (backup / "pip").exists():
                os.replace(str(backup / "pip"), str(old_pip))
            for backup_info, original_name in old_info_map:
                if backup_info.exists():
                    os.replace(str(backup_info), str(site_packages / original_name))
            raise
    print("Pinned pip 26.2.2 installed into " + str(site_packages), flush=True)


def main() -> int:
    if sys.version_info[:2] != (3, 13) or Path(sys.executable).resolve().parent != (ROOT / ".build-python").resolve():
        raise RuntimeError("Run this bootstrap with the isolated BuildKit Python 3.13 runtime")
    wheel = TOOLS / WHEEL_NAME
    download_pinned_wheel(wheel)
    install_wheel(wheel)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print("SECURE PIP BOOTSTRAP FAILED: " + str(error), file=sys.stderr, flush=True)
        raise SystemExit(1)
