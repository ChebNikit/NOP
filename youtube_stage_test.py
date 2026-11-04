"""NOP YouTube release gate: verifies the application's actual Downloader, not only yt-dlp --version.

Invoke on build PC with: python youtube_stage_test.py preflight|frozen|legacy-report
Internet access and an accessible public test video are required; failures block release.
Uses the same real downloader worker and never keeps test media.
"""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import traceback

ROOT = Path(__file__).resolve().parent
# A public, short video (~19 seconds). Can be overridden with a user's public test link.
DEFAULT_TEST_URL = "https://www.youtube.com/watch?v=jNQXAC9IVRw"


def _test_url():
    value = os.environ.get("NOP_YOUTUBE_TEST_URL", DEFAULT_TEST_URL).strip()
    if not re.fullmatch(r"https://(?:www\.|m\.)?youtube\.com/watch\?v=[A-Za-z0-9_-]{11}|https://youtu\.be/[A-Za-z0-9_-]{11}", value):
        raise ValueError("Test URL must be a public YouTube watch link without extra parameters")
    return value


def _run(command, env, timeout):
    proc = subprocess.run(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          timeout=timeout, text=True, errors="replace",
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if proc.returncode:
        raise RuntimeError("Command exited with code {}: {}".format(proc.returncode, proc.stdout[-3500:]))
    return proc.stdout


def _report(stage, data):
    report_file = ROOT / "build" / "youtube-{}_test.json".format(stage)
    report_file.parent.mkdir(parents=True, exist_ok=True)
    report_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print("YouTube report:", report_file, flush=True)


def preflight():
    result = {"stage": "preflight", "yt_dlp": "", "ok": False, "runtime": "", "ejs": False}
    try:
        import yt_dlp
        version = str(yt_dlp.version.__version__)
        result["yt_dlp"] = version
        date = tuple(int(x) for x in version.split(".")[:3])
        if date < (2025, 11, 12):
            raise RuntimeError("yt-dlp {} is too old for YouTube EJS; Python 3.8/Win7 is unsupported. "
                               "Use build_windows10.bat to verify downloading on Windows 10/11. "
                               "Do not release this Legacy build as YouTube-capable.".format(version))
        import yt_dlp_ejs
        result["ejs"] = True
        exe = ROOT / "runtime_deps" / "deno.exe"
        if not exe.is_file():
            raise RuntimeError("Bundled Deno is missing: runtime_deps\\deno.exe")
        env = dict(os.environ)
        env["PATH"] = str(exe.parent) + os.pathsep + env.get("PATH", "")
        result["runtime"] = _run([str(exe), "--version"], env, 20).splitlines()[0]
        version_numbers = tuple(int(x) for x in re.findall(r"\d+", result["runtime"])[:3])
        if version_numbers < (2, 0, 0):
            raise RuntimeError("Deno >=2 required")
        for binary in ("ffmpeg.exe", "ffprobe.exe"):
            if not (exe.parent / binary).is_file():
                raise RuntimeError("Bundled {} is missing".format(binary))
        result["url"] = _test_url()
        # The actual worker will be exercised on the frozen EXE. This preliminary
        # check catches a missing EJS runtime before the expensive PyInstaller step.
        result["ok"] = True
        print("YouTube preflight passed: yt-dlp {}, {}, EJS installed".format(version, result["runtime"]))
        return 0
    except Exception as exc:
        result["error"] = str(exc)
        print("YOUTUBE PREFLIGHT FAILED:", exc, file=sys.stderr)
        return 1
    finally:
        _report("preflight", result)


def legacy_report():
    """Report the Win7 limitation without pretending YouTube was verified."""
    report = {
        "stage": "win7-legacy", "ok": False, "youtube_supported": False,
        "yt_dlp": "2024.10.22", "note": (
            "Windows 7 / Python 3.8 legacy yt-dlp cannot use current EJS. "
            "This limited installer is NOT verified for YouTube downloading."
        )
    }
    _report("legacy", report)
    print("WIN7 LIMITED: mpv and other features may build; YouTube download is NOT supported.", flush=True)
    return 0


def run_frozen_smoke(ns, url, destination):
    """Entry point inside frozen NOP.exe; use the exact application Downloader."""
    import yt_dlp
    report = Path(destination)
    report.parent.mkdir(parents=True, exist_ok=True)
    outcome = {"stage": "frozen-app", "ok": False,
               "yt_dlp": str(yt_dlp.version.__version__), "checks": []}
    try:
        import yt_dlp_ejs
        outcome["checks"].append("EJS package imported")
        if not getattr(sys, "frozen", False):
            raise RuntimeError("This check must run inside the compiled EXE")
        for name in ("deno", "ffmpeg", "ffprobe"):
            found = shutil.which(name)
            if not found or not Path(found).is_file():
                raise RuntimeError("Missing runtime executable: " + name)
            outcome["checks"].append(name + "=" + str(Path(found).name))
        normalized = ns["download_url"](url, "youtube", "single")
        with tempfile.TemporaryDirectory(prefix="nop-youtube-e2e-") as folder:
            worker = ns["Downloader"](normalized, 1, Path(folder), single_url=normalized,
                                      source="youtube", mode="both", vq="min", aq="best",
                                      container="mkv", parallel_videos=1, fragment_threads=1)
            worker._child_mode = True
            worker._run_job()
            outcome["finished"] = worker.finished_videos
            outcome["worker_error"] = ns["redact_diagnostic"](worker.error_text)
            outcome["failures"] = [ns["redact_diagnostic"](x) for x in worker._failed]
            downloads = [p for p in Path(folder).rglob("*") if p.is_file() and p.suffix.lower()
                         in {".mkv", ".mp4", ".webm", ".m4a", ".mp3"} and p.stat().st_size > 1024]
            if worker.finished_videos != 1 or not downloads:
                raise RuntimeError("NOP Downloader failed: {} {}".format(worker.error_text, worker._failed[:2]))
            # Probe actual playable output through the bundled ffprobe, not just file existence.
            probe = subprocess.run([shutil.which("ffprobe"), "-v", "error", "-show_entries", "format=duration",
                                    "-of", "default=noprint_wrappers=1:nokey=1", str(downloads[0])],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if probe.returncode or not probe.stdout.strip():
                raise RuntimeError("ffprobe cannot read the downloaded file")
            outcome["checks"].append("Application Downloader saved playable video through yt-dlp and FFmpeg")
        outcome["ok"] = True
        print("YOUTUBE END-TO-END PASS: actual frozen NOP Downloader saved playable video", flush=True)
        return 0
    except Exception as exc:
        outcome["error"] = ns["redact_diagnostic"](exc)
        outcome["trace"] = ns["redact_diagnostic"](traceback.format_exc())
        print("YOUTUBE END-TO-END FAILURE: " + outcome["error"], file=sys.stderr, flush=True)
        return 1
    finally:
        report.write_text(json.dumps(outcome, ensure_ascii=False, indent=2), encoding="utf-8")


def frozen():
    exe = ROOT / "dist" / "NOP" / "NOP.exe"
    report = ROOT / "build" / "youtube-frozen_test.json"
    if not exe.is_file():
        raise FileNotFoundError("Missing compiled EXE: " + str(exe))
    if report.is_file():
        report.unlink()
    env = dict(os.environ)
    for key in list(env):
        if key.upper().startswith(("QT_", "QML", "_PYI_", "PYTHON")):
            env.pop(key, None)
    env["QT_QPA_PLATFORM"] = "offscreen"
    # Real installer payload paths; do not accidentally use system Deno/ffmpeg.
    env["PATH"] = str(exe.parent) + os.pathsep + str(exe.parent / "bin") + os.pathsep + str(Path(env.get("SystemRoot", r"C:\Windows")) / "System32")
    print("YouTube frozen EXE check (real transfer; test media removed afterward)...", flush=True)
    result = subprocess.run([str(exe), "--nop-youtube-check", _test_url(), str(report)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace", env=env,
        timeout=240, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    print((result.stdout or "")[-3500:], flush=True)
    if not report.is_file():
        raise RuntimeError("EXE produced no YouTube report; exit code " + str(result.returncode))
    data = json.loads(report.read_text(encoding="utf-8"))
    if result.returncode or not data.get("ok"):
        raise RuntimeError("YouTube EXE end-to-end test failed: " + str(data.get("error") or data.get("failures") or result.returncode))
    return 0


if __name__ == "__main__":
    try:
        mode = sys.argv[1] if len(sys.argv) > 1 else ""
        if mode == "preflight":
            sys.exit(preflight())
        if mode == "legacy-report":
            sys.exit(legacy_report())
        if mode == "frozen":
            sys.exit(frozen())
        raise ValueError("Usage: youtube_stage_test.py preflight|frozen|legacy-report")
    except Exception as error:
        print("YOUTUBE STAGE FAILED:", error, file=sys.stderr)
        sys.exit(1)
