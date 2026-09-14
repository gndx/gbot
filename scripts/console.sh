#!/usr/bin/env bash
# Open the selected board's MicroPython REPL. Press Ctrl-] to exit.
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  echo "Usage: $0 SERIAL_PORT (press Ctrl-] to exit the REPL)"
  exit 0
fi
if [[ "$#" -ne 1 || "$1" != /* ]]; then
  echo "Usage: $0 SERIAL_PORT" >&2
  exit 2
fi
if [[ ! -x .venv/bin/mpremote ]]; then
  echo "Missing .venv/bin/mpremote. Install requirements.txt in .venv first." >&2
  exit 1
fi
exec .venv/bin/mpremote connect "$1" repl
