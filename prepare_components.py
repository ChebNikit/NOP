"""Prepare the Equalizer APO and Microsoft runtime payloads for offline setup."""
from __future__ import annotations

import argparse
import certifi
import ast
from email.utils import parsedate_to_datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "component_config.json"
RUNTIME = ROOT / "runtime_deps"
MANIFEST = RUNTIME / "component-manifest.json"
USER_AGENT = "NOP-Installer-BuildKit/2026.10.27-r5"


def trusted_ssl_context():
    """Trust OS-managed roots (including enterprise roots) plus pinned Certifi.

    Certificate and hostname verification remain required. This does not accept
    an arbitrary certificate merely because the network returned it.
    """
    import ssl
    context = ssl.create_default_context()
    context.load_verify_locations(cafile=certifi.where())
    return context


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def filesystem_path(path: Path) -> Path:
    """Use Windows extended paths for filesystem operations, not CLI arguments."""
    if os.name != "nt":
        return path
    value = os.path.abspath(path)
    if value.startswith("\\\\?\\"):
        return Path(value)
    if value.startswith("\\\\"):
        return Path("\\\\?\\UNC\\" + value[2:])
    return Path("\\\\?\\" + value)


def rate_limit_delay(error, attempt):
    """Honor Retry-After without waiting indefinitely inside a build stage."""
    delay = 2 * (attempt + 1)
    value = (error.headers or {}).get('Retry-After', '').strip()
    if value:
        try:
            delay = int(value) if value.isdecimal() else int(parsedate_to_datetime(value).timestamp() - time.time()) + 1
        except (TypeError, ValueError, OverflowError):
            pass
    if delay > 60:
        raise RuntimeError('HTTP 429: upstream asks to retry after ' + str(delay) +
                           ' seconds; resume later. Cached downloads were retained.') from error
    return max(1, delay)


def request_json(url: str):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=90, context=trusted_ssl_context()) as response:
                if response.geturl().split(":", 1)[0] != "https":
                    raise RuntimeError("Unexpected non-HTTPS redirect")
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code == 429 and attempt < 2:
                delay = rate_limit_delay(error, attempt)
                print(f'Metadata HTTP 429; retrying in {delay}s ({attempt + 1}/3).', flush=True)
                time.sleep(delay)
                continue
            if error.code in (403, 404) or attempt == 2:
                raise RuntimeError(f"Metadata unavailable: HTTP {error.code}: {url}. Cached files are retained.") from error
        except OSError:
            if attempt == 2:
                raise
        time.sleep(2 * (attempt + 1))


def pe_machine(path: Path) -> int:
    if path.stat().st_size < 70:
        raise ValueError(f"Truncated Windows executable header: {path}")
    with path.open("rb") as stream:
        if stream.read(2) != b"MZ":
            raise ValueError(f"Not a Windows executable: {path}")
        stream.seek(0x3C)
        offset = struct.unpack("<I", stream.read(4))[0]
        if not 64 <= offset <= path.stat().st_size - 6:
            raise ValueError(f"Invalid PE header: {path}")
        stream.seek(offset)
        if stream.read(4) != b"PE\0\0":
            raise ValueError(f"Invalid PE signature: {path}")
        return struct.unpack("<H", stream.read(2))[0]


