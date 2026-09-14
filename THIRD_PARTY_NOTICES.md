# Third-party notices

GBOT is distributed under the GNU Affero General Public License, version 3 or
later. See [LICENSE](LICENSE). The font data retains its separate SIL Open Font
License. The source references below were checked on September 14, 2026.

## Eye expression presets

The expression parameters in [`firmware/palette.py`](firmware/palette.py) are
adapted from [`EyePresets.h`](https://github.com/playfultechnology/esp32-eyes/blob/2738dbfc1e9876d1e9d9cd04e36669f5b12e9a92/EyePresets.h)
in [playfultechnology/esp32-eyes](https://github.com/playfultechnology/esp32-eyes),
at revision `2738dbfc1e9876d1e9d9cd04e36669f5b12e9a92`.

> Copyright (c) 2023 Alastair Aitchison, Playful Technology, 2020 Luis Llamas (www.luisllamas.es)

That source file grants redistribution and modification under the GNU Affero
General Public License, version 3 or, at the recipient's option, any later
version. It disclaims warranties, including merchantability and fitness for a
particular purpose. GBOT follows this file-specific notice.

The upstream repository's root `LICENSE` contains the GNU GPL version 3,
while `EyePresets.h` specifies the GNU **Affero** GPL version 3 or later. A copy
of the repository license is preserved for provenance in
[`licenses/esp32-eyes-GPL-3.0.txt`](licenses/esp32-eyes-GPL-3.0.txt); it does not
replace the file-specific AGPL notice for the adapted presets.

GBOT scales those parameters from the original 128x64 monochrome OLED to a
240x240 round RGB565 panel, maps eyelid slopes to mirrored eye rotation, and
adds a narrower right eye to the `skeptic` pose. The MicroPython drawing code
uses a different renderer built around `framebuf`, shared strip buffers, and
fixed-point Viper geometry. Changes for this public version include GBOT
branding and English source documentation and interface text.

The upstream project credits the Anki Cozmo robot as visual inspiration.
GBOT is an independent project and is not endorsed by those projects or brands.

## Inter font data

[`firmware/limits_font.py`](firmware/limits_font.py) contains a generated bitmap
subset of [Inter](https://github.com/rsms/inter), based on revision
`353b61b9f4430d5f420d56605a6e7993e0941470`.

Copyright (c) 2016 The Inter Project Authors.

The font data is distributed under the SIL Open Font License 1.1. Its complete
notice and license are included in [`fonts/Inter-OFL.txt`](fonts/Inter-OFL.txt).
See [`fonts/README.md`](fonts/README.md) for source verification and regeneration.
Inter remains the name of the upstream font; GBOT does not rename the bitmap
subset as an upstream font release.

## Waveshare hardware reference

The pin assignments and GC9A01A initialization register values in
[`firmware/gc9a01.py`](firmware/gc9a01.py) follow the Waveshare
[RP2040-LCD-1.28 documentation](https://www.waveshare.com/wiki/RP2040-LCD-1.28)
and its [manufacturer demo archive](https://files.waveshare.com/upload/9/9d/RP2040-LCD-1.28.zip).

Relevant reference files in that archive are
`RP2040-LCD-1.28/Python/RP2040-LCD-1.28/RP2040-LCD-1.28.py` and
`RP2040-LCD-1.28/c/lib/LCD/LCD_1in28.c`. The C reference identifies its author
as the **Waveshare team**, version 1.0, dated December 16, 2020. GBOT expresses
the register sequence as a table and implements its own display transport and
buffer management. The manufacturer demo implementation is not bundled here.

The archive inspected for this release has SHA-256
`c9f31b9b2d1819589cd38b1b8cce7e87f0bccf43386ee77822ffc53b12491121`.
The Python reference has no license header and the archive contains no
standalone license file; this notice does not assign a license to Waveshare's
demo archive, documentation, datasheets, or hardware designs.

## External runtimes and services

MicroPython, mpremote, mpy-cross, Python, Pillow, Apple EventKit, and the host
CLIs are separate dependencies with their own terms. Their implementations
are not vendored in this repository. Claude, Codex, Waveshare, and other
product names identify compatibility or documentation sources and do not
imply endorsement.
