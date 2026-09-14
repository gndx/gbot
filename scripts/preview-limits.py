#!/usr/bin/env python3
"""Render the actual MicroPython limits screen on a desktop, without hardware.

Requires Pillow. Run: python3 scripts/preview-limits.py --output artifacts/gbot-limits
The native PNGs are exactly 240 x 240, RGB565-quantized, with a circular panel
mask. Contact sheets use nearest-neighbour enlargement. No alternate UI is
drawn here: firmware/limits.py controls the layout, text, colors and animation.

The framebuffer rasterizers and 8x8 font below are adapted from MicroPython:
https://github.com/micropython/micropython/blob/master/extmod/modframebuf.c
https://github.com/micropython/micropython/blob/master/extmod/font_petme128_8x8.h

Copyright (c) 2013, 2014, 2016 Damien P. George

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
"""

import argparse
import ast
import hashlib
import importlib.util
import inspect
import json
import sys
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RGB565 = 1
MONO_VLSB = 0
MONO_HLSB = 3
MONO_HMSB = 4

# Original MicroPython PETME128 bitmap, ASCII 32..127, columns LSB at top.
_FONT = bytes.fromhex("""
00000000000000000000004f4f0000000007070000070700147f7f14147f7f14
00242e6b6b3a1200006333180c66630000327f4d4d7772500000000406030100
00001c3e63410000000041633e1c0000082a3e1c1c3e2a080008083e3e080800
000080e0600000000008080808080800000000606000000000406030180c0602
003e7f49457f3e000040447f7f40400000627351494f460000226349497f3600
00181814167f7f1000276745457d3900003e7f49497b3200000303797d070300
00367f49497f360000266f49497f3e000000002424000000000080e464000000
00081c3663414100001414141414140000414163361c080000020351590f0600
003e7f414d4f2e00007c7e0b0b7e7c00007f7f49497f3600003e7f4141632200
007f7f41633e1c00007f7f4949414100007f7f0909010100003e7f41497b3a00
007f7f08087f7f000000417f7f410000002060417f3f0100007f7f1c36634100
007f7f4040404000007f7f060c067f7f007f7f0e1c7f7f00003e7f41417f3e00
007f7f09090f0600001e3f21617f5e00007f7f19396f460000266f49497b3200
0001017f7f010100003f7f40407f3f00001f3f60603f1f00007f7f3018307f7f
0063771c1c77630000070f78780f0700006171594d47430000007f7f41410000
0002060c18306040000041417f7f000000080c06060c0800c0c0c0c0c0c0c0c0
000001030604000000207454547c7800007f7f44447c380000387c44446c2800
00387c44447f7f0000387c54545c580000087e7f090302000098bca4a4fc7c00
007f7f04047c78000000007d7d0000000040c08080fd7d00007f7f30386c4400
0000417f7f400000007c7c1830187c7c007c7c04047c780000387c44447c3800
00fcfc24243c180000183c2424fcfc00007c7c04040c080000485c5454742000
04043f7f44642000003c7c40407c3c00001c3c60603c1c00001c7c3018307c1c
00446c38386c4400009cbca0a0fc7c00004464745c4c44000008083e77414100
000000ffff000000004141773e0808000002030103020301aa55aa55aa55aa55
""")


