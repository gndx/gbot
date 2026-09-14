#!/usr/bin/env bash
# Build the optional macOS calendar reader; authorize with gbot calendar connect.
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  echo "Usage: $0 (macOS 14+, Xcode Command Line Tools and .venv required)"
  exit 0
fi
if [[ "$#" -ne 0 ]]; then echo "Usage: $0" >&2; exit 2; fi
if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "The optional Calendar integration requires macOS 14 or newer." >&2
  exit 1
fi
if [[ ! -x .venv/bin/python ]]; then
  echo "Create .venv and install requirements.txt first." >&2
  exit 1
fi
if ! command -v xcrun >/dev/null || ! command -v codesign >/dev/null; then
  echo "Install Xcode Command Line Tools with: xcode-select --install" >&2
  exit 1
fi
.venv/bin/python - "$PWD/host/CalendarReader.swift" <<'PY'
from pathlib import Path
import platform
import plistlib
import subprocess
import sys

if sys.version_info < (3, 10):
    raise SystemExit('GBOT requires Python 3.10 or newer.')
if int(platform.mac_ver()[0].split('.')[0]) < 14:
    raise SystemExit('The optional Calendar integration requires macOS 14 or newer.')
app = Path.home() / 'Applications/GBOT Calendar.app'
contents = app / 'Contents'
binary = contents / 'MacOS/gbot-calendar'
binary.parent.mkdir(parents=True, exist_ok=True)
info = contents / 'Info.plist'
description = 'GBOT reads your next meeting to show a reminder on your board five minutes before it starts. It does not modify events.'
info.write_bytes(plistlib.dumps({
    'CFBundleIdentifier': 'com.gndx.gbot.calendar',
    'CFBundleName': 'GBOT Calendar',
    'CFBundleDisplayName': 'GBOT Calendar',
    'CFBundleExecutable': 'gbot-calendar',
    'CFBundlePackageType': 'APPL',
    'CFBundleVersion': '1',
    'CFBundleShortVersionString': '1.0',
    'LSMinimumSystemVersion': '14.0',
    'LSUIElement': True,
    'NSCalendarsFullAccessUsageDescription': description,
    'NSCalendarsUsageDescription': description,
}))
subprocess.run(['xcrun', 'swiftc', '-O', '-target', platform.machine() + '-apple-macosx14.0',
                '-framework', 'EventKit', sys.argv[1], '-o', str(binary),
                '-Xlinker', '-sectcreate', '-Xlinker', '__TEXT',
                '-Xlinker', '__info_plist', '-Xlinker', str(info)], check=True)
subprocess.run(['codesign', '--force', '--sign', '-', str(app)], check=True)
print('GBOT Calendar reader installed: ' + str(app))
print('Run gbot calendar connect to grant Calendar access.')
PY
