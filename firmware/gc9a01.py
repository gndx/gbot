"""GC9A01A driver for the Waveshare RP2040-LCD-1.28 (240x240 round LCD).

Fixed board wiring:
    SCK=GP10  MOSI=GP11  CS=GP9  DC=GP8  RST=GP12  BL=GP25

The initialization register values follow the manufacturer reference sequence.
See THIRD_PARTY_NOTICES.md and the Waveshare board documentation."""

from machine import Pin, SPI, PWM
import time

WIDTH = 240
HEIGHT = 240

# MADCTL values for 0, 90, 180, and 270 degrees. Bit 0x08 selects BGR,
# which matches this panel.
ROTATIONS = (0x48, 0x28, 0x88, 0xE8)

# GC9A01A manufacturer initialization sequence. Registers 0x84..0x98
# are internal; keep the reference values and ordering.
_INIT = (
    (0xEF, None),
    (0xEB, b"\x14"),
    (0xFE, None),
    (0xEF, None),
    (0xEB, b"\x14"),
    (0x84, b"\x40"),
    (0x85, b"\xff"),
    (0x86, b"\xff"),
    (0x87, b"\xff"),
    (0x88, b"\x0a"),
    (0x89, b"\x21"),
    (0x8a, b"\x00"),
    (0x8b, b"\x80"),
    (0x8c, b"\x01"),
    (0x8d, b"\x01"),
    (0x8e, b"\xff"),
    (0x8f, b"\xff"),
    (0xb6, b"\x00\x00"),
    (0x36, bytes([ROTATIONS[0]])),
    (0x3a, b"\x55"),  # RGB565
    (0x90, b"\x08\x08\x08\x08"),
    (0xbd, b"\x06"),
    (0xbc, b"\x00"),
    (0xff, b"\x60\x01\x04"),
    (0xc3, b"\x13"),
    (0xc4, b"\x13"),
    (0xc9, b"\x22"),
    (0xbe, b"\x11"),
    (0xe1, b"\x10\x0e"),
    (0xdf, b"\x21\x0c\x02"),
    (0xf0, b"\x45\x09\x08\x08\x26\x2a"),
    (0xf1, b"\x43\x70\x72\x36\x37\x6f"),
    (0xf2, b"\x45\x09\x08\x08\x26\x2a"),
    (0xf3, b"\x43\x70\x72\x36\x37\x6f"),
    (0xed, b"\x1b\x0b"),
    (0xae, b"\x77"),
    (0xcd, b"\x63"),
    (0x70, b"\x07\x07\x04\x0e\x0f\x09\x07\x08\x03"),
    (0xe8, b"\x34"),
    (0x62, b"\x18\x0d\x71\xed\x70\x70\x18\x0f\x71\xef\x70\x70"),
    (0x63, b"\x18\x11\x71\xf1\x70\x70\x18\x13\x71\xf3\x70\x70"),
    (0x64, b"\x28\x29\xf1\x01\xf1\x00\x07"),
    (0x66, b"\x3c\x00\xcd\x67\x45\x45\x10\x00\x00\x00"),
    (0x67, b"\x00\x3c\x00\x00\x00\x01\x54\x10\x32\x98"),
    (0x74, b"\x10\x85\x80\x00\x00\x4e\x00"),
    (0x98, b"\x3e\x07"),
    (0x35, None),
    (0x21, None),  # inversion ON, required for this panel
)


def rgb565(r, g, b):
    """Pack RGB into the byte-swapped integer used by framebuf.RGB565.

    framebuf stores native little-endian pixels, while the panel expects
    big-endian SPI bytes. All firmware colors use this swapped representation."""
    c = (r & 0xF8) << 8 | (g & 0xFC) << 3 | b >> 3
    return ((c & 0xFF) << 8) | (c >> 8)


def color_bytes(color):
    """Return the two SPI bytes for a color produced by rgb565()."""
    return bytes((color & 0xFF, color >> 8))


def mix(c1, c2, t):
    """Interpolate two (r, g, b) tuples: t=0 selects c1; t=1 selects c2."""
    if t <= 0:
        return c1
    if t >= 1:
        return c2
    return (
        int(c1[0] + (c2[0] - c1[0]) * t),
        int(c1[1] + (c2[1] - c1[1]) * t),
        int(c1[2] + (c2[2] - c1[2]) * t),
    )


class Display:
    def __init__(self, baudrate=62_500_000):
        self.spi = SPI(1, baudrate=baudrate, polarity=0, phase=0,
                       sck=Pin(10), mosi=Pin(11))
        self.cs = Pin(9, Pin.OUT, value=1)
        self.dc = Pin(8, Pin.OUT, value=0)
        self.rst = Pin(12, Pin.OUT, value=1)
        self.bl = PWM(Pin(25))
        self.bl.freq(2000)
        self.bl.duty_u16(0)
        self._level = 0.0
        self._rotation = 0
        self._line = bytearray(WIDTH * 2)
        self.reset()
        self.init()

    # ---- transport ----

    def _cmd(self, cmd, data=None):
        self.cs(0)
        self.dc(0)
        self.spi.write(bytes((cmd,)))
        if data:
            self.dc(1)
            self.spi.write(data)
        self.cs(1)

    def reset(self):
        self.rst(1)
        time.sleep_ms(10)
        self.rst(0)
        time.sleep_ms(20)
        self.rst(1)
        time.sleep_ms(120)

    def init(self):
        for cmd, data in _INIT:
            self._cmd(cmd, data)
        self._cmd(0x11)  # sleep out
        time.sleep_ms(120)
        self._cmd(0x29)  # display on
        time.sleep_ms(20)

    def rotation(self, n):
        """Rotate in 90-degree steps to match the board mounting orientation."""
        self._rotation = n % 4
        self._cmd(0x36, bytes((ROTATIONS[self._rotation],)))

    @property
    def rot(self):
        return self._rotation

    def window(self, x, y, w, h):
        x2 = x + w - 1
        y2 = y + h - 1
        self._cmd(0x2A, bytes((x >> 8, x & 0xFF, x2 >> 8, x2 & 0xFF)))
        self._cmd(0x2B, bytes((y >> 8, y & 0xFF, y2 >> 8, y2 & 0xFF)))

    def blit(self, buf, x, y, w, h):
        """Transfer an RGB565 buffer into a display rectangle."""
        self.window(x, y, w, h)
        self.cs(0)
        self.dc(0)
        self.spi.write(b"\x2c")
        self.dc(1)
        self.spi.write(buf)
        self.cs(1)

    def row(self, y, buf):
        self.blit(buf, 0, y, WIDTH, 1)

    def fill(self, color):
        line = self._line
        line[:] = color_bytes(color) * WIDTH
        self.window(0, 0, WIDTH, HEIGHT)
        self.cs(0)
        self.dc(0)
        self.spi.write(b"\x2c")
        self.dc(1)
        for _ in range(HEIGHT):
            self.spi.write(line)
        self.cs(1)

    # ---- backlight ----

    def backlight(self, level):
        """Set brightness from 0.0 to 1.0 with gamma correction for smooth fades."""
        if level < 0.0:
            level = 0.0
        elif level > 1.0:
            level = 1.0
        self._level = level
        self.bl.duty_u16(int(65535 * level * level))

    @property
    def level(self):
        return self._level

    def sleep(self):
        self.backlight(0.0)
        self._cmd(0x28)  # display off
        self._cmd(0x10)  # sleep in

    def wake(self):
        self._cmd(0x11)
        time.sleep_ms(120)
        self._cmd(0x29)
