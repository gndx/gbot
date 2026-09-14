# SPDX-License-Identifier: AGPL-3.0-or-later
"""State palettes, eye expression presets, and personality.

The expression parameters are adapted from EyePresets.h in
playfultechnology/esp32-eyes, inspired by the Anki Cozmo robot.
Copyright (c) 2023 Alastair Aitchison, Playful Technology,
2020 Luis Llamas (www.luisllamas.es).
The source file specifies AGPL-3.0-or-later. See LICENSE and
THIRD_PARTY_NOTICES.md for its exact revision and inherited notices.

Original parameter names and values are preserved before scaling in _expr():
    Height Width Slope_Top Radius_Top Radius_Bottom OffsetX OffsetY
The original 128x64 monochrome OLED has 40-pixel eyes; this implementation
scales the presets for a 240x240 RGB565 round display using framebuf.

Width/Height size each eye. Top and bottom radii distinguish smiles from
frowns. Slope_Top becomes an atan(slope) rotation mirrored across the eyes,
OffsetX mirrors eye separation, and Inverse_Radius_Bottom forms a crescent
smile. The skeptic preset additionally narrows the right eye as noted below.
Each state randomly chooses from its own subset without immediate repeats."""

import math

DEFAULT = "await"

# Eye centers on the 240x240 display.
EYE_CX = (78.0, 162.0)
FACE_CY = 115.0

# The upstream presets use 40 px eyes on a 128x64 OLED. Scale to 60 px
# to fit the redrawn band. The widest awe pose and maximum gaze
# retain a small margin at the band edge.
#
_SCALE = 1.50


def _expr(h, w, rt, rb, slope=0.0, ox=0.0, oy=0.0, bite=0.0, breath=0.0):
    """Convert an upstream eye preset into a pose for each eye.

    Arguments retain upstream names and values. Rotation derives from slope and
    mirrors between the eyes, as does the horizontal offset."""
    rot = math.degrees(math.atan(slope))
    height = h * _SCALE
    out = []
    for i in (0, 1):
        sign = -1.0 if i == 0 else 1.0
        out.append({
            "w": w * _SCALE,
            "h": height,
            "rt": rt * _SCALE,
            "rb": rb * _SCALE,
            "rot": rot * -sign,
            "dx": ox * _SCALE * sign,
            "y": FACE_CY - height * 0.5 + oy * _SCALE,
            "bite": bite * _SCALE,
            "breath": breath,
        })
    return tuple(out)


EXPRESSIONS = {
    # ---- positive/available: green ----
    "happy":       _expr(h=10, w=40, rt=10, rb=0, breath=1),
    "glee":        _expr(h=8, w=40, rt=8, rb=0, bite=5, breath=1),
    "surprised":   _expr(h=45, w=45, rt=16, rb=16, ox=-2, breath=2),
    "awe":         _expr(h=35, w=45, rt=12, rb=12, slope=-0.1, ox=2, breath=2),

    # ---- neutral: blue ----
    "normal":      _expr(h=40, w=40, rt=8, rb=8, breath=2),
    "focused":     _expr(h=14, w=40, rt=3, rb=1, slope=0.2, breath=1),
    "skeptic":     _expr(h=40, w=40, rt=10, rb=10, breath=1),
    "sleepy":      _expr(h=14, w=40, rt=3, rb=3, slope=-0.5, oy=-2, breath=1),
    "suspicious":  _expr(h=22, w=40, rt=8, rb=3, breath=1),

    # ---- busy/in a meeting: yellow ----
    "annoyed":     _expr(h=12, w=40, rt=0, rb=10),
    "unimpressed": _expr(h=12, w=40, rt=1, rb=10, ox=3),
    "squint":      _expr(h=35, w=35, rt=8, rb=8, ox=-10, oy=-3, breath=1),
    "worried":     _expr(h=25, w=40, rt=6, rb=10, slope=-0.1, breath=1),
    "sad":         _expr(h=15, w=40, rt=1, rb=10, slope=-0.5),

    # ---- anger: red ----
    "angry":       _expr(h=20, w=40, rt=2, rb=12, slope=0.3, ox=-3, breath=1),
    "furious":     _expr(h=30, w=40, rt=2, rb=8, slope=0.4, ox=-2, breath=2),
    "frustrated":  _expr(h=12, w=40, rt=0, rb=10, ox=3, oy=-5),
    "scared":      _expr(h=40, w=40, rt=12, rb=8, slope=-0.1, ox=-3, breath=2),
}

