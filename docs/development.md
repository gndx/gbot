# Development and validation

## Local checks

Use Python 3.10+ and a virtual environment:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python cli/gbot --help
```

The unit tests use fake hardware, time, serial responses, and provider
responses. They cover command behavior, view transitions, countdowns,
provider retry handling, weather/TRM validation, and calendar scheduling
without requiring your personal credentials or a connected board.

Run the existing suite after changes to protocol or scheduling behavior.
Add a focused regression test when fixing a behavior that can fail again;
avoid tests that merely restate constants or implementation syntax.

## Desktop previews and fonts

The preview scripts exercise rendering with host-side substitutes. Install
the development dependencies before running them:

```sh
.venv/bin/python scripts/preview-limits.py --help
.venv/bin/python scripts/preview-cards.py --help
.venv/bin/python scripts/preview-dashboards.py --help
```

Use their output options to save previews outside the source tree or into an
ignored local directory. Inspect text contrast, clipping, baselines, and
circular margins. A preview does not reproduce physical SPI throughput,
LCD color calibration, backlight, viewing angle, or MicroPython memory use.

Font generation and Inter attribution are documented in
[fonts/README.md](../fonts/README.md). `firmware/limits_font.py` is generated;
change the generator or its inputs rather than hand-editing bitmap runs.
Retain the upstream font license when redistributing derived assets.

## Device validation

Always state the exact firmware revision, board model/revision, MicroPython
version, and deployment port with device evidence. Stop the feed and other
serial clients before deployment:

```sh
./scripts/deploy.sh /path/to/gbot-port --verify
gbot --device /path/to/gbot-port ping
gbot --device /path/to/gbot-port status
```

Then validate the behavior relevant to the change:

- Cold boot shows the face; all four states have the correct colors.
- Short and long BOOT presses follow separate paths; RESET restarts cleanly.
- All four rotations fit the visible circular area without clipped content.
- Brightness, sleep, wake, and return-to-face behavior work on the display.
- HUD telemetry is plausible; a real tap/shake is distinct from a USB
  `press` command test.
- Every changed dashboard has readable text, expected units, and correct
  handling of missing or stale data.
- A reset countdown longer than the platform's tick range does not overflow.
- A Calendar reminder appears at the intended lead time, can be dismissed,
  returns to the prior face/state, and does not repeat during the same run.
- Reconnecting USB allows the feed to resume; power cycling preserves
  availability/rotation without inventing fresh usage countdowns.

Capture a photo or video for visible UI changes. A successful compile,
readback, ping, or FPS report alone does not prove visual correctness.
Avoid publishing real meeting names, account identifiers, or credentials in
that evidence.

## What a validation report should say

Use concrete distinctions:

```text
Host: test suite passed on [OS / Python version].
Build: bytecode compiled with [mpy-cross version].
Transfer: files verified by readback on [board / port].
Device: [specific views and controls observed], MicroPython [version].
Not verified: [other operating systems, physical controls, or other boards].
```

If no board was flashed during the change, say so. This standalone GBOT
extraction inherits the original HEX implementation, but its own device
validation must be recorded independently.
