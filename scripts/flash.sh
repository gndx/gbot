#!/usr/bin/env bash
# Install a user-supplied RP2040 MicroPython UF2 on an explicit BOOTSEL volume.
set -euo pipefail

usage() {
  echo "Usage: $0 MICROPYTHON.uf2 BOOTSEL_MOUNT"
  echo "macOS example: $0 ~/Downloads/RPI_PICO-v1.29.0.uf2 /Volumes/RPI-RP2"
  echo "Linux example: $0 ~/Downloads/RPI_PICO-v1.29.0.uf2 /media/\$USER/RPI-RP2"
  echo "Hold BOOTSEL while connecting USB; pass the mounted RPI-RP2 volume."
}
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then usage; exit 0; fi
if [[ "$#" -ne 2 ]]; then usage >&2; exit 2; fi
uf2="$1"
mount_dir="$2"
if [[ ! -f "$uf2" || ! -d "$mount_dir" ]]; then
  echo "Provide an existing UF2 file and a mounted BOOTSEL directory." >&2
  exit 1
fi

# Validate both the selected volume and every block's RP2040 family marker.
# A UF2 filename alone does not identify its target chip.
python3 - "$uf2" "$mount_dir" <<'PY'
from pathlib import Path
import struct
import sys

source, target = map(Path, sys.argv[1:])
try:
    info = (target / "INFO_UF2.TXT").read_text(encoding="utf-8")
except OSError as error:
    raise SystemExit("The selected directory is not a readable BOOTSEL volume: " + str(error))
if "Board-ID: RPI-RP2" not in info:
    raise SystemExit("Expected an RPI-RP2 BOOTSEL volume; refusing the selected target.")
data = source.read_bytes()
if not data or len(data) % 512:
    raise SystemExit("Invalid UF2 file length; expected complete 512-byte blocks.")
count = len(data) // 512
for index in range(count):
    block = data[index * 512:(index + 1) * 512]
    magic0, magic1, flags, address, size, number, total, family = struct.unpack_from("<8I", block)
    end_magic, = struct.unpack_from("<I", block, 508)
    if (magic0, magic1, end_magic) != (0x0A324655, 0x9E5D5157, 0x0AB16F30):
        raise SystemExit("Invalid UF2 magic in block %d." % index)
    if not flags & 0x2000 or family != 0xE48BFF56:
        raise SystemExit("The UF2 is not marked for RP2040; refusing to flash it.")
    if size > 476 or number != index or total != count:
        raise SystemExit("Invalid UF2 block metadata in block %d." % index)
print("Validated RP2040 UF2: " + str(source))
PY

echo "Flashing $uf2 to $mount_dir"
if ! cp "$uf2" "$mount_dir/"; then
  echo "The copy failed. The board may have disconnected; verify it before retrying." >&2
  exit 1
fi
echo "UF2 copied. The board should restart and leave BOOTSEL mode."
echo "List serial ports with gbot devices, then deploy using an explicit port."
