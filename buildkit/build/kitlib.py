"""Helpers for the NOP build kit: pinned downloads, signature checks, safe archive extraction.

Everything here is plain standard-library Python so it also runs on the freshly provisioned build
interpreter before any package is installed. No global tools or PATH entries are assumed."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

CHUNK = 1024 * 1024
USER_AGENT = "NOP-BuildKit/1.1 (+https://github.com/ChebNikit/NOP)"


class KitError(RuntimeError):
    """A build step failed in a way the user can act on; the message says how."""


def log(message: str = "") -> None:
    print(message, flush=True)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def human_size(size: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


BROWSER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                 "Chrome/124.0 Safari/537.36")


def _open(url: str, timeout: int = 60, user_agent: str | None = None):
    request = urllib.request.Request(url, headers={"User-Agent": user_agent or USER_AGENT})
    return urllib.request.urlopen(request, timeout=timeout)


def fetch_text(url: str, retries: int = 3) -> str:
    last = None
    for attempt in range(1, retries + 1):
        try:
            with _open(url) as response:
                return response.read().decode("utf-8", "replace")
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            last = exc
            time.sleep(min(2 * attempt, 6))
    raise KitError(f"Cannot reach {url}: {last}. Check the internet connection, proxy or firewall.")


def download(url: str, destination: Path, sha256: str | None = None, size: int | None = None,
             retries: int = 4, label: str = "", user_agent: str | None = None) -> Path:
    """Download to *destination* (resumable by restart, never half-written under the final name).

    When *sha256* is given the file is verified; an existing cached file with a matching hash is reused,
    a corrupt one is deleted and fetched again."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    label = label or destination.name
    if destination.is_file():
        if sha256 is None or sha256_file(destination).lower() == sha256.lower():
            log(f"  [cache] {label}")
            return destination
        log(f"  [cache] {label}: hash mismatch, downloading again")
        destination.unlink()
    partial = destination.with_name(destination.name + ".part")
    last = None
    for attempt in range(1, retries + 1):
        try:
            log(f"  [download {attempt}/{retries}] {label}" + (f" ({human_size(size)})" if size else ""))
            digest = hashlib.sha256()
            done = 0
            shown = 0
            with _open(url, timeout=90, user_agent=user_agent) as response, open(partial, "wb") as out:
                total = int(response.headers.get("Content-Length") or 0)
                for block in iter(lambda: response.read(CHUNK), b""):
                    out.write(block)
                    digest.update(block)
                    done += len(block)
                    if total and done * 10 // total > shown:
                        shown = done * 10 // total
                        log(f"      {shown * 10}%")
            if sha256 and digest.hexdigest().lower() != sha256.lower():
                raise KitError(f"SHA-256 of {label} does not match the pinned value "
                               f"(expected {sha256}, got {digest.hexdigest()}). The file was NOT used.")
            os.replace(partial, destination)
            return destination
        except KitError:
            partial.unlink(missing_ok=True)
            raise  # a wrong hash is a security failure, not a network glitch: never retry silently
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code in (400, 401, 403, 404, 410):
                break  # the address is wrong or forbidden: retrying will not help
            time.sleep(min(3 * attempt, 12))
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            last = exc
            time.sleep(min(3 * attempt, 12))
    partial.unlink(missing_ok=True)
    raise KitError(f"Could not download {label} from {url}: {last}. "
                   f"Download it manually into the 'cache' folder under the same name and run the build again.")


def verify_authenticode(path: Path, signer_contains: list[str]) -> str:
    """Valid Authenticode signature whose subject contains one of the names. Returns the subject."""
    if os.name != "nt":
        raise KitError("Authenticode verification is only available on Windows.")
    # The path travels in an environment variable: with "-Command" extra arguments are NOT available as $args.
    script = ("$s = Get-AuthenticodeSignature -LiteralPath $env:NOP_KIT_PATH; "
              "if ($s.Status -ne 'Valid') { Write-Output ('STATUS:' + $s.Status); exit 3 } "
              "Write-Output ('SUBJECT:' + $s.SignerCertificate.Subject)")
    result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                             "-Command", script], capture_output=True, text=True, timeout=120,
                            env={**os.environ, "NOP_KIT_PATH": str(path)})
    output = (result.stdout or "").strip()
    if result.returncode != 0 or "SUBJECT:" not in output:
        raise KitError(f"{Path(path).name}: the digital signature is missing or invalid ({output or result.stderr.strip()}).")
    subject = output.split("SUBJECT:", 1)[1].strip()
    if not any(name.lower() in subject.lower() for name in signer_contains):
        raise KitError(f"{Path(path).name}: signed by an unexpected publisher: {subject}")
    return subject


