#!/usr/bin/env bash
# Compile on the host, then copy GBOT firmware to an explicitly selected board.
set -euo pipefail
cd "$(dirname "$0")/.."

usage() {
  echo "Usage: $0 SERIAL_PORT [--verify]"
  echo "Example: $0 /dev/ttyACM0 --verify"
  echo "--verify reads every transferred file back and compares its bytes."
}
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then usage; exit 0; fi
if [[ "$#" -lt 1 || "$#" -gt 2 || "$1" != /* || ( "$#" -eq 2 && "$2" != "--verify" ) ]]; then
  usage >&2
  exit 2
fi
device="$1"
verify="${2:-}"
mpremote="$PWD/.venv/bin/mpremote"
mpy_cross="$PWD/.venv/bin/mpy-cross"
for executable in "$mpremote" "$mpy_cross"; do
  if [[ ! -x "$executable" ]]; then
    echo "Missing $executable. Create .venv and install requirements.txt first." >&2
    exit 1
  fi
done

build_dir="$(mktemp -d "${TMPDIR:-/tmp}/gbot-firmware.XXXXXX")"
trap 'rm -rf "$build_dir"' EXIT

# Validate all firmware before opening a port. Most modules stay readable .py
# files on the board. The large dashboard and font use bytecode to save RAM.
for source in firmware/*.py; do
  module="$(basename "$source" .py)"
  "$mpy_cross" -march=armv6m -msmall-int-bits=31 -s "$module.py" \
    -o "$build_dir/$module.mpy" "$source"
done

copy_file() {
  local source="$1" name attempt copied=0
  name="$(basename "$source")"
  echo "Copying $name"
  for attempt in 1 2 3; do
    if "$mpremote" connect "$device" fs cp "$source" ":$name"; then
      copied=1
      break
    fi
    if [[ "$attempt" -lt 3 ]]; then
      echo "Transfer failed; retrying $name ($attempt/3)." >&2
      sleep 2
    fi
  done
  if [[ "$copied" -ne 1 ]]; then
    echo "Could not copy $name. Deployment stopped; the board may contain a partial update." >&2
    exit 1
  fi
  if [[ "$verify" == "--verify" ]]; then
    "$mpremote" connect "$device" fs cp ":$name" "$build_dir/readback"
    if ! cmp -s "$source" "$build_dir/readback"; then
      echo "Readback mismatch for $name. Deployment stopped before reset." >&2
      exit 1
    fi
  fi
}

for source in firmware/*.py; do
  case "$(basename "$source")" in main.py|limits.py|limits_font.py) continue ;; esac
  copy_file "$source"
done
copy_file "$build_dir/limits_font.mpy"
copy_file "$build_dir/limits.mpy"
copy_file "fonts/Inter-OFL.txt"

# MicroPython chooses .py ahead of .mpy; remove old sources only after the
# compiled replacements have transferred. Ignore only a missing source file.
"$mpremote" connect "$device" exec $'import os\nfor path in ("limits.py", "limits_font.py"):\n    try:\n        os.remove(path)\n    except OSError as exc:\n        if exc.args[0] != 2:\n            raise'

# Install the entry point last to reduce the chance of booting missing modules.
# This is a multi-file deployment, not an atomic filesystem transaction.
copy_file "firmware/main.py"
"$mpremote" connect "$device" reset
echo "GBOT firmware deployed to $device${verify:+ with byte readback verification}."
