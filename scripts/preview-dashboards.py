#!/usr/bin/env python3
"""Export GBOT's full dashboards separately from its brief cards inside eyes.

Run: python3 scripts/preview-dashboards.py --output artifacts/gbot-dashboards
Requires Pillow. Layout, fonts, colors and bytes come from the actual
MicroPython renderer, not from a desktop imitation. Values are sample data.
"""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


base = module("gbot_dashboard_base", ROOT / "scripts/preview-limits.py")
cards = module("gbot_dashboard_cards", ROOT / "scripts/preview-cards.py")


def setup():
    clock = base.Clock()
    base.install_shims(clock)
    renderer = base.load_renderer(ROOT / "firmware/limits.py")
    screen, lcd = base.new_screen(renderer)
    return clock, renderer, screen, lcd


def settle(clock, screen, weather=False):
    tick = screen.tick_weather if weather else screen.tick
    for _ in range(10):
        clock.advance(64)
        tick()


def provider(brand, percent=96):
    clock, renderer, screen, lcd = setup()
    base.configure(screen, brand, percent)
    screen.enter(None)
    settle(clock, screen)
    return clock, renderer, screen, lcd


def weather(temp=256, code=3, humidity=68, stale=False, empty=False):
    clock, renderer, screen, lcd = setup()
    if not empty:
        screen.set_weather(temp, code, humidity, 1788976800)
    if stale:
        clock.advance(901000)
    screen.enter_weather(None)
    settle(clock, screen, weather=True)
    return clock, renderer, screen, lcd


def trm(cents=311647, stale=False, empty=False):
    clock, renderer, screen, lcd = setup()
    if not empty:
        screen.set_trm(cents, 20260909, 20260909, 86400)
    if stale:
        clock.advance(86401000)
    screen.enter_trm(None)
    return clock, renderer, screen, lcd


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/gbot-dashboards")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    hero, overview, records = [], [], []

    def capture(name, label, lcd, destination):
        image = lcd.image()
        image.save(args.output / (name + ".png"))
        lcd.image(circular=False).save(args.output / (name + "-raw.png"))
        destination.append((label, image))
        records.append({"name": name, "sha256": hashlib.sha256(lcd.data).hexdigest(),
                        "blits": list(lcd.blits)})
        return image

    for brand in ("CLAUDE", "CODEX"):
        _, _, _, lcd = provider(brand)
        capture(brand.lower() + "-full", brand + " / full dashboard", lcd, hero)
    _, _, _, lcd = weather()
    capture("weather-full", "MEDELLIN / full dashboard", lcd, hero)
    _, _, _, lcd = trm()
    capture("trm-full", "TRM / full dashboard", lcd, hero)
    base.contact_sheet(hero, args.output / "hero.png", scale=2, columns=4)
    trm_cases = []
    for name, settings in (("current", {}), ("stale", {"stale": True}),
                           ("empty", {"empty": True})):
        _, _, _, lcd = trm(**settings)
        capture("trm-" + name, "TRM / " + name, lcd, trm_cases)
    base.contact_sheet(trm_cases, args.output / "trm-cases.png", columns=3)

    for name, settings in (("cloudy", {}), ("sunny", {"code": 0, "temp": 285, "humidity": 52}),
                           ("rain", {"code": 63, "temp": 198, "humidity": 92}),
                           ("stale", {"stale": True}), ("empty", {"empty": True})):
        _, _, _, lcd = weather(**settings)
        capture("weather-" + name, "MEDELLIN / " + name, lcd, overview)
    base.contact_sheet(overview, args.output / "weather-cases.png", columns=5)

    # The automatic face cycle inserts compact usage and fresh weather cards.
    mini = []
    modules = cards.environment()
    clock, face, screen, lcd = cards.setup("await", modules)
    cards.sample_data(screen, 20)
    ring = cards.outside_band(lcd.data)
    capture("eyes", "45 s / animated eyes", lcd, mini)
    for brand in ("CLAUDE", "CODEX", "WEATHER"):
        screen.enter_card(brand, face.pal)
        if cards.outside_band(lcd.data) != ring:
            raise AssertionError("Automatic card changed status ring")
        capture(brand.lower() + "-mini", "8 s / " + brand, lcd, mini)
        screen.leave_card()
    base.contact_sheet(mini, args.output / "mini-cards.png", scale=2, columns=4)

    (args.output / "manifest.json").write_text(json.dumps({
        "renderer": str(ROOT / "firmware/limits.py"),
        "renderer_sha256": hashlib.sha256((ROOT / "firmware/limits.py").read_bytes()).hexdigest(),
        "resolution": [240, 240], "pixel_format": "RGB565, SPI big endian",
        "data": "Sample values for visual review, not live readings",
        "full_views": "Manual dashboards return to the previous face after 60 seconds",
        "mini_cards": "Claude, Codex and Medellin; 8 seconds after 45 seconds of eyes",
        "cases": records,
    }, indent=2) + "\n")
    print("Full dashboards: " + str(args.output / "hero.png"))
    print("Automatic cards: " + str(args.output / "mini-cards.png"))


if __name__ == "__main__":
    main()
