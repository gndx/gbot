# Adapt GBOT to another board with Claude or Codex

GBOT can be adapted with Claude Code or Codex as the coding assistant. Start
with the source and the target manufacturer's documentation; the assistant
can inspect assumptions, implement a driver, update layout, and prepare
deployment instructions. The target board still needs the correct runtime,
electrical connections, and hands-on validation.

The current release supplies one reference port: Waveshare RP2040-LCD-1.28,
non-touch. ESP32, RP2350, touch variants, and other displays are possible
adaptation targets, not already verified hardware configurations.

## Gather the target facts

Create a short hardware brief before asking for changes:

| Fact | Why it matters |
| --- | --- |
| Exact model and PCB revision | Similar product names can have different wiring |
| Official wiki, schematic, and pinout | Prevents guessed pins and voltage assumptions |
| MCU and MicroPython build | `rp2`, USB CDC, ADC, and boot APIs vary |
| LCD controller, resolution, and shape | Determines driver, color order, and layout |
| LCD SPI pins, reset, and backlight | Must match the physical board |
| Available RAM and flash | Determines buffer sizes and bytecode strategy |
| Buttons and touch controller | Changes input semantics and driver needs |
| IMU model and address | Determines whether gestures can work |
| Host OS and serial transport | The current CLI requires POSIX serial APIs |
| Power and ADC circuit | Voltage-divider and temperature formulas are hardware-specific |

Keep secrets out of the brief. Pinouts, public datasheets, and sanitized
error traces are enough for the assistant to work with.

## Recommended implementation order

1. **Boot the correct runtime.** Use the manufacturer's guidance for the
   target. Do not flash the RP2040 Pico UF2 onto a different MCU family.
2. **Bring up the display alone.** Draw solid red, green, and blue fields,
   a border, and orientation markers. Verify reset, backlight, byte order,
   addressing, clipping, and rotation on the real panel.
3. **Implement the display contract.** Replace or adapt `gc9a01.py` while
   keeping the drawing operations used by the existing UI. Reduce buffer
   sizes or SPI speed when needed.
4. **Adapt controls and telemetry.** Replace `rp2.bootsel_button()` on
   non-RP2 targets. Port the IMU or disable motion gestures explicitly.
   Revisit ADC and temperature calculations.
5. **Fit the face and dashboards.** Adjust coordinates, type sizes, safe
   circular margins, and rendering budgets. A new resolution affects more
   than the display constants.
6. **Retain the USB command boundary.** Keep the four states, `ok`/`err`
   replies, and core protocol compatible where possible. Add a new host
   transport only when the target requires one.
7. **Validate and document the port.** Run host checks, then verify cold
   boot, serial commands, controls, all views, timer behavior, and long-run
   stability on the target. Record the exact board and runtime versions.

For a larger contribution, introduce a board-specific configuration layer
instead of scattering new pin conditionals through the UI. Keep the
reference board working and document optional hardware features.

## Prompts you can use

### Assess feasibility

```text
Read AGENTS.md, docs/architecture.md, and docs/hardware.md in this GBOT repo.
Target: [exact board and revision]. Official sources: [links].

Compare the target with the current RP2040-LCD-1.28 port. List the concrete
changes needed for MicroPython, display transport, pins, framebuffer memory,
BOOT/button input, IMU, ADC, and USB serial. Cite the official source for
each pin assumption. Identify missing information instead of guessing.
Provide a minimal bring-up plan before adding optional integrations.
```

### Implement a port

```text
Implement the GBOT port described in [hardware brief]. Preserve the four
availability states, animation behavior where practical, and USB protocol.
Keep online providers and credentials on the host. Make unsupported sensors
degrade cleanly. Update the deployment instructions for this MCU and runtime.
Run relevant host tests and compile checks. Report file changes, test results,
and a physical-device checklist, separating verified from unverified behavior.
```

### Change the display layout

```text
Adapt GBOT's face and dashboards to [resolution, shape, and controller].
Use the target display contract in [file]. Preserve readable labels and safe
margins. Budget framebuffer memory explicitly, update previews, and inspect
them for clipping. Provide commands to exercise every view on the board and
do not claim hardware validation from a desktop preview.
```

### Debug a real device result

```text
Target: [board], runtime: [version], revision: [commit].
Expected: [specific behavior]. Actual: [observation].
Evidence: [sanitized status/traceback and screen photo].

Trace this case through GBOT. Make the smallest relevant fix, run its host
regression checks, and prepare explicit deployment and readback commands.
Explain what I should observe on-device to confirm the issue is resolved.
```

AI assistance can handle substantial coding work. It cannot establish
electrical compatibility from an ambiguous product name or confirm the
physical display without evidence from that device. Include that evidence
when proposing a new supported-board entry.
