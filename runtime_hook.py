"""Private media paths and frozen-bundle checks; no persistent PATH changes."""
import json
import os
from pathlib import Path
import sys
import traceback
import tempfile
import datetime

_validation_profile = None
if len(sys.argv) > 1 and sys.argv[1] in ("--nop-bundle-check", "--nop-functional-check", "--nop-youtube-check"):
    _validation_profile = tempfile.TemporaryDirectory(prefix="nop-validation-profile-")
    sys._nop_validation_profile = _validation_profile  # Keep it alive across runtime-hook namespaces.
    os.environ["APPDATA"] = _validation_profile.name
    os.environ["NOP_VALIDATION_PROFILE"] = _validation_profile.name
    if sys.argv[1] == "--nop-functional-check":
        os.environ["QT_QPA_PLATFORM"] = "windows"
    os.environ.pop("YAMI_BACKEND", None)

# Keep unexpected Python exceptions from windowed builds diagnosable.
def _nop_exception(kind, error, tb):
    try:
        main = sys.modules.get("__main__")
        redact = getattr(main, "redact_diagnostic", lambda v: str(v)[:5000])
        path = Path(os.environ.get("APPDATA", str(Path.home()))) / "YamiFM" / "logs" / "exceptions.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_file() and path.stat().st_size > 2 * 1024 * 1024:
            path.replace(path.with_suffix(".previous.log"))
        with path.open("a", encoding="utf-8") as out:
            out.write(datetime.datetime.now(datetime.timezone.utc).isoformat() + "\n" +
                      redact("".join(traceback.format_exception(kind, error, tb))) + "\n")
    except Exception:
        pass
sys.excepthook = _nop_exception
import certifi

root = Path(sys.executable).resolve().parent
_ca_bundle = Path(certifi.where()).resolve()
if not _ca_bundle.is_file():
    raise RuntimeError("Pinned Certifi CA bundle is missing from the frozen application")
os.environ["SSL_CERT_FILE"] = str(_ca_bundle)
directories = [root, root / "bin"]
os.environ["PATH"] = os.pathsep.join([str(p) for p in directories if p.is_dir()] + [os.environ.get("PATH", "")])

if len(sys.argv) == 3 and sys.argv[1] == "--nop-bundle-check":
    report = Path(sys.argv[2])
    try:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        from nop_bundle_check import run_check
        code = run_check(root, report)
    except Exception:
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps({"ok": False, "error": traceback.format_exc()}, ensure_ascii=False, indent=2), encoding="utf-8")
        code = 1
    raise SystemExit(code)
