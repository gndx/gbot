#!/usr/bin/env python3
"""Render GBOT's actual eyes, status rings and center cards without a board.

Run: python3 scripts/preview-cards.py --output artifacts/gbot-cards
Requires Pillow for PNG exports only; the regression tests require stdlib.
All pixels come from firmware/face.py, backdrop.py and limits.py. The desktop
adapter executes the same Viper integer arithmetic as Python and captures the
real backdrop's SPI stream. It does not approximate eyes or draw a mockup.
"""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import random
import sys
import types


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("gbot_card_base_preview", ROOT / "scripts/preview-limits.py")
base = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(base)


class LCD(base.LCD):
    """Capture both partial blits and backdrop.paint_full's actual SPI writes."""

    def __init__(self):
        super().__init__()
        self.spi = self
        self._data_mode = False
        self._selected = False
        self._window = (0, 0, 240, 240)
        self._cursor = 0
        self.brightness = 1.0

    def window(self, x, y, width, height):
        self._window = (x, y, width, height)
        self._cursor = 0

    def cs(self, value):
        self._selected = value == 0

    def dc(self, value):
        self._data_mode = value != 0

    def write(self, data):
        if not self._selected:
            raise AssertionError("SPI write while LCD is deselected")
        if not self._data_mode:
            if data != b"\x2c":
                raise AssertionError("Unexpected command in backdrop SPI stream")
            return
        x, y, width, height = self._window
        if self._cursor + len(data) > width * height * 2:
            raise AssertionError("SPI stream exceeds LCD window")
        for offset in range(0, len(data), 2):
            pixel = (self._cursor + offset) // 2
            row, column = divmod(pixel, width)
            destination = ((y + row) * 240 + x + column) * 2
            self.data[destination:destination + 2] = data[offset:offset + 2]
        self._cursor += len(data)

    def backlight(self, value):
        self.brightness = value


def load_module(name, path, pointers=False):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    if pointers:
        # Viper only uses pointer annotations here; the body indexes arrays.
        module.ptr32 = object
        module.ptr16 = object
    spec.loader.exec_module(module)
    return module


def environment(clock=None):
    clock = clock or base.Clock()
    base.install_shims(clock)
    micropython = types.ModuleType("micropython")
    micropython.viper = lambda function: function
    micropython.native = lambda function: function
    micropython.const = lambda value: value
    sys.modules["micropython"] = micropython
    face = load_module("gbot_card_preview_face", ROOT / "firmware/face.py", pointers=True)
    palette = load_module("gbot_card_preview_palette", ROOT / "firmware/palette.py")
    renderer = base.load_renderer(ROOT / "firmware/limits.py")
    return clock, face, palette, renderer


def setup(state="await", modules=None):
    clock, face_module, palette, renderer = modules or environment()
    random.seed(42)
    lcd = LCD()
    face = face_module.Face(lcd, palette.STATES, palette.EXPRESSIONS, state)
    pose(face, face.mood, clock)
    screen = renderer.Limits(lcd, face.band, face.fb)
    return clock, face, screen, lcd


def pose(face, mood, clock):
    """Set a firmware expression for a deterministic, open-eye screenshot."""
    face.mood = mood
    face.tgt = face.exprs[mood]
    face.blink = [0.0, 0.0]
    face.gx = face.gy = 0.0
    for i in (0, 1):
        face.cur[i] = dict(face._target(i, 0.0))
    face._draw(clock.ticks_ms())


def outside_band(data, face_module=None):
    """Exact byte oracle for pixels which neither eyes nor cards may change."""
    if face_module is None:
        x, y, width, height = 32, 60, 176, 112
    else:
        x, y, width, height = (face_module.BAND_X, face_module.BAND_Y,
                               face_module.BAND_W, face_module.BAND_H)
    output = bytearray()
    for row in range(240):
        start = row * 240 * 2
        if y <= row < y + height:
            output.extend(data[start:start + x * 2])
            output.extend(data[start + (x + width) * 2:start + 240 * 2])
        else:
            output.extend(data[start:start + 240 * 2])
    return bytes(output)


def sample_data(screen, percent=84):
    screen.set("CLAUDE", [("5H", percent, 9234), ("7D", min(100, percent + 8), 326877)])
    screen.set("CODEX", [("5H", percent, 2400), ("7D", min(100, percent + 5), 326877)])
    screen.set_weather(256, 3, 68, 1788976800)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/gbot-cards")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    modules = environment()
    items, hero, cases, eyes = [], [], [], []
    for state in ("open", "await", "hold", "busy"):
        clock, face, screen, lcd = setup(state, modules)
        baseline = outside_band(lcd.data, modules[1])
        eye_image = lcd.image()
        eye_image.save(args.output / (state + "-eyes.png"))
        items.append((state.upper() + " / eyes", eye_image))
        for mood in face.pal["exprs"]:
            pose(face, mood, clock)
            if outside_band(lcd.data, modules[1]) != baseline:
                raise AssertionError("Eye pose changed state ring: " + mood)
            image = lcd.image()
            image.save(args.output / (state + "-" + mood + ".png"))
            eyes.append((state.upper() + " / " + mood, image))
        for kind, percent in (("CLAUDE", 10), ("CLAUDE", 100),
                              ("CODEX", 10), ("CODEX", 100), ("WEATHER", 84)):
            sample_data(screen, percent)
            lcd.blits.clear()
            screen.enter_card(kind, face.pal)
            clock.advance(640)
            screen.tick_card()
            ring_matches = outside_band(lcd.data, modules[1]) == baseline
            if not ring_matches:
                raise AssertionError("Card changed pixels outside eyes: " + kind)
            name = "%s-%s-%03d" % (state, kind.lower(), percent)
            image = lcd.image()
            image.save(args.output / (name + ".png"))
            label = "%s / %s %s" % (state.upper(), kind,
                                      "26 C" if kind == "WEATHER" else "%d%%" % percent)
            items.append((label, image))
            cases.append({"name": name, "status_ring_unchanged": ring_matches,
                          "blits": list(lcd.blits),
                          "sha256": hashlib.sha256(lcd.data).hexdigest()})
            if state == "await" and (kind == "WEATHER" or percent == 100):
                hero.append((label, image))
            screen.leave_card()
        if state == "await":
            hero.insert(0, ("GBOT / animated eyes", eye_image))
    base.contact_sheet(items, args.output / "contact-sheet.png", columns=6)
    base.contact_sheet(eyes, args.output / "expressions.png", columns=6)
    base.contact_sheet(hero, args.output / "hero.png", columns=4)
    (args.output / "manifest.json").write_text(json.dumps({
        "description": "Actual firmware renderer with SPI/framebuf desktop capture",
        "resolution": [240, 240], "card_band": [32, 60, 176, 112],
        "data": "Sample usage and weather for visual regression; not a live reading",
        "sources": {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in (ROOT / "firmware/limits.py", ROOT / "firmware/limits_font.py",
                                 ROOT / "firmware/face.py",
                                 ROOT / "firmware/backdrop.py", ROOT / "firmware/palette.py")},
        "cases": cases,
    }, indent=2) + "\n")
    print("Rendered %d cards and %d expressions; status rings match byte for byte." %
          (len(cases), len(eyes)))
    print(args.output / "hero.png")


if __name__ == "__main__":
    main()
