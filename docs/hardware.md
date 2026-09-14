# Reference hardware

GBOT targets the **Waveshare RP2040-LCD-1.28**, non-touch variant. Waveshare
documents the RP2040 MCU, 264 KB SRAM, 2 MB flash, 240 × 240 GC9A01A LCD,
QMI8658 IMU, USB-C connector, and BOOT/RESET buttons in the
[official board wiki](https://www.waveshare.com/wiki/RP2040-LCD-1.28).

## Pin map used by the firmware

The following is the map implemented in `firmware/gc9a01.py` and
`firmware/sensors.py`. Check it against the
[official schematic](https://files.waveshare.com/upload/6/60/RP2040-LCD-1.28-sch.pdf)
before adapting the project to a different board revision.

| Function | Pin or interface |
| --- | --- |
| LCD SPI | SPI1 |
| LCD clock | GP10 |
| LCD MOSI | GP11 |
| LCD chip select | GP9 |
| LCD data/command | GP8 |
| LCD reset | GP12 |
| LCD backlight PWM | GP25 |
| IMU bus | I2C1 at 400 kHz |
| IMU SDA / SCL | GP6 / GP7 |
| QMI8658 address | `0x6B` |
| Supply-voltage sense | GP29 / ADC |
| RP2040 chip temperature | Internal ADC4 |
| BOOT button | `rp2.bootsel_button()` |
| RESET button | Hardware RUN/reset line |

## Display and memory assumptions

The driver uses RGB565 color, panel-specific initialization, and four
GC9A01A rotation settings. The default SPI request is 62.5 MHz; actual
throughput depends on the port and hardware. It uses a byte-swapped RGB565
representation so framebuffer bytes match the panel's expected order.

UI coordinates, eye positions, dashboard spacing, and circular cropping
assume 240 × 240 pixels. Changing just `WIDTH` and `HEIGHT` does not complete
a port to another display. A full RGB565 framebuffer at this resolution is
115,200 bytes, so the implementation uses bands/rows and shared drawing
buffers. Large dashboard modules are compiled on the host to reduce startup
memory pressure.

The BOOT button is not a normal GPIO input on this RP2040 design. Firmware
polls the MicroPython `rp2` helper between display operations. RESET cannot
be repurposed as a second software-readable button.

The sensor layer initializes the QMI8658 with a reset before configuring
the accelerometer. When motion data is unavailable, animation and USB
commands can continue without gesture control. ADC voltage and internal
chip temperature are approximate telemetry, not calibrated instruments.

## Power and standalone use

USB provides power and the host data link. The board can continue showing
its face and responding to the button while powered without a computer,
but it cannot fetch fresh online data. GBOT does not implement Wi-Fi or a
network configuration flow for this board.

For battery wiring, connector polarity, and charging requirements, follow
the manufacturer's documentation for your exact revision. This project
does not supply a battery-management or fuel-gauge implementation.

## Official references

- [Waveshare board wiki and examples](https://www.waveshare.com/wiki/RP2040-LCD-1.28)
- [Waveshare schematic PDF](https://files.waveshare.com/upload/6/60/RP2040-LCD-1.28-sch.pdf)
- [MicroPython firmware for Raspberry Pi Pico](https://micropython.org/download/RPI_PICO/)
- [MicroPython RP2 quick reference](https://docs.micropython.org/en/latest/rp2/quickref.html)
- [MicroPython mpremote](https://docs.micropython.org/en/latest/reference/mpremote.html)
- [MicroPython bytecode compatibility](https://docs.micropython.org/en/latest/reference/mpyfiles.html)
- [Raspberry Pi microcontroller documentation](https://www.raspberrypi.com/documentation/microcontrollers/)

The `latest` MicroPython documentation may describe development features;
select the installed release when checking an API change.
