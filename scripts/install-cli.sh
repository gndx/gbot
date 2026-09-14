#!/usr/bin/env bash
# Install a user-local launcher bound to this checkout's Python environment.
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  echo "Usage: $0 [BIN_DIRECTORY]"
  echo "Default: ~/.local/bin. Requires .venv with Python 3.10 or newer."
  exit 0
fi
if [[ "$#" -gt 1 ]]; then echo "Usage: $0 [BIN_DIRECTORY]" >&2; exit 2; fi
python="$PWD/.venv/bin/python"
if [[ ! -x "$python" ]]; then
  echo "Missing .venv/bin/python. Create .venv with Python >=3.10 and install requirements.txt." >&2
  exit 1
fi
"$python" - "$PWD/cli/gbot" "${1:-$HOME/.local/bin}" <<'PY'
from pathlib import Path
import shlex
import sys

if sys.version_info < (3, 10):
    raise SystemExit("GBOT requires Python 3.10 or newer. Recreate .venv with a supported Python.")
source = Path(sys.argv[1]).absolute()
if not source.is_file():
    raise SystemExit("Cannot locate the GBOT CLI: " + str(source))
destination = Path(sys.argv[2]).expanduser().absolute()
destination.mkdir(parents=True, exist_ok=True)
launcher = destination / "gbot"
# Unlink a previous symlink before writing; never overwrite its target.
if launcher.is_symlink():
    launcher.unlink()
launcher.write_text("#!/bin/sh\nexec %s %s \"$@\"\n" %
                    (shlex.quote(sys.executable), shlex.quote(str(source))), encoding="utf-8")
launcher.chmod(0o755)
print("Installed: " + str(launcher))
print("Keep this checkout and its .venv in place; rerun this installer if you move it.")
print("If needed, add the directory to your shell PATH:")
print("  export PATH=" + shlex.quote(str(destination)) + ':"$PATH"')
PY
