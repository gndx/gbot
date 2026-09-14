# Working on GBOT

GBOT is a standalone MicroPython desktop companion for the Waveshare
RP2040-LCD-1.28. Work within this repository. Do not assume access to or modify
the original HEX checkout, connected devices, host services, or personal
provider configuration as a side effect of local development.

## Read first

- `README.md` for installation and supported scope.
- `docs/architecture.md` for module boundaries and persistence.
- `docs/development.md` for validation expectations.
- `docs/porting.md` for another board or display.

## Implementation rules

- Keep user-facing documentation and new messages in English.
- Preserve the four states: `busy`, `hold`, `await`, and `open`.
- Keep credentials and network calls on the host. Send only normalized
  display data to the board. Never log or commit tokens or personal events.
- Treat the 240 × 240 layout, GC9A01A driver, RP2 BOOT API, and QMI8658 pins
  as board-specific assumptions. Use official references for changes.
- Keep memory use bounded. Compile large modules on the host with the
  pinned `mpy-cross`; do not assume CPython success proves MicroPython works.
- Use elapsed tick arithmetic for timers and remaining durations for long
  reset intervals. Do not construct arbitrary multi-day `ticks_add` targets.
- Preserve nonblocking serial polling and keep provider requests outside
  serial transactions in the feed/watch paths.
- Retain source and font license notices. See `THIRD_PARTY_NOTICES.md`.

## Validation and delivery

Run the appropriate host tests after behavior changes. Do not contact live
providers, read user credentials, install a background service, request
calendar access, or flash hardware as part of an ordinary test suite.
When device deployment is part of the task, use an explicit serial port and
the documented scripts, verify transferred bytes, and exercise the actual
changed view/control.

Distinguish host tests, bytecode compilation, transfer/readback, and physical
visual validation in the final report. A screenshot from a desktop preview
is not device evidence. Explain any remaining unverified hardware or OS
coverage. Avoid claiming support for a new board until its actual runtime,
display, controls, and serial link have been exercised.
