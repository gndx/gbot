#!/usr/bin/env bash
# Install the optional per-user macOS USB feeder. No sudo is required.
# Usage: ./scripts/install-feed.sh /dev/cu.usbmodem...
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  echo "Usage: $0 SERIAL_PORT (macOS only; installs and starts a user LaunchAgent)"
  exit 0
fi
if [[ "$#" -ne 1 || "$1" != /* ]]; then
  echo "Usage: $0 SERIAL_PORT" >&2
  exit 2
fi
if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "The optional background feeder installer requires macOS." >&2
  echo "On Linux, run gbot --device SERIAL_PORT feed --watch 60 in a terminal." >&2
  exit 1
fi
if [[ ! -x .venv/bin/python ]]; then
  echo "Create .venv and install requirements.txt first." >&2
  exit 1
fi

.venv/bin/python - "$PWD/cli/gbot" "$1" <<'PY'
import os
from pathlib import Path
import plistlib
import subprocess
import sys

label = "com.gndx.gbot.feed"
cli = Path(sys.argv[1]).resolve()
# Preserve .venv's interpreter path: resolving its symlink can lose the venv.
python = Path(sys.executable).absolute()
if sys.version_info < (3, 10):
    raise SystemExit("GBOT requires Python 3.10 or newer.")
if not cli.is_file() or not python.is_file():
    raise SystemExit("The CLI or Python is missing; the service was not installed.")
agents = Path.home() / "Library" / "LaunchAgents"
logs = Path.home() / "Library" / "Logs" / "gbot"
agents.mkdir(parents=True, exist_ok=True)
logs.mkdir(parents=True, exist_ok=True, mode=0o700)
plist = agents / (label + ".plist")
args = [str(python), str(cli), "feed", "--watch", "60"]
if sys.argv[2]:
    args.extend(["--device", sys.argv[2]])
settings = {
    "Label": label,
    "ProgramArguments": args,
    "RunAtLoad": True,
    "KeepAlive": True,
    "ThrottleInterval": 30,
    "ProcessType": "Background",
    "EnvironmentVariables": {"PYTHONUNBUFFERED": "1"},
    "StandardOutPath": str(logs / "feed.log"),
    "StandardErrorPath": str(logs / "feed-error.log"),
}
with plist.open("wb") as output:
    plistlib.dump(settings, output)
plist.chmod(0o600)
domain = "gui/%d" % os.getuid()
subprocess.run(["/bin/launchctl", "bootout", domain + "/" + label],
               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
subprocess.run(["/bin/launchctl", "bootstrap", domain, str(plist)], check=True)
print("GBOT feeder started: usage and enabled calendar every 60 seconds; weather every 10 minutes; TRM hourly.")
print("LaunchAgent: " + str(plist))
print("Log: " + str(logs / "feed.log"))
print("Stop with: launchctl bootout " + domain + "/" + label)
PY
