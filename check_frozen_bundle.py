"""Run the actual frozen EXE with a system-only PATH before compiling Setup.exe."""
import json
import os
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parent
report = root / "build" / "bundle-self-test.json"
report.parent.mkdir(parents=True, exist_ok=True)
report.unlink(missing_ok=True)
environment = {key: value for key, value in os.environ.items()
               if not key.upper().startswith(("PYTHON", "QT_", "QML", "_PYI_"))}
windows = Path(os.environ["WINDIR"])
environment["PATH"] = os.pathsep.join((str(windows / "System32"), str(windows)))
environment["QT_FORCE_STDERR_LOGGING"] = "1"
native_log = root / "build" / "bundle-native-output.log"
try:
    with native_log.open("wb") as output:
        process = subprocess.run([str(root / "dist" / "NOP" / "NOP.exe"), "--nop-bundle-check", str(report)],
                                 cwd=str(root / "dist" / "NOP"), env=environment, timeout=480,
                                 stdout=output, stderr=subprocess.STDOUT)
except subprocess.TimeoutExpired:
    raise SystemExit("Frozen EXE check timed out. Details: " + str(report) + " / " + str(native_log))
if not report.is_file():
    raise SystemExit(f"Frozen EXE could not start (exit {process.returncode}, 0x{process.returncode & 0xFFFFFFFF:08X}). Native log: {native_log}")
result = json.loads(report.read_text(encoding="utf-8"))
for check in result.get("checks", []):
    print(("OK  " if check["ok"] else "FAIL") + " " + check["name"] + ": " + check["detail"])
if process.returncode or not result.get("ok"):
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit("Frozen bundle self-test failed. Report: " + str(report))
print("Frozen bundle self-test passed without a system Python or developer PATH.")