def safe_extract_zip(archive: Path, target: Path) -> list[str]:
    """Extract a ZIP while refusing entries that would escape *target* (zip-slip)."""
    target = Path(target).resolve()
    target.mkdir(parents=True, exist_ok=True)
    names = []
    with zipfile.ZipFile(archive) as bundle:
        for info in bundle.infolist():
            destination = (target / info.filename).resolve()
            if target != destination and target not in destination.parents:
                raise KitError(f"Unsafe path inside {Path(archive).name}: {info.filename}")
            names.append(info.filename)
        bundle.extractall(target)
    return names


def extract_7z(seven_zip: Path, archive: Path, target: Path) -> None:
    target = Path(target)
    target.mkdir(parents=True, exist_ok=True)
    result = subprocess.run([str(seven_zip), "x", "-y", "-bso0", "-bsp0", f"-o{target}", str(archive)],
                            capture_output=True, text=True, timeout=1800)
    if result.returncode != 0:
        raise KitError(f"7-Zip could not extract {Path(archive).name}: {result.stderr.strip() or result.stdout.strip()}")


def newest_series_version(index_json: str, series: str) -> str:
    """Highest stable x.y.z in a NuGet flat-container index that starts with *series* (e.g. '3.13.')."""
    versions = json.loads(index_json).get("versions", [])
    stable = [v for v in versions if v.startswith(series) and re.fullmatch(r"\d+\.\d+\.\d+", v)]
    if not stable:
        raise KitError(f"No stable Python {series}x release was found in the NuGet index.")
    return max(stable, key=lambda v: tuple(int(part) for part in v.split(".")))


def run(command: list[str], cwd: Path | None = None, env: dict | None = None, timeout: int = 7200,
        check: bool = True) -> subprocess.CompletedProcess:
    """Run a child process, stream its output into the build log and fail with its tail on error."""
    log("  $ " + " ".join(f'"{part}"' if " " in str(part) else str(part) for part in command))
    process = subprocess.Popen([str(part) for part in command], cwd=str(cwd) if cwd else None, env=env,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                               encoding="utf-8", errors="replace")
    tail: list[str] = []
    started = time.monotonic()
    assert process.stdout is not None
    for line in process.stdout:
        line = line.rstrip()
        tail.append(line)
        del tail[:-40]
        if line:
            print("    " + line, flush=True)
        if time.monotonic() - started > timeout:
            process.kill()
            raise KitError(f"Command timed out: {command[0]}")
    code = process.wait()
    if check and code != 0:
        raise KitError(f"Command failed with exit code {code}: {command[0]}\n" + "\n".join(tail[-15:]))
    return subprocess.CompletedProcess(command, code, "\n".join(tail), "")


def free_space_gb(path: Path) -> float:
    return shutil.disk_usage(path).free / (1024 ** 3)


def windows_build() -> int:
    """Windows build number (17763 = Windows 10 1809/LTSC 2019), 0 on other systems."""
    if os.name != "nt":
        return 0
    return sys.getwindowsversion().build  # type: ignore[attr-defined]


def rmtree(path, ignore_errors: bool = False, attempts: int = 6) -> None:
    """Delete a folder tree on Windows reliably: clears the read-only flag (files unpacked from MSI packages have it)
    and retries while an antivirus scanner or a just-finished process still holds a file."""
    path = Path(path)
    if not path.exists():
        return

    def make_writable(function, target, error):
        try:
            os.chmod(target, stat.S_IWRITE | stat.S_IREAD)
            function(target)
        except FileNotFoundError:
            return
        except OSError:
            raise error

    last = None
    for attempt in range(1, attempts + 1):
        try:
            shutil.rmtree(path, onexc=make_writable)
            return
        except FileNotFoundError:
            return
        except OSError as exc:
            last = exc
            time.sleep(1.5 * attempt)
    if ignore_errors:
        return
    raise KitError(f"Cannot delete {path}: {last}. Close programs that may be using these files "
                   "(a test copy of NOP, LibreOffice, Blender, an antivirus scan) and run the build again.")
