"""Face background: a status ring surrounding a black center.

Draw concentric circles from largest to smallest. Half-pixel radial samples
and two-pixel edge gradients reduce visible stair steps without a costly
per-pixel antialiasing pass. This background is painted only when the state
or view changes.

Cache each circle's row widths because radii do not depend on the palette.
Collapse constant-color spans and duplicate RGB565 colors. Draw spans using
framebuf.hline, avoiding Python slices and temporary per-row allocations.
The eye band fits wholly inside the black center, allowing its renderer to
use fast C-backed framebuf primitives."""

import framebuf
import math
from array import array
from gc9a01 import rgb565, mix

CX = 120
CY = 120

# Radial ring profile from outside to inside. Each segment contains
# outer radius, inner radius, starting color, and ending color.
# Interpolate colors; radii are measured in display pixels.
#
# Keep two black pixels at the edge so the physical bezel does not
# clip the ring.
_MARGIN = 118.0
_INNER = 108.0     # black inside this radius: the eye band lives here

_BLACK = (0, 0, 0)
_STEP = 0.5        # profile sampling interval in pixels


def _profile(pal):
    """Return radial profile segments: (outer_r, inner_r, outer_rgb, inner_rgb)."""
    ring = pal["ring"]
    glow = pal["glow"]
    return (
        (118.0, 116.5, _BLACK, glow),     # outer edge fades in from black
        (116.5, 115.5, glow, glow),       # highlight accent line
        (115.5, 114.0, glow, ring),       # transition to the main ring
        (114.0, 110.0, ring, ring),       # main ring
        (110.0, 108.0, ring, _BLACK),     # inner edge fades toward black
    )


_span_key = None
_span_table = None


def _spans(radii):
    """Cache each circle's half-width on each row.

    Radii are palette-independent, so all states share this table. A value of -1
    marks rows outside a circle."""
    global _span_key, _span_table
    if _span_key == radii:
        return _span_table
    n = len(radii)
    table = array("h", [0] * (240 * n))
    for y in range(240):
        dy2 = (y - CY) ** 2
        base = y * n
        for k in range(n):
            r = radii[k]
            v = r * r - dy2
            table[base + k] = int(math.sqrt(v)) if v > 0 else -1
    _span_key = radii
    _span_table = table
    return table


def build(pal):
    """Return (radii, colors) from largest radius to smallest.

    Use one circle per distinct color, sample gradients at half-pixel intervals,
    and remove duplicate RGB565 values before paint_full overwrites the circles."""
    radii = []
    colors = []
    last = 0            # Rows start black, so an initial black circle adds nothing.
    for r_out, r_in, c_out, c_in in _profile(pal):
        span = r_out - r_in
        if c_out == c_in or span <= 0:
            samples = ((r_out, c_out),)
        else:
            samples = tuple((r_out - k * _STEP,
                             mix(c_out, c_in, k * _STEP / span))
                            for k in range(int(span / _STEP)))
        for r, c in samples:
            v = rgb565(*c)
            if v == last:
                continue
            last = v
            radii.append(r)
            colors.append(v)
    if last != 0:
        radii.append(_INNER)
        colors.append(0)
    return (tuple(radii), tuple(colors))


def paint_full(lcd, circles):
    """Paint the full display one row at a time without a full framebuffer.

    Each 240x1 row is drawn with C-backed hline and transferred over SPI."""
    radii, colors = circles
    n = len(radii)
    table = _spans(radii)
    line = bytearray(240 * 2)
    fb = framebuf.FrameBuffer(line, 240, 1, framebuf.RGB565)
    lcd.window(0, 0, 240, 240)
    lcd.cs(0)
    lcd.dc(0)
    lcd.spi.write(b"\x2c")
    lcd.dc(1)
    for y in range(240):
        fb.fill(0)
        base = y * n
        for k in range(n):
            half = table[base + k]
            if half > 0:
                fb.hline(CX - half, 0, half + half, colors[k])
        lcd.spi.write(line)
    lcd.cs(1)
