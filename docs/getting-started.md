# Getting started

## 1. Check the hardware

Use the **Waveshare RP2040-LCD-1.28**, non-touch model, and a USB-C data cable.
Compare your board with the
[Waveshare wiki](https://www.waveshare.com/wiki/RP2040-LCD-1.28).
Similarly named touch and RP2350 boards can have different hardware.
The onboard LCD and IMU are already wired; no external display wiring is
needed for this reference board.

The host CLI and shell scripts target macOS and Linux. Windows requires a
separate serial/installer port. Apple's optional Calendar reader requires
macOS 14+ and Apple's Command Line Tools (`xcode-select --install`).

## 2. Install the host tools

From a checkout of this repository:

```sh
python3 --version            # Must be 3.10 or newer
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
./scripts/install-cli.sh
```

The requirements pin `mpremote`, `mpy-cross`, and `pyserial`. The CLI itself
uses Python's standard library; `mpremote` manages board deployment and the
REPL. The installer places `gbot` in `~/.local/bin` and ties it to this
checkout's virtual environment. Follow its `PATH` message when needed.

You can also run the CLI without installing it:

```sh
.venv/bin/python cli/gbot --help
```

## 3. Put MicroPython on the board

The build baseline is **MicroPython 1.29.0 for Raspberry Pi Pico** and the
matching compiler pinned in `requirements.txt`. Download the release UF2
from the [official Pico page](https://micropython.org/download/RPI_PICO/).
Do not use a Pico W, Pico 2, CircuitPython, or preview image as a substitute.

1. Disconnect USB.
2. Hold the board's BOOT button while reconnecting USB, then release it.
3. Find the `RPI-RP2` removable drive.
4. Copy the downloaded UF2 to that drive.

The board resets after the copy. This is the
[official MicroPython UF2 installation procedure](https://micropython.org/download/RPI_PICO/).
The helper script accepts both paths explicitly:

```sh
# macOS example. Substitute the actual downloaded filename.
./scripts/flash.sh "$HOME/Downloads/RPI_PICO-v1.29.0.uf2" /Volumes/RPI-RP2

# On Linux, the drive is often mounted below /media/<user>/RPI-RP2.
```

The script does not choose a drive or download firmware for you. Flashing
installs the MicroPython runtime; the next step installs GBOT. Save any files
from a previously programmed board before replacing its software.

## 4. Find the USB serial port and deploy GBOT

```sh
gbot devices
```

Typical names are `/dev/cu.usbmodem...` on macOS and `/dev/ttyACM0` on Linux.
The list contains candidates: identify your board by comparing it before
and after reconnecting that board. Use an explicit port for deployment:

```sh
./scripts/deploy.sh /dev/cu.usbmodemXXXX --verify
```

The script builds bytecode on the host, transfers the firmware, and restarts
the board. `--verify` reads transferred files back for comparison. This is a
file-transfer check; you must still inspect the screen and exercise controls.
Large dashboard modules use `.mpy` bytecode to avoid compiling their source
within the RP2040's limited RAM. Keep the compiler and runtime versions
compatible when upgrading; see
[MicroPython's bytecode format documentation](https://docs.micropython.org/en/latest/reference/mpyfiles.html).

Stop any running `gbot ... --watch` process or background feed before
deployment, and close other serial monitors. The CLI coordinates its own
serial access, but an external REPL or deployment tool can still contend for
the port.

## 5. Verify the first run

```sh
gbot --device /dev/cu.usbmodemXXXX ping
gbot --device /dev/cu.usbmodemXXXX open
gbot --device /dev/cu.usbmodemXXXX status
gbot --device /dev/cu.usbmodemXXXX rotate 2
gbot --device /dev/cu.usbmodemXXXX limits --demo
gbot --device /dev/cu.usbmodemXXXX face
```

Confirm that the board displays animated eyes, turns green for `open`, rotates
correctly, and renders the demo without clipping. Try a short BOOT press and
a long press, then reconnect power and check that availability and rotation
are restored. The screen starts on the face after reboot.

Remove demo values before displaying real data:

```sh
gbot limits --clear
```

After a successful connection the CLI remembers the device path under
`~/.config/gbot/`. Use `--device` whenever selecting a particular board matters.
Continue with the [command reference](usage.md) and optional
[integrations](integrations.md).

## Troubleshooting

| Symptom | Check or recovery |
| --- | --- |
| No removable drive | Hold BOOT while connecting; try a known data cable and another USB port |
| No serial candidate | The board may still be in bootloader mode; finish flashing, wait, and list again |
| Linux permission denied | Check ownership and your distribution's serial-device group/udev policy; use normal user access instead of running GBOT as root |
| Port busy or command timeout | Stop the feed/watch command and close `mpremote`, Thonny, or another serial monitor |
| Black or dark screen | Try `gbot wake` and `gbot bright 70`; confirm the exact board and complete deployment |
| Incompatible `.mpy` or `MemoryError` | Recheck the MicroPython/compiler pair and redeploy the compiled dashboard modules |
| Eyes are sideways | Set `gbot rotate 0`, `1`, `2`, or `3` for your enclosure |
| Usage values look old | Run a fresh provider command; saved percentages are not a live provider response |
| Calendar authorization fails | Re-run `gbot calendar connect`; check macOS Privacy & Security → Calendars for GBOT Calendar |

To inspect the MicroPython REPL:

```sh
./scripts/console.sh /dev/cu.usbmodemXXXX
```

Ctrl-C interrupts the firmware. At the REPL, `import sys; print(sys.version)`
shows the runtime version. Ctrl-D soft-resets it. Exit `mpremote` with Ctrl-]
before trying the CLI. See the
[official mpremote reference](https://docs.micropython.org/en/latest/reference/mpremote.html)
for recovery and filesystem commands.

## Updating and removing the host installation

To update, stop the feed, pull the desired release, reinstall requirements,
then deploy to the explicit port with `--verify`. Review release notes before
changing MicroPython itself.

The installed CLI entry is `~/.local/bin/gbot`. Remove that entry to uninstall
the command; remove the checkout only after stopping any service that refers
to it. Optional Calendar/feed locations and their removal instructions are
listed in [integrations](integrations.md#background-feed-on-macos).
