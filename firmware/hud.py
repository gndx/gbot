"""System view showing locally measured board diagnostics.

Share the face framebuffer and redraw its central band; the state ring and
header are painted only on entry. Large values use rectangle-based seven
segment digits because the built-in 8x8 framebuf font is too small."""

import framebuf
import math
import time

import backdrop
from face import BAND_X, BAND_Y, BAND_W, BAND_H
from gc9a01 import rgb565, mix

_BLACK = 0
_WHITE = rgb565(255, 255, 255)
_GREY = rgb565(120, 130, 145)
_DIM = rgb565(52, 58, 70)

# Active segments for each digit, ordered a b c d e f g.
_DIGITS = (
    0b1111110,  # 0
    0b0110000,  # 1
    0b1101101,  # 2
    0b1111001,  # 3
    0b0110011,  # 4
    0b1011011,  # 5
    0b1011111,  # 6
    0b1110000,  # 7
    0b1111111,  # 8
    0b1111011,  # 9
)


# ---- shared drawing primitives ----
# limits.py also uses these functions, avoiding a Hud instance
# when only a digit is needed.


def seg_digit(fb, x, y, w, h, t, value, col, off):
    """Draw a seven-segment digit with its top-left corner at (x, y).

    A value of None leaves the cell blank, suppressing leading zeroes."""
    if value is None:
        return
    on = _DIGITS[value]
    half = (h - t) // 2
    # a, d, g: horizontal
    fb.fill_rect(x + t, y, w - 2 * t, t, col if on & 0b1000000 else off)
    fb.fill_rect(x + t, y + h - t, w - 2 * t, t, col if on & 0b0001000 else off)
    fb.fill_rect(x + t, y + half, w - 2 * t, t, col if on & 0b0000001 else off)
    # f, b, e, c: vertical
    fb.fill_rect(x, y + t, t, half - t, col if on & 0b0000010 else off)
    fb.fill_rect(x + w - t, y + t, t, half - t, col if on & 0b0100000 else off)
    fb.fill_rect(x, y + half + t, t, half - t, col if on & 0b0000100 else off)
    fb.fill_rect(x + w - t, y + half + t, t, half - t,
                 col if on & 0b0010000 else off)


def meter(fb, x, y, w, h, frac, color, track):
    """Draw a horizontal capsule track with a left-anchored fill.

    The rounded fill endpoint indicates the value by length; color reinforces it."""
    r = h // 2
    fb.fill_rect(x + r, y, w - 2 * r, h, track)
    fb.ellipse(x + r, y + r, r, r, track, True)
    fb.ellipse(x + w - r - 1, y + r, r, r, track, True)
    if frac <= 0.01:
        return
    if frac > 1.0:
        frac = 1.0
    fill = int((w - 2 * r) * frac)
    fb.ellipse(x + r, y + r, r, r, color, True)
    if fill:
        fb.fill_rect(x + r, y, fill, h, color)
    fb.ellipse(x + r + fill, y + r, r, r, color, True)


class Hud:
    def __init__(self, lcd, band, fb, sensors):
        self.lcd = lcd
        self.band = band
        self.fb = fb
        self.sensors = sensors
        self.pal = None
        self.started = time.ticks_ms()

    # ---- entry and background ----

    def enter(self, pal):
        """Paint the background and header when the view or state changes."""
        self.pal = pal
        self.accent = rgb565(*pal["ring"])
        self.soft = rgb565(*mix(pal["ring"], (0, 0, 0), 0.45))
        backdrop.paint_full(self.lcd, backdrop.build(pal))
        self._label()

    def _label(self):
        """Draw the top header outside the refreshed band."""
        strip = bytearray(120 * 10 * 2)
        fb = framebuf.FrameBuffer(strip, 120, 10, framebuf.RGB565)
        fb.fill(_BLACK)
        fb.text("GBOT", 34, 1, self.accent)
        self.lcd.blit(strip, 60, 44, 120, 10)

    # ---- drawing primitives ----

    def _seg_digit(self, x, y, w, h, t, value):
        seg_digit(self.fb, x, y, w, h, t, value, self.accent, _DIM)

    def _number(self, x, y, value, w=22, h=38, t=5):
        """Draw two integer digits, a decimal point, and one fractional digit."""
        v = int(round(value * 10))
        if v > 999:
            v = 999
        if v < 0:
            v = 0
        d = (v // 100, (v // 10) % 10, v % 10)
        self._seg_digit(x, y, w, h, t, d[0])
        self._seg_digit(x + w + 6, y, w, h, t, d[1])
        self.fb.fill_rect(x + 2 * w + 13, y + h - t, t, t, self.accent)
        self._seg_digit(x + 2 * w + 22, y, w, h, t, d[2])

    def _bar(self, x, y, w, h, frac, color):
        fb = self.fb
        fb.fill_rect(x, y, w, h, _DIM)
        fill = int(w * (0 if frac < 0 else (1 if frac > 1 else frac)))
        if fill:
            fb.fill_rect(x, y, fill, h, color)

    def _horizon(self, cx, cy, r, ax, ay):
        """Draw a horizon line tilted by the accelerometer."""
        fb = self.fb
        angle = math.atan2(ax, -ay if ay else 0.0001)
        if angle > 1.2:
            angle = 1.2
        elif angle < -1.2:
            angle = -1.2
        dx = int(r * math.cos(angle))
        dy = int(r * math.sin(angle))
        fb.line(cx - dx, cy - dy, cx + dx, cy + dy, self.accent)
        fb.line(cx - dx, cy - dy + 1, cx + dx, cy + dy + 1, self.soft)
        fb.ellipse(cx, cy, 3, 3, _WHITE, True)

    # ---- frame ----

    def tick(self, state, fps, free):
        import gc
        fb = self.fb
        fb.fill(_BLACK)

        temp = self.sensors.chip_temp()
        self._number(26, 2, temp)          # 88 px wide
        fb.ellipse(122, 8, 3, 3, _GREY, False)
        fb.text("C", 130, 4, _GREY)

        # Free memory relative to the RP2040 264 KB SRAM capacity.
        self._bar(18, 50, 140, 9, free / 264000.0, self.soft)
        fb.text("RAM %dK" % (free // 1024), 18, 63, _GREY)
        fb.text("%d FPS" % fps, 112, 63, _GREY)

        secs = time.ticks_diff(time.ticks_ms(), self.started) // 1000
        fb.text("UP %02d:%02d:%02d" % (secs // 3600, secs // 60 % 60, secs % 60),
                18, 77, _GREY)
        volts = self.sensors.voltage()
        if volts is not None:
            fb.text("%.2fV" % volts, 112, 77, _GREY)

        # State on the left and horizon on the right, without overlap.
        fb.text(state.upper(), 18, 96, self.accent)
        ax, ay, _ = self.sensors.accel()
        self._horizon(126, 98, 34, ax, ay)

        self.lcd.blit(self.band, BAND_X, BAND_Y, BAND_W, BAND_H)
