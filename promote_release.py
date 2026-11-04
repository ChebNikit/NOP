"""Atomically promote a fully validated staged NOP installer without losing the last good release.

Python 3.8-compatible so this helper also serves the Windows 7 build path.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile

CONFIG = {
    "win10": {
        "setup": "NOP_Setup.exe",
        "checksum": "SHA256.txt",
        "companions": ("bundle-manifest.json", "DEPENDENCIES_RU.txt"),
        "minimum_bytes": 10_000_000,
    },
    "win7": {
        "setup": "NOP_1.0_Setup_Win7_x64.exe",
        "checksum": "SHA256_WIN7.txt",
        "companions": ("bundle-manifest-win7.json", "WIN7_YOUTUBE_LIMITATIONS.txt"),
        "minimum_bytes": 1_000_000,
    },
}


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate(root, variant):
    if variant not in CONFIG:
        raise ValueError("Choose win10 or win7")
    config = CONFIG[variant]
    release = root / "release"
    stage = release / "staging" / variant
    setup = stage / config["setup"]
    checksum = stage / config["checksum"]
    if not setup.is_file() or setup.stat().st_size < config["minimum_bytes"]:
        raise RuntimeError("Staged installer is missing or implausibly small: " + str(setup))
    with setup.open("rb") as stream:
        if stream.read(2) != b"MZ":
            raise RuntimeError("Staged installer has no PE/DOS signature: " + str(setup))
    if not checksum.is_file():
        raise RuntimeError("Staged SHA-256 file is missing: " + str(checksum))
    text = checksum.read_text(encoding="ascii").strip()
    match = re.fullmatch(r"([0-9a-fA-F]{64})  (\S+)", text)
    if not match or match.group(2) != config["setup"]:
        raise RuntimeError("Staged checksum must contain a SHA-256 and the exact installer filename")
    actual = sha256(setup)
    if actual.lower() != match.group(1).lower():
        raise RuntimeError("Staged installer SHA-256 mismatch; previous release was not changed")

    for name in config["companions"]:
        path = stage / name
        if not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError("Staged release metadata is missing or empty: " + str(path))
    manifest_name = config["companions"][0]
    try:
        json.loads((stage / manifest_name).read_text(encoding="utf-8-sig"))
    except Exception as error:
        raise RuntimeError("Staged bundle manifest is not valid JSON: " + str(error)) from error

    # Sources are moved only after every artifact has passed validation.
    promotions = [(stage / name, release / name) for name in config["companions"]]
    promotions.append((checksum, release / config["checksum"]))
    promotions.append((setup, release / config["setup"]))  # installer is the final commit item
    return stage, release, promotions


def promote_release(root, variant):
    root = Path(root).resolve()
    stage, release, promotions = _validate(root, variant)
    release.mkdir(parents=True, exist_ok=True)
    config = CONFIG[variant]

    with tempfile.TemporaryDirectory(prefix=".promotion-rollback-", dir=str(release)) as backup_name:
        backup_root = Path(backup_name)
        previous = {}
        for index, (_source, target) in enumerate(promotions):
            if target.exists():
                if not target.is_file():
                    raise RuntimeError("Release destination exists but is not a regular file: " + str(target))
                backup = backup_root / ("previous-" + str(index))
                shutil.copy2(target, backup)
                previous[target] = backup
            else:
                previous[target] = None

        committed = []
        try:
            for source, target in promotions:
                # Stage and destination share the same volume. os.replace makes
                # each individual file replacement atomic on Windows and POSIX.
                os.replace(str(source), str(target))
                committed.append(target)
        except Exception as error:
            rollback_errors = []
            for target in reversed(committed):
                backup = previous[target]
                try:
                    if backup is None:
                        if target.exists():
                            target.unlink()
                    else:
                        os.replace(str(backup), str(target))
                except Exception as rollback_error:
                    rollback_errors.append(str(target) + ": " + str(rollback_error))
            message = "Release promotion failed; attempted to restore the previous release: " + str(error)
            if rollback_errors:
                message += "; rollback errors: " + " | ".join(rollback_errors)
            raise RuntimeError(message) from error

    print("RELEASE PROMOTION PASS: " + str(release / config["setup"]))
    print("SHA-256: " + sha256(release / config["setup"]))
    print("Previous release was retained until staged installer and metadata passed validation.")
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 1 or argv[0] not in CONFIG:
        print("Usage: promote_release.py win10|win7", file=sys.stderr)
        return 2
    try:
        return promote_release(Path(__file__).resolve().parent, argv[0])
    except Exception as error:
        print("RELEASE PROMOTION FAILED: " + str(error), file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