class FrameBuffer:
    """Subset of framebuf used by the real display renderer; clips every write."""

    def __init__(self, buf, width, height, fmt, stride=None):
        self.buf = memoryview(buf).cast("B")
        self.width, self.height, self.fmt = width, height, fmt
        self.stride = width if stride is None else stride
        if fmt in (MONO_HLSB, MONO_HMSB):
            self.stride = (self.stride + 7) & ~7
        if fmt == RGB565:
            required = ((height - 1) * self.stride + width) * 2
        elif fmt in (MONO_HLSB, MONO_HMSB):
            required = ((height - 1) * self.stride + width + 7) // 8
        elif fmt == MONO_VLSB:
            required = ((height + 7) // 8 - 1) * self.stride + width
        else:
            raise ValueError("Unsupported framebuffer format: %s" % fmt)
        if len(self.buf) < required:
            raise ValueError("Framebuffer buffer too short")

    def pixel(self, x, y, color=None):
        if not (0 <= x < self.width and 0 <= y < self.height):
            return None
        if self.fmt == RGB565:
            offset = (y * self.stride + x) * 2
            if color is None:
                return self.buf[offset] | (self.buf[offset + 1] << 8)
            self.buf[offset] = color & 255
            self.buf[offset + 1] = color >> 8
            return None
        if self.fmt == MONO_VLSB:
            offset, bit = (y // 8) * self.stride + x, y & 7
        else:
            offset, bit = (y * self.stride + x) // 8, x & 7
            if self.fmt == MONO_HLSB:
                bit = 7 - bit
        if color is None:
            return (self.buf[offset] >> bit) & 1
        self.buf[offset] = ((self.buf[offset] & ~(1 << bit)) |
                            (bool(color) << bit))
        return None

    def fill(self, color):
        self.fill_rect(0, 0, self.width, self.height, color)

    def fill_rect(self, x, y, width, height, color):
        if width <= 0 or height <= 0:
            return
        x1, y1 = min(self.width, x + width), min(self.height, y + height)
        x, y = max(0, x), max(0, y)
        if x >= x1 or y >= y1:
            return
        if self.fmt == RGB565:
            row = bytes((color & 255, color >> 8)) * (x1 - x)
            for yy in range(y, y1):
                start = (yy * self.stride + x) * 2
                self.buf[start:start + len(row)] = row
        else:
            for yy in range(y, y1):
                for xx in range(x, x1):
                    self.pixel(xx, yy, color)

    def hline(self, x, y, width, color):
        self.fill_rect(x, y, width, 1, color)

    def vline(self, x, y, height, color):
        self.fill_rect(x, y, 1, height, color)

    def rect(self, x, y, width, height, color, fill=False):
        if fill:
            self.fill_rect(x, y, width, height, color)
            return
        self.hline(x, y, width, color)
        self.hline(x, y + height - 1, width, color)
        self.vline(x, y, height, color)
        self.vline(x + width - 1, y, height, color)

    def line(self, x1, y1, x2, y2, color):
        dx, dy = abs(x2 - x1), abs(y2 - y1)
        sx, sy = (1 if x2 > x1 else -1), (1 if y2 > y1 else -1)
        steep = dy > dx
        if steep:
            x1, y1, dx, dy, sx, sy = y1, x1, dy, dx, sy, sx
        error = 2 * dy - dx
        for _ in range(dx):
            self.pixel(y1, x1, color) if steep else self.pixel(x1, y1, color)
            while error >= 0:
                y1 += sy
                error -= 2 * dx
            x1 += sx
            error += 2 * dy
        self.pixel(x2, y2, color)

    def ellipse(self, cx, cy, rx, ry, color, fill=False, mask=15):
        def points(x, y):
            for quadrant, xx, yy in ((1, cx, cy - y), (2, cx - x, cy - y),
                                     (4, cx - x, cy + y), (8, cx, cy + y)):
                if not mask & quadrant:
                    continue
                if fill:
                    self.hline(xx, yy, x + 1, color)
                else:
                    self.pixel(xx + (x if quadrant in (1, 8) else 0), yy, color)

        if rx == 0 and ry == 0:
            if mask & 15:
                self.pixel(cx, cy, color)
            return
        a2, b2 = 2 * rx * rx, 2 * ry * ry
        x, y, xc, yc, error = rx, 0, ry * ry * (1 - 2 * rx), rx * rx, 0
        stopx, stopy = b2 * rx, 0
        while stopx >= stopy:
            points(x, y)
            y, stopy, error, yc = y + 1, stopy + a2, error + yc, yc + a2
            if 2 * error + xc > 0:
                x, stopx, error, xc = x - 1, stopx - b2, error + xc, xc + b2
        x, y, xc, yc, error = 0, ry, ry * ry, rx * rx * (1 - 2 * ry), 0
        stopx, stopy = 0, a2 * ry
        while stopx <= stopy:
            points(x, y)
            x, stopx, error, xc = x + 1, stopx + b2, error + xc, xc + b2
            if 2 * error + yc > 0:
                y, stopy, error, yc = y - 1, stopy - a2, error + yc, yc + a2

    def poly(self, x, y, coords, color, fill=False):
        vertices = list(zip(coords[::2], coords[1::2]))
        if not vertices:
            return
        if not fill:
            for p1, p2 in zip(vertices, vertices[1:] + vertices[:1]):
                self.line(x + p1[0], y + p1[1], x + p2[0], y + p2[1], color)
            return
        # int(a / b), unlike a // b, truncates toward zero just like C.
        for row in range(min(v[1] for v in vertices), max(v[1] for v in vertices) + 1):
            nodes = []
            px1, py1 = vertices[0]
            for px2, py2 in reversed(vertices):
                if py1 != py2 and ((py1 > row >= py2) or (py2 > row >= py1)):
                    node = int((32 * px1 + int(32 * (px2 - px1) *
                               (row - py1) / (py2 - py1)) + 16) / 32)
                    nodes.append(node)
                elif row == max(py1, py2):
                    if py1 < py2:
                        self.pixel(x + px2, y + py2, color)
                    elif py2 < py1:
                        self.pixel(x + px1, y + py1, color)
                    else:
                        self.line(x + px1, y + py1, x + px2, y + py2, color)
                px1, py1 = px2, py2
            nodes.sort()
            for a, b in zip(nodes[::2], nodes[1::2]):
                self.hline(x + a, y + row, b - a + 1, color)

    def text(self, value, x, y, color=1):
        for char in value.encode("utf-8"):
            char = char if 32 <= char <= 127 else 127
            for column in _FONT[(char - 32) * 8:(char - 31) * 8]:
                for bit in range(8):
                    if column & (1 << bit):
                        self.pixel(x, y + bit, color)
                x += 1

    def blit(self, source, x, y, key=-1, palette=None):
        if isinstance(source, (tuple, list)):
            source = FrameBuffer(*source)
        for yy in range(source.height):
            for xx in range(source.width):
                color = source.pixel(xx, yy)
                if palette is not None:
                    color = palette.pixel(color, 0)
                if color != key:
                    self.pixel(x + xx, y + yy, color)


class Clock:
    """Deterministic clock with the RP2040 ticks wraparound period."""

    period = 1 << 30

    def __init__(self):
        self.now = 1000

    def ticks_ms(self):
        return self.now % self.period

    def ticks_diff(self, a, b):
        return ((a - b + self.period // 2) % self.period) - self.period // 2

    def ticks_add(self, a, delta):
        if not -self.period // 2 <= delta < self.period // 2:
            raise OverflowError("ticks interval overflow")
        return (a + delta) % self.period

    def advance(self, ms):
        self.now += ms


class LCD:
    """Capture bytes that the real driver would transmit to the round LCD."""

    def __init__(self):
        self.data = bytearray(240 * 240 * 2)
        self.blits = []

    def blit(self, buf, x, y, width, height):
        if not (0 <= x <= x + width <= 240 and 0 <= y <= y + height <= 240):
            raise AssertionError("LCD blit outside physical 240x240 buffer")
        if len(buf) != width * height * 2:
            raise AssertionError("LCD blit buffer length mismatch")
        self.blits.append((x, y, width, height))
        for yy in range(height):
            start = ((y + yy) * 240 + x) * 2
            self.data[start:start + width * 2] = buf[yy * width * 2:(yy + 1) * width * 2]

    def image(self, circular=True):
        from PIL import Image, ImageDraw

        raw = bytearray(240 * 240 * 3)
        for i in range(240 * 240):
            # framebuf writes native LE; rgb565() swaps in advance for SPI BE.
            color = (self.data[2 * i] << 8) | self.data[2 * i + 1]
            r, g, b = (color >> 11) & 31, (color >> 5) & 63, color & 31
            raw[3 * i:3 * i + 3] = bytes(((r << 3) | (r >> 2),
                                          (g << 2) | (g >> 4),
                                          (b << 3) | (b >> 2)))
        image = Image.frombytes("RGB", (240, 240), bytes(raw))
        if circular:
            mask = Image.new("L", image.size)
            ImageDraw.Draw(mask).ellipse((0, 0, 239, 239), fill=255)
            image.putalpha(mask)
        return image


def install_shims(clock):
    module = types.ModuleType("framebuf")
    for name in ("FrameBuffer", "RGB565", "MONO_HLSB", "MONO_HMSB", "MONO_VLSB"):
        setattr(module, name, globals()[name])
    sys.modules["framebuf"] = module
    machine = types.ModuleType("machine")
    for name in ("Pin", "SPI", "PWM"):
        setattr(machine, name, type(name, (), {}))
    sys.modules["machine"] = machine
    for name in ("ticks_ms", "ticks_diff", "ticks_add"):
        setattr(time, name, getattr(clock, name))
    # Use the real shared seven-segment implementation for old firmware snapshots
    # without importing the rest of hud, face, sensors or their hardware globals.
    hud = types.ModuleType("hud")
    source = ast.parse((ROOT / "firmware/hud.py").read_text())
    selected = [node for node in source.body
                if (isinstance(node, ast.FunctionDef) and node.name == "seg_digit")
                or (isinstance(node, ast.Assign) and any(
                    isinstance(target, ast.Name) and target.id == "_DIGITS"
                    for target in node.targets))]
    exec(compile(ast.Module(body=selected, type_ignores=[]), "hud.py", "exec"), hud.__dict__)
    sys.modules["hud"] = hud
    sys.path.insert(0, str(ROOT / "firmware"))


def load_renderer(path):
    spec = importlib.util.spec_from_file_location("gbot_limits_preview", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def new_screen(renderer):
    lcd = LCD()
    band = bytearray(240 * 82 * 2)
    fb = FrameBuffer(band, 240, 82, RGB565)
    return renderer.Limits(lcd, band, fb), lcd


def configure(screen, brand, pct, stale=False, windows=2):
    for title in ("CLAUDE", "CODEX"):
        values = [("5H", pct, 9234), ("7D", min(100, pct + 8), 326877),
                  ("7DS", min(100, pct + 15), None)]
        screen.set(title, values[:windows])
    if brand not in ("CLAUDE", "CODEX"):
        screen.set(brand, [("WWWW", pct, 9234), ("MMMM", min(100, pct + 8), 326877),
                           ("8888", min(100, pct + 15), None)][:windows])
        screen.select("2")
    else:
        screen.select("0" if brand == "CLAUDE" else "1")
    if stale:
        screen.stale_all()


def contact_sheet(items, output, scale=2, columns=5):
    from PIL import Image, ImageDraw, ImageFont

    tile_w, tile_h = 240 * scale + 32, 240 * scale + 68
    rows = (len(items) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * tile_w, rows * tile_h), (11, 14, 18))
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default(size=16)
    for index, (label, image) in enumerate(items):
        x, y = (index % columns) * tile_w + 16, (index // columns) * tile_h + 16
        enlarged = image.resize((240 * scale, 240 * scale), Image.Resampling.NEAREST)
        sheet.paste(enlarged, (x, y), enlarged)
        draw.text((x + 240 * scale // 2, y + 240 * scale + 14), label,
                  fill=(186, 193, 204), anchor="mt", font=font)
    sheet.save(output)


def main():
    from PIL import Image

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/gbot-limits")
    parser.add_argument("--renderer", type=Path, default=ROOT / "firmware/limits.py")
    parser.add_argument("--settle-ms", type=int, default=640,
                        help="Time to finish entrance animation before PNG snapshots (default: 640)")
    parser.add_argument("--animation", action="store_true", help="Also export both providers as 4.8-second GIFs")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    clock = Clock()
    install_shims(clock)
    renderer = load_renderer(args.renderer)
    items, cases = [], []
    specifications = [(brand, pct, False, 2) for brand in ("CLAUDE", "CODEX")
                      for pct in (0, 10, 50, 96, 100)]
    specifications += [(brand, 50, True, 2) for brand in ("CLAUDE", "CODEX")]
    specifications += [("CLAUDE", 84, False, 3), ("CODEX", 96, False, 1),
                       (None, None, False, 0), ("WWWWWWWW", 100, False, 3),
                       ("GBOTAI123", 96, False, 3)]
    for brand, pct, stale, windows in specifications:
        screen, lcd = new_screen(renderer)
        if brand:
            configure(screen, brand, pct, stale, windows)
            name = "%s-%s" % (brand.lower(), "stale" if stale else "%03d" % pct)
            if windows != 2:
                name += "-%dwindows" % windows
            label = "%s / %s" % (brand, "NOT SYNCED" if stale else "%d%%" % pct)
        else:
            name, label = "empty", "NO DATA"
        screen.enter(None)
        # Render into one buffer as an independent oracle for clipped strips.
        full = bytearray(240 * 240 * 2)
        fb = FrameBuffer(full, 240, 240, RGB565)
        fb.fill(getattr(renderer, "_BG", getattr(renderer, "_BLACK", 0)))
        if len(inspect.signature(screen._render).parameters) == 3:
            screen._render(fb, 0, 240)
        else:
            screen._render(fb, 0)
        seam_match = full == lcd.data
        if not seam_match:
            raise AssertionError("Strip/full-frame mismatch: " + name)
        for elapsed in range(0, max(0, args.settle_ms), 64):
            clock.advance(min(64, args.settle_ms - elapsed))
            screen.tick()
        image = lcd.image()
        image.save(args.output / (name + ".png"))
        lcd.image(circular=False).save(args.output / (name + "-raw.png"))
        items.append((label, image))
        background = lcd.data[:2]
        clipped = sum(1 for y in range(240) for x in range(240)
                      if (x - 119.5) ** 2 + (y - 119.5) ** 2 > 120 ** 2
                      and lcd.data[(y * 240 + x) * 2:(y * 240 + x) * 2 + 2] != background)
        cases.append({"name": name, "strip_matches_full_frame": seam_match,
                      "content_pixels_outside_round_panel": clipped,
                      "blits": lcd.blits, "sha256": hashlib.sha256(lcd.data).hexdigest()})
    contact_sheet(items, args.output / "contact-sheet.png")
    contact_sheet([items[3], items[8]], args.output / "hero.png", scale=3, columns=2)
    if args.animation:
        for brand in ("CLAUDE", "CODEX"):
            screen, lcd = new_screen(renderer)
            configure(screen, brand, 96)
            screen.enter(None)
            frames = []
            for _ in range(75):
                im = lcd.image()
                base = Image.new("RGB", im.size, (11, 14, 18))
                base.paste(im, mask=im.getchannel("A"))
                frames.append(base.resize((480, 480), Image.Resampling.NEAREST))
                clock.advance(64)
                screen.tick()
            frames[0].save(args.output / (brand.lower() + "-animation.gif"),
                           save_all=True, append_images=frames[1:], duration=64, loop=0)
    font_path = ROOT / "firmware/limits_font.py"
    (args.output / "manifest.json").write_text(json.dumps({
        "renderer": str(args.renderer.resolve()),
        "renderer_sha256": hashlib.sha256(args.renderer.read_bytes()).hexdigest(),
        "font_sha256": (hashlib.sha256(font_path.read_bytes()).hexdigest()
                        if hasattr(renderer, "FONTS") else None),
        "settle_ms": args.settle_ms,
        "resolution": [240, 240], "pixel_format": "RGB565, SPI big endian",
        "cases": cases,
    }, indent=2) + "\n")
    print("Rendered %d cases; all strip boundaries match full-frame rendering." % len(cases))
    print(args.output / "contact-sheet.png")
    print(args.output / "hero.png")


if __name__ == "__main__":
    main()