def download(url: str, destination: Path, expected: str | None = None, minimum: int = 1024) -> None:
    if urllib.parse.urlsplit(url).scheme != "https":
        raise ValueError("Only HTTPS sources are accepted")
    if expected is not None and not re.fullmatch(r"[0-9a-fA-F]{64}", expected):
        raise ValueError("Invalid SHA-256 metadata")
    if destination.is_file() and destination.stat().st_size >= minimum:
        if expected is None or sha256(destination).lower() == expected.lower():
            print(f"Cached: {destination.name}", flush=True)
            return
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".part")
    # A complete R12 archive supplies these caches. Repair a missing/corrupt
    # workspace copy from it before using the network; never trust by filename.
    original = os.environ.get('NOP_OUTPUT_ROOT')
    if original and expected:
        try:
            relative = destination.resolve().relative_to(ROOT.resolve())
            bundled = filesystem_path(Path(original) / relative)
            if bundled.is_file() and sha256(bundled).lower() == expected.lower():
                shutil.copy2(bundled, partial)
                if sha256(partial).lower() != expected.lower():
                    raise RuntimeError('Bundled payload copy SHA-256 mismatch')
                partial.replace(destination)
                print('Restored bundled payload:', destination.name, flush=True)
                return
        except (OSError, ValueError):
            partial.unlink(missing_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(3):
        try:
            print(f"Downloading {destination.name} (attempt {attempt + 1}/3)", flush=True)
            with urllib.request.urlopen(request, timeout=120, context=trusted_ssl_context()) as response, partial.open("wb") as output:
                if urllib.parse.urlsplit(response.geturl()).scheme != "https":
                    raise RuntimeError("Download redirected to non-HTTPS")
                content_length = response.headers.get("Content-Length")
                total = 0
                last_notice = 0
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
                    total += len(chunk)
                    if total - last_notice >= 32 * 1024 * 1024:
                        print(f"  {total // (1024 * 1024)} MiB", flush=True)
                        last_notice = total
            if content_length and total != int(content_length):
                raise RuntimeError("Incomplete HTTP body; the payload will not be used")
            if partial.stat().st_size < minimum:
                raise RuntimeError("Download is unexpectedly small; it may be an HTML error page")
            if expected and sha256(partial).lower() != expected.lower():
                raise RuntimeError("SHA-256 mismatch; the payload will not be used")
            partial.replace(destination)
            return
        except urllib.error.HTTPError as error:
            partial.unlink(missing_ok=True)
            if error.code == 429 and attempt < 2:
                delay = rate_limit_delay(error, attempt)
                print(f'Download HTTP 429; retrying in {delay}s ({attempt + 1}/3).', flush=True)
                time.sleep(delay)
                continue
            if error.code in (401, 403, 404) or attempt == 2:
                raise RuntimeError(f"HTTP {error.code} downloading {url}. You can place the original upstream file at {destination} and retry.") from error
        except (OSError, RuntimeError):
            partial.unlink(missing_ok=True)
            if attempt == 2:
                raise
        time.sleep(2 * (attempt + 1))


def run(args: list[str], timeout: int = 1800) -> subprocess.CompletedProcess:
    result = subprocess.run(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace", timeout=timeout,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return result


def signed_microsoft_version(path: Path) -> str:
    # Pass the path as a script argument rather than interpolating it as PowerShell code.
    script = ROOT / "verify_microsoft_payload.ps1"
    result = run([str(Path(os.environ["WINDIR"]) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), "-Payload", str(path)], timeout=120)
    if result.returncode:
        raise RuntimeError("Microsoft runtime signature check failed: " + result.stdout[-1500:])
    version = result.stdout.strip().splitlines()[-1]
    if not re.fullmatch(r"\d+(?:\.\d+){1,3}", version):
        raise RuntimeError("Cannot read Visual C++ runtime version")
    return version


def validate_only() -> None:
    configuration = json.loads(CONFIG.read_text(encoding="utf-8"))
    for name in ("apo", "vc_redist"):
        if name not in configuration:
            raise ValueError("Missing setup payload configuration: " + name)
    source = ROOT / "NOP_1.0.py"
    ast.parse(source.read_text(encoding="utf-8"))
    for filename in ("NOP_installer.iss", "build_windows.bat", "runtime_hook.py", "nop_bundle_check.py", "assets/nop.ico", "assets/avatar.jpg", "assets/donate_crypto_qr.jpg", "assets/donate_ozon_qr.jpg", "installer-art/wizard.png"):
        if not (ROOT / filename).is_file():
            raise FileNotFoundError(filename)
    print("Build-kit static validation OK. No downloads or installers were run.")


def prepare_installer_payloads(configuration: dict) -> dict:
    # Rebuild this manifest so converter records from r1-r3 cannot enter the new bundle.
    # Existing downloads and extracted application folders are left in the cache.
    manifest = {}
    apo = configuration["apo"]
    apo_file = RUNTIME / "installers" / apo["filename"]
    download(apo["url"], apo_file, apo["sha256"], 1024 * 1024)
    if pe_machine(apo_file) not in (0x14C, 0x8664):
        raise RuntimeError("Unsupported Equalizer APO installer architecture")
    manifest["apo"] = {**apo, "bytes": apo_file.stat().st_size}
    write_json(MANIFEST, manifest)
    vc = configuration["vc_redist"]
    vc_file = RUNTIME / "installers" / vc["filename"]
    download(vc["url"], vc_file, vc.get("sha256"), minimum=1024 * 1024)
    version = signed_microsoft_version(vc_file)
    manifest["vc_redist"] = {**vc, "version": version, "sha256": sha256(vc_file), "bytes": vc_file.stat().st_size}
    write_json(MANIFEST, manifest)
    print("Equalizer APO and Visual C++ payloads are ready. External converters are not downloaded.", flush=True)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    if args.validate_only:
        validate_only()
        return 0
    if sys.platform != "win32" or struct.calcsize("P") != 8:
        raise RuntimeError("Build this Windows x64 installer on Windows x64")
    configuration = json.loads(CONFIG.read_text(encoding="utf-8"))
    prepare_installer_payloads(configuration)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print("COMPONENT PREPARATION FAILED: " + str(error), file=sys.stderr, flush=True)
        raise SystemExit(1)
