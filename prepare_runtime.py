"""Prepare media tools without PowerShell's native stderr/ErrorRecord conversion."""
from __future__ import annotations

import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from zipfile import ZipFile

from prepare_components import filesystem_path, ROOT, download, pe_machine, request_json, run, sha256, trusted_ssl_context, write_json

RUNTIME = ROOT / "runtime_deps"
CACHE = ROOT / ".build-tools" / "media-downloads"
LOG = ROOT / ".build-tools" / "runtime-preparation.log"
NATIVE_LOCK = json.loads((ROOT / "native_sources.lock.json").read_text(encoding="utf-8"))
FFMPEG_URL = NATIVE_LOCK["ffmpeg"]["url"]
MPV_API = "https://api.github.com/repos/mpv-player/mpv/releases/tags/git-release"
MPV_PATTERN = r"^libmpv-(?:.*-)?x86_64-w64-mingw32-lgpl\.zip$"


def note(message: str) -> None:
    print(message, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as stream:
        stream.write(message + "\n")


def command_output(args: list[str], timeout: int = 90) -> str:
    """stderr is text; only an unsuccessful exit code/timeout means failure."""
    try:
        result = run(args, timeout=timeout)
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(f"Timeout after {timeout}s: {Path(args[0]).name}") from error
    except OSError as error:
        raise RuntimeError(f"Cannot start {Path(args[0]).name}: {error}") from error
    output = result.stdout or ""
    if result.returncode != 0:
        status = f"{result.returncode} (0x{result.returncode & 0xFFFFFFFF:08X})"
        raise RuntimeError(f"{Path(args[0]).name} exited with {status}.\n{output[-8000:]}")
    return output


def version_of(path: Path, option: str, prefix: str) -> str:
    if not path.is_file() or pe_machine(path) != 0x8664:
        raise RuntimeError(f"Not a valid Windows x64 executable: {path}")
    output = command_output([str(path), option])
    line = next((line.strip() for line in output.splitlines() if line.strip().lower().startswith(prefix.lower())), None)
    if line is None:
        raise RuntimeError(f"{path.name} returned no recognizable version information.\n{output[-2000:]}")
    return line


def cached_version(path: Path, option: str, prefix: str) -> str | None:
    if not path.is_file():
        return None
    try:
        version = version_of(path, option, prefix)
        note(f"Validated cached {path.name}: {version}")
        return version
    except (OSError, ValueError, RuntimeError) as error:
        note(f"Cached {path.name} needs repair: {error}")
        return None


def cached_files_match(component: str, files: dict[str, Path]) -> bool:
    """Trust cached executables only when their hashes match the prior manifest."""
    if not files:
        return False
    manifest_path = RUNTIME / "runtime-manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        metadata = manifest[component]
        locked = NATIVE_LOCK[component]
        expected_archive = (locked["sha256"] if component == "ffmpeg"
                            else required_asset_digest(locked["assets"][0]))
        if metadata.get("archive_sha256") != expected_archive:
            note(f"Cached {component} belongs to another source revision; revalidating.")
            return False
        recorded = metadata["files"]
        if not isinstance(recorded, dict) or set(recorded) != set(files):
            note(f"Cached {component} needs revalidation: no complete file-hash record.")
            return False
        for name, path in files.items():
            expected = recorded.get(name)
            if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", expected):
                note(f"Cached {component} needs revalidation: no valid SHA-256 for {name}.")
                return False
            if not path.is_file() or sha256(path).lower() != expected.lower():
                note(f"Cached {component} needs repair: SHA-256 mismatch for {name}.")
                return False
        return True
    except (OSError, ValueError, KeyError, TypeError) as error:
        note(f"Cached {component} needs revalidation: prior runtime manifest unavailable ({error}).")
        return False


def digest_from_text(value: str) -> str:
    if "<html" in value.lower():
        raise RuntimeError("Received an HTML page instead of an upstream SHA-256 checksum")
    match = re.search(r"(?i)\b[0-9a-f]{64}\b", value)
    if not match:
        raise RuntimeError("Upstream checksum contains no SHA-256 digest")
    return match.group().lower()


def upstream_ffmpeg_hash() -> str:
    request = urllib.request.Request(FFMPEG_URL + ".sha256", headers={"User-Agent": "NOP-Installer-BuildKit-r2"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=90, context=trusted_ssl_context()) as response:
                if urllib.parse.urlsplit(response.geturl()).scheme != "https":
                    raise RuntimeError("Unexpected non-HTTPS checksum redirect")
                value = response.read(16385)
            if len(value) > 16384:
                raise RuntimeError("Checksum response is unexpectedly large")
            return digest_from_text(value.decode("utf-8-sig"))
        except (OSError, urllib.error.URLError) as error:
            if isinstance(error, urllib.error.HTTPError) and error.code in (401, 403, 404, 429):
                raise
            if attempt == 2:
                raise
            note("Checksum metadata request interrupted; retrying...")
            time.sleep(2 * (attempt + 1))
    raise RuntimeError("Cannot retrieve the upstream FFmpeg checksum")


def extract_zip(archive: Path, destination: Path) -> None:
    with ZipFile(archive) as container:
        entries = container.infolist()
        if len(entries) > 100000 or sum(item.file_size for item in entries) > 8 * 1024**3:
            raise RuntimeError("Unexpected media archive size/entry count")
        for item in entries:
            path = PurePosixPath(item.filename.replace("\\", "/"))
            if path.is_absolute() or ".." in path.parts or any(":" in part for part in path.parts):
                raise RuntimeError("Unsafe archive member: " + item.filename)
            if stat.S_ISLNK(item.external_attr >> 16):
                raise RuntimeError("Unexpected symbolic link in a Windows media archive")
        container.extractall(filesystem_path(destination))


def select_asset(assets: list[dict], pattern: str) -> dict:
    selected = [item for item in assets if re.fullmatch(pattern, item.get("name", ""))]
    if len(selected) != 1:
        raise RuntimeError(f"Expected one matching x64 release asset, found {len(selected)}: {pattern}")
    return selected[0]


def asset_digest(asset: dict) -> str | None:
    value = asset.get("digest") or ""
    if not value:
        return None
    if not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", value):
        raise RuntimeError("Unexpected upstream release digest format")
    return value[7:].lower()


def required_asset_digest(asset: dict) -> str:
    """Reject upstream binaries when the release API provides no SHA-256 digest."""
    digest = asset_digest(asset)
    if digest is None:
        raise RuntimeError("Official release asset has no SHA-256 digest; refusing an unverified download: " + str(asset.get("name", "<unnamed>")))
    return digest


def copy_binary(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".new")
    try:
        shutil.copy2(source, temporary)
        temporary.replace(target)
    except OSError as error:
        raise RuntimeError(f"Cannot replace {target}. Close a process using this cached runtime and retry. {error}") from error
    finally:
        temporary.unlink(missing_ok=True)


def prepare_ffmpeg() -> dict:
    ffmpeg, ffprobe = RUNTIME / "ffmpeg.exe", RUNTIME / "ffprobe.exe"
    version = cached_version(ffmpeg, "-version", "ffmpeg version ")
    probe_version = cached_version(ffprobe, "-version", "ffprobe version ")
    stale_dlls = list(RUNTIME.glob("*.dll"))
    cache_hashes_valid = cached_files_match("ffmpeg", {"ffmpeg.exe": ffmpeg, "ffprobe.exe": ffprobe})
    if version is None or probe_version is None or stale_dlls or not cache_hashes_valid:
        for path in stale_dlls:
            path.unlink()
        archive = CACHE / "ffmpeg-9.0.2-full_build.7z"
        download(FFMPEG_URL, archive, NATIVE_LOCK["ffmpeg"]["sha256"], minimum=50000000)
        note("FFmpeg full archive SHA-256 verified.")
        with tempfile.TemporaryDirectory(prefix="nop-ffmpeg-") as directory:
            stage = Path(directory)
            from archive_tools import extract_7z
            extract_7z(archive, stage)
            for filename, target in (("ffmpeg.exe", ffmpeg), ("ffprobe.exe", ffprobe)):
                candidates = list(stage.rglob(filename))
                if len(candidates) != 1:
                    raise RuntimeError("Missing/ambiguous media tool in archive: " + filename)
                copy_binary(candidates[0], target)
        version = version_of(ffmpeg, "-version", "ffmpeg version ")
        probe_version = version_of(ffprobe, "-version", "ffprobe version ")
    # r1 could stop after copying binaries but before writing these files.
    # Regenerate them on every run, including a valid cached-binary run.
    license_text = command_output([str(ffmpeg), "-L"])
    if not license_text.strip():
        raise RuntimeError("FFmpeg returned an empty license text")
    (RUNTIME / "FFMPEG-LICENSE.txt").write_text(license_text, encoding="utf-8-sig")
    (RUNTIME / "FFMPEG-SOURCE.txt").write_text(
        "FFmpeg / FFprobe Windows static full build\nSource: https://www.gyan.dev/ffmpeg/builds/\n" +
        version + "\n" + probe_version + "\nOriginal license text: FFMPEG-LICENSE.txt\n", encoding="utf-8-sig")
    return {"version": version, "ffprobe_version": probe_version, "sha256": sha256(ffmpeg),
            "ffprobe_sha256": sha256(ffprobe),
            "files": {"ffmpeg.exe": sha256(ffmpeg), "ffprobe.exe": sha256(ffprobe)}, "source": FFMPEG_URL}


def prepare_deno() -> dict:
    binary = RUNTIME / "deno.exe"
    version = cached_version(binary, "--version", "deno ")
    source = "https://github.com/denoland/deno/releases"
    if version is None or not cached_files_match("deno", {"deno.exe": binary}):
        release = NATIVE_LOCK["deno"]
        asset = select_asset(release["assets"], r"deno-x86_64-pc-windows-msvc\.zip")
        tag = re.sub(r"[^A-Za-z0-9_.-]", "_", release["tag_name"])
        archive = CACHE / ("deno-" + tag + "-x64.zip")
        download(asset["browser_download_url"], archive, required_asset_digest(asset), minimum=10000000)
        with tempfile.TemporaryDirectory(prefix="nop-deno-") as directory:
            stage = Path(directory)
            extract_zip(archive, stage)
            candidates = list(stage.rglob("deno.exe"))
            if len(candidates) != 1:
                raise RuntimeError("Deno archive has no unique deno.exe")
            copy_binary(candidates[0], binary)
        version = version_of(binary, "--version", "deno ")
        source = release["html_url"]
    (RUNTIME / "DENO-SOURCE.txt").write_text(
        "Deno JavaScript runtime for Windows x64\n" + version + "\nSource: " + source + "\nLicense: MIT and upstream notices.\n", encoding="utf-8-sig")
    return {"version": version, "sha256": sha256(binary),
            "files": {"deno.exe": sha256(binary)}, "source": source}


MPV_PROBE = '''import ctypes,json,os,sys
from pathlib import Path
path=Path(sys.argv[1])
handle=os.add_dll_directory(str(path.parent))
try:
    library=ctypes.CDLL(str(path))
    library.mpv_client_api_version.restype=ctypes.c_ulong
    print(json.dumps({"client_api":int(library.mpv_client_api_version())}))
finally:
    handle.close()
'''


def mpv_api_version(binary: Path) -> int:
    if not binary.is_file() or pe_machine(binary) != 0x8664:
        raise RuntimeError("libmpv-2.dll is missing or is not x64")
    # A child process releases DLLs before any cache repair on Windows.
    output = command_output([sys.executable, "-I", "-c", MPV_PROBE, str(binary)], timeout=45)
    value = int(json.loads(output)["client_api"])
    if value >> 16 != 2:
        raise RuntimeError("libmpv returned an unsupported client API major version")
    return value


def prepare_mpv() -> dict:
    target = RUNTIME / "mpv"
    binary = target / "libmpv-2.dll"
    source = "https://github.com/mpv-player/mpv/releases/tag/git-release"
    try:
        cached_dlls = {path.name: path for path in target.glob("*.dll")}
        if not cached_dlls or not cached_files_match("mpv", cached_dlls):
            raise RuntimeError("Cached libmpv DLL hashes do not match the previous runtime manifest")
        api = mpv_api_version(binary)
        note(f"Validated cached libmpv client API and SHA-256 file manifest: {api}")
    except (OSError, ValueError, RuntimeError):
        release = NATIVE_LOCK["mpv"]
        asset = select_asset(release["assets"], MPV_PATTERN)
        # Keep cache paths short even when the upstream nightly filename is long.
        archive = CACHE / "libmpv-x64-lgpl.zip"
        download(asset["browser_download_url"], archive, required_asset_digest(asset), minimum=10000000)
        with tempfile.TemporaryDirectory(prefix="nop-libmpv-") as directory:
            work = Path(directory)
            unpacked = work / "unpacked"
            staged_target = work / "mpv"
            unpacked.mkdir()
            staged_target.mkdir()
            extract_zip(archive, unpacked)
            dlls = list(unpacked.rglob("*.dll"))
            if not any(p.name.lower() == "libmpv-2.dll" for p in dlls):
                raise RuntimeError("Upstream LGPL archive contains no libmpv-2.dll")
            seen = {}
            for dll in dlls:
                if pe_machine(dll) != 0x8664:
                    raise RuntimeError("Non-x64 DLL in libmpv archive: " + dll.name)
                key = dll.name.lower()
                checksum = sha256(dll)
                if key in seen and seen[key] != checksum:
                    raise RuntimeError("Conflicting dependent DLLs in libmpv archive: " + dll.name)
                seen[key] = checksum
                copy_binary(dll, staged_target / dll.name)
            for path in unpacked.rglob("*"):
                if path.is_file() and path.name.upper().startswith(("LICENSE", "COPYING", "NOTICE")):
                    dest = staged_target / "licenses" / path.relative_to(unpacked)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(path, dest)
            staged_binary = staged_target / next(p.name for p in staged_target.glob("*.dll") if p.name.lower() == "libmpv-2.dll")
            # Probe the candidate before touching the existing runtime.
            api = mpv_api_version(staged_binary)
            source = release["html_url"]
            (staged_target / "SOURCE.txt").write_text(
                "Windows x64 LGPL libmpv\nSource: " + source + "\nArchive: " + asset["name"] + "\n", encoding="utf-8-sig")
            backup = target.with_name(target.name + ".previous")
            if backup.exists():
                shutil.rmtree(backup)
            had_previous = target.exists()
            if had_previous:
                target.replace(backup)
            try:
                staged_target.replace(target)
            except Exception:
                if had_previous and backup.exists() and not target.exists():
                    backup.replace(target)
                raise
            if backup.exists():
                shutil.rmtree(backup)
        binary = target / "libmpv-2.dll"
    if not (target / "SOURCE.txt").is_file():
        (target / "SOURCE.txt").write_text("Windows x64 LGPL libmpv\nSource: " + source + "\n", encoding="utf-8-sig")
    dll_hashes = {path.name: sha256(path) for path in target.glob("*.dll")}
    if "libmpv-2.dll" not in dll_hashes:
        raise RuntimeError("Prepared libmpv DLL manifest is incomplete")
    return {"client_api": api, "sha256": dll_hashes["libmpv-2.dll"], "files": dll_hashes, "source": source}


def main() -> int:
    if sys.platform != "win32" or sys.maxsize <= 2**32:
        raise RuntimeError("Run the Windows x64 build on Windows x64")
    RUNTIME.mkdir(parents=True, exist_ok=True)
    CACHE.mkdir(parents=True, exist_ok=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    LOG.write_text("NOP media runtime preparation r2\n", encoding="utf-8")
    try:
        state = json.loads((RUNTIME / "runtime-manifest.json").read_text(encoding="utf-8"))
        if not isinstance(state, dict):
            state = {}
    except (OSError, ValueError):
        state = {}
    for key, function in (("ffmpeg", prepare_ffmpeg), ("deno", prepare_deno), ("mpv", prepare_mpv)):
        note("Preparing/checking " + key + "...")
        state[key] = function()
        locked = NATIVE_LOCK[key]
        state[key]["archive_sha256"] = (locked["sha256"] if key == "ffmpeg"
                                         else required_asset_digest(locked["assets"][0]))
        write_json(RUNTIME / "runtime-manifest.json", state)
        note(key + " passed exit-code, architecture and runtime checks.")
    note("All media runtimes are ready. Cached downloads and binaries were retained.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as stream:
            stream.write(traceback.format_exc())
        print("ERROR preparing runtime dependencies: " + str(error), file=sys.stderr, flush=True)
        print("Details: " + str(LOG), file=sys.stderr, flush=True)
        raise SystemExit(1)