# Upstream skeptic differs from normal by only two radius pixels.
# Narrow the right eye to make the skeptical expression visible.
# This is an intentional modification of the EyePresets.h values.
#
EXPRESSIONS["skeptic"][1]["h"] *= 0.45
EXPRESSIONS["skeptic"][1]["y"] += EXPRESSIONS["skeptic"][1]["h"] * 0.7
EXPRESSIONS["skeptic"][1]["rb"] *= 0.5

STATES = {
    # ---- BUSY ----
    "busy": {
        "ring": (255, 45, 40),
        "glow": (168, 0, 32),
        "eye": (255, 48, 72),
        "core": (255, 240, 240),
        "exprs": ("angry", "furious", "frustrated", "scared"),
        "expr_every": (3000, 4200),
        "blink": (4200, 9000),
        "wink": 0,
        "gaze": (1500, 3900),
        "gaze_range": (4, 2),
        "gaze_ease": 0.18,
        "breath": (2600, 0.10),
        "bright": 0.92,
    },
    # ---- HOLD ----
    "hold": {
        "ring": (255, 186, 20),
        "glow": (196, 110, 0),
        "eye": (255, 208, 56),
        "core": (255, 250, 232),
        "exprs": ("annoyed", "unimpressed", "squint", "worried", "sad"),
        "expr_every": (3600, 4800),
        "blink": (2400, 5600),
        "wink": 12,
        "gaze": (1500, 3900),
        "gaze_range": (7, 4),
        "gaze_ease": 0.18,
        "breath": (3200, 0.14),
        "bright": 0.90,
    },
    # ---- AWAIT ----
    "await": {
        "ring": (10, 126, 255),
        "glow": (0, 94, 255),
        "eye": (0, 200, 255),
        "core": (240, 251, 255),
        "exprs": ("normal", "focused", "skeptic", "sleepy", "suspicious"),
        "expr_every": (4200, 5400),
        "blink": (2800, 6200),
        "wink": 8,
        "gaze": (1500, 3900),
        "gaze_range": (8, 4),
        "gaze_ease": 0.18,
        "breath": (5200, 0.16),
        "bright": 0.85,
    },
    # ---- OPEN ----
    "open": {
        "ring": (40, 214, 92),
        "glow": (0, 168, 61),
        "eye": (0, 255, 114),
        "core": (232, 255, 240),
        "exprs": ("happy", "glee", "surprised", "awe"),
        "expr_every": (3800, 5000),
        "blink": (1700, 4000),
        "wink": 22,
        "gaze": (1500, 3900),
        "gaze_range": (8, 5),
        "gaze_ease": 0.18,
        "breath": (3800, 0.13),
        "bright": 1.0,
    },
}

# The button cycles from most to least available.
# Full-screen data pages are handled separately.
CYCLE = ("open", "await", "hold", "busy")

# State entered on a sustained shake.
ANGRY = "busy"

ALIASES = {
    "red": "busy", "dnd": "busy",
    "yellow": "hold", "amarillo": "hold", "brb": "hold", "soon": "hold",
    "focus": "await", "blue": "await", "wait": "await",
    "green": "open", "free": "open", "talk": "open",
}


def resolve(name):
    """Normalize a state name, or return None if it is unknown."""
    if not name:
        return None
    name = name.strip().lower()
    name = ALIASES.get(name, name)
    return name if name in STATES else None
