"""Animated character: two rounded bars that morph, look, and blink.

Each eye has no pupil; width, height, corner radii, and rotation express its
mood, while gaze moves the complete bar. Only the rectangular eye band is
redrawn, and only rows occupied in the current or previous frame are sent
over SPI. This leaves time for drawing within the board's frame budget.

Layered polygon outlines form the glow, filled polygons form the colored rim
and near-white body, and intermediate edge tones soften the boundaries.
Half-pixel outline spacing avoids gaps on diagonals. Fixed-point Viper code
builds all vertices with integer math; the RP2040 has no hardware FPU.
The pose parameters and their upstream attribution live in palette.py."""

import framebuf
import math
import micropython
import random
import time
from array import array

import backdrop
from gc9a01 import rgb565, mix

# Redraw only this band, which fits inside the status ring black center.
# Its background must never overwrite the colored ring.
# The ring geometry determines the maximum safe width.
BAND_X = 32
BAND_Y = 60
BAND_W = 176
BAND_H = 112

FACE_CX = 120.0
FACE_CY = 115.0

# Scale the full-screen preset geometry 8% toward the face center
# to keep the eyes inside the narrower band.
# Even the widest furious pose at maximum gaze retains margin
# against the band edge.
#
GEOM = 0.92

RIM = 3            # colored eye-rim thickness
HALO = 4           # glow radius around the silhouette
THIN = 8           # omit the rim below this eye height
CORNER = 4         # points per corner; four balances smoothness and fill cost
NVERT = CORNER * 4

_BLACK = 0         # black background inside the ring

_BLINK_CLOSE_MS = 90
_BLINK_HOLD_MS = 20
_BLINK_OPEN_MS = 140
_FADE_FROM = 0.72  # fade the closing eye completely after this threshold

_POSE_EASE = 0.16   # pose interpolation fraction per frame
_BREATH_RATE = 0.0032   # shape breathing rate in rad/ms
_BREATH_SKEW = 0.45     # phase offset between eyes in radians
_LOOK_SQUASH = 0.006    # vertical stretch from sideways gaze
_KEYS = ("x", "y", "w", "h", "rt", "rb", "rot")

# Space glow outlines by half a pixel to overlap on diagonals.
# Whole-pixel spacing leaves black gaps between adjacent contours.
#
GLOW_STEPS = 8
GLOW_MIN = 0.08    # outermost glow intensity
GLOW_MAX = 0.66    # glow intensity next to the silhouette

# Eye layers: silhouette offset in pixels, filled flag, color index.
# Draw from outside to inside.
# Half-pixel edge blends soften the rim boundaries.
# Each replaces a hard edge with an intermediate color.
#
_LAYERS = tuple((HALO - k * 0.5, False, k) for k in range(GLOW_STEPS)) + (
    (0.0, True, GLOW_STEPS),               # filled silhouette in rim color
    (0.0, False, GLOW_STEPS + 1),          # outer edge: glow to rim
    (-0.5, False, GLOW_STEPS + 2),
    (-RIM, True, GLOW_STEPS + 3),          # near-white body
    (-RIM + 0.5, False, GLOW_STEPS + 4),   # inner edge: rim to body
    (-RIM, False, GLOW_STEPS + 5),         # blend the strongest contrast boundary
    (-RIM - 0.5, False, GLOW_STEPS + 6),   # through intermediate tones
)
NLAYER = len(_LAYERS)
_CORE_CI = GLOW_STEPS + 3
_CORE_EDGE_CI = GLOW_STEPS + 6

# For each vertex, store corner-center signs and an outward direction
# scaled by 256, plus the corner index.
# Top and bottom radii differ, distinguishing smiles from frowns.
#
_BASIS = array("i", [0] * (NVERT * 5))
_n = 0
_corner = 0
for _sx, _sy, _m00, _m01, _m10, _m11 in (
        (-1, -1, -1.0, 0.0, 0.0, -1.0),   # top left
        (1, -1, 0.0, 1.0, -1.0, 0.0),     # top right
        (1, 1, 1.0, 0.0, 0.0, 1.0),       # bottom right
        (-1, 1, 0.0, -1.0, 1.0, 0.0)):    # bottom left
    for _i in range(CORNER):
        _t = math.radians(90.0 * _i / (CORNER - 1))
        _c = math.cos(_t)
        _s = math.sin(_t)
        _BASIS[_n] = _sx
        _BASIS[_n + 1] = _sy
        _BASIS[_n + 2] = int(round((_m00 * _c + _m01 * _s) * 256))
        _BASIS[_n + 3] = int(round((_m10 * _c + _m11 * _s) * 256))
        _BASIS[_n + 4] = _corner
        _n += 5
    _corner += 1


def _clamp(v, lo, hi):
    return lo if v < lo else (hi if v > hi else v)


def _smoothstep(v):
    v = _clamp(v, 0.0, 1.0)
    return v * v * (3.0 - 2.0 * v)


@micropython.viper
def _vertices(prm: ptr32, basis: ptr32, lay: ptr32, out: ptr16):
    """Calculate integer vertices for every layer of one eye.

    Offsetting half-axes and radii together preserves each corner center, so a
    single fixed-point pass replaces per-layer trigonometry.
    prm: center (1/256 px), cos/sin (x256), half-width/height, vertex/layer counts.
    basis: corner signs, outward x/y direction (x256), corner index (top: 0/1).
    lay: offset and top/bottom radii per layer (1/256 px).
    out: consecutive x/y vertex pairs for each layer."""
    cx = int(prm[0])
    cy = int(prm[1])
    cos_i = int(prm[2])
    sin_i = int(prm[3])
    hw = int(prm[4])
    hh = int(prm[5])
    nv = int(prm[6])
    nl = int(prm[7])

    o = 0
    layer = 0
    while layer < nl:
        j = layer * 3
        off = int(lay[j])
        rt = int(lay[j + 1])
        rb = int(lay[j + 2])
        hwl = hw + off
        hhl = hh + off
        if hwl < 0:
            hwl = 0
        if hhl < 0:
            hhl = 0
        v = 0
        while v < nv:
            k = v * 5
            if int(basis[k + 4]) < 2:
                r = rt
            else:
                r = rb
            if r > hwl:
                r = hwl
            if r > hhl:
                r = hhl
            if r < 0:
                r = 0
            a = hwl - r
            b = hhl - r
            dx = int(basis[k]) * a + ((r * int(basis[k + 2])) >> 8)
            dy = int(basis[k + 1]) * b + ((r * int(basis[k + 3])) >> 8)
            out[o] = (cx + ((dx * cos_i - dy * sin_i) >> 8) + 128) >> 8
            out[o + 1] = (cy + ((dx * sin_i + dy * cos_i) >> 8) + 128) >> 8
            o += 2
            v += 1
        layer += 1


class Face:
    def __init__(self, lcd, states, exprs, name):
        self.lcd = lcd
        self.states = states
        self.exprs = exprs
        self.band = bytearray(BAND_W * BAND_H * 2)
        self.fb = framebuf.FrameBuffer(self.band, BAND_W, BAND_H,
                                       framebuf.RGB565)
        self.view = memoryview(self.band)

        # Preallocate all eye-layer vertices and per-layer views,
        # avoiding copies when passing them to framebuf.poly.
        self.verts = array("h", [0] * (NLAYER * NVERT * 2))
        vv = memoryview(self.verts)
        self.slices = tuple(vv[i * NVERT * 2:(i + 1) * NVERT * 2]
                            for i in range(NLAYER))
        self.prm = array("i", [0] * 8)
        self.lay = array("i", [0] * (NLAYER * 3))

        # eye centers already scaled toward the face center
        self.cx = tuple(FACE_CX + (x - FACE_CX) * GEOM for x in (78.0, 162.0))

        self.name = name
        self.pal = states[name]
        self.pending = None

        # Current expression index, target pose, and interpolated
        # pose used for drawing.
        self.index = 0
        self.mood = self.pal["exprs"][0]
        self.tgt = exprs[self.mood]
        self.cur = [{}, {}]
        self.next_expr = 0

        # gaze
        self.gx = 0.0
        self.gy = 0.0
        self.tgx = 0.0
        self.tgy = 0.0
        self.next_gaze = 0

        # Blink: zero=open, one=closed; independent per eye for winks.
        self.blink = [0.0, 0.0]
        self.blink_phase = 0      # 0 idle, 1 closing, 2 holding, 3 opening
        self.blink_eyes = (0, 1)
        self.blink_at = 0
        self.next_blink = 0

        # per-eye geometry prepared by _advance for _eye
        self.geom = [[0] * 10, [0] * 10]
        # Reuse per-eye work dictionaries in _target instead of allocating
        # two new dictionaries every frame.
        self.tmp = [dict.fromkeys(_KEYS, 0.0), dict.fromkeys(_KEYS, 0.0)]
        # previously occupied band rows, for selective clearing
        self.dirty = (0, BAND_H - 1)

        self.gain = 1.0   # user brightness multiplier
        self.t0 = time.ticks_ms()
        self._pick_expr(self.t0, advance=False)
        for i in (0, 1):
            self.cur[i] = dict(self._target(i, 0.0))
        self.repaint()

    # ---- state ----

    def request(self, name):
        """Acknowledge every command with an expression and a blink."""
        if name == self.name and self.pending is None:
            # Repeating gbot await must still visibly acknowledge the command.
            # Keep availability and its ring; renew only the expression.
            self._pick_expr(time.ticks_ms(), advance=True)
            self._start_blink((0, 1))
            return
        self.pending = name
        self._start_blink((0, 1))

    def _apply(self, name):
        self.name = name
        self.pal = self.states[name]
        self.pending = None
        self.index = 0            # each state starts with its first expression
        self._pick_expr(time.ticks_ms(), advance=False)
        self.repaint()

    def repaint(self):
        """Rebuild colors, repaint the background, and invalidate the whole band."""
        self.colors = self._ramp(1.0)
        self.dirty = (0, BAND_H - 1)   # background changed: invalidate the whole band
        backdrop.paint_full(self.lcd, backdrop.build(self.pal))

    def _ramp(self, level):
        """Build one color per layer in _LAYERS order.

        Eight glow steps and five edge tones approximate soft lighting. level < 1
        fades toward the black background during the middle of a blink."""
        pal = self.pal
        black = (0, 0, 0)
        glow = mix(black, pal["glow"], level)
        eye = mix(black, pal["eye"], level)
        core = mix(black, pal["core"], level)
        halo = level * level      # fade the glow before the eye itself
        span = (GLOW_MAX - GLOW_MIN) / (GLOW_STEPS - 1)
        ramp = [rgb565(*mix(black, glow, (GLOW_MIN + span * k) * halo))
                for k in range(GLOW_STEPS)]
        ramp.append(rgb565(*eye))
        ramp.append(rgb565(*mix(glow, eye, 0.50)))
        ramp.append(rgb565(*mix(glow, eye, 0.80)))
        ramp.append(rgb565(*core))
        ramp.append(rgb565(*mix(eye, core, 0.18)))
        ramp.append(rgb565(*mix(eye, core, 0.45)))
        ramp.append(rgb565(*mix(eye, core, 0.75)))
        return ramp

    # ---- expressions ----

    def _pick_expr(self, now, advance=True):
        """Choose a random expression from this state without an immediate repeat."""
        names = self.pal["exprs"]
        if advance and len(names) > 1:
            pick = random.randint(0, len(names) - 2)
            self.index = pick if pick < self.index else pick + 1
        self.mood = names[self.index]
        self.tgt = self.exprs[self.mood]
        lo, hi = self.pal["expr_every"]
        self.next_expr = time.ticks_add(now, random.randint(lo, hi))
        self.next_gaze = now      # new expression, new gaze saccade

    def _update_expr(self, now):
        if time.ticks_diff(now, self.next_expr) >= 0:
            self._pick_expr(now)
            # hide an expression change inside a natural blink
            if self.blink_phase == 0 and random.randint(0, 2):
                self._start_blink((0, 1))

    # ---- animation ----

    def _start_blink(self, eyes):
        self.blink_eyes = eyes
        self.blink_phase = 1
        self.blink_at = time.ticks_ms()

    def _update_blink(self, now):
        pal = self.pal
        phase = self.blink_phase

        if phase == 0:
            if self.next_blink == 0:
                lo, hi = pal["blink"]
                self.next_blink = time.ticks_add(now, random.randint(lo, hi))
            elif time.ticks_diff(now, self.next_blink) >= 0:
                self.next_blink = 0
                if random.randint(0, 99) < pal["wink"]:
                    self._start_blink((random.randint(0, 1),))
                else:
                    self._start_blink((0, 1))
            return

        dt = time.ticks_diff(now, self.blink_at)
        if phase == 1:
            v = _smoothstep(dt / _BLINK_CLOSE_MS)
            if dt >= _BLINK_CLOSE_MS:
                v = 1.0
                self.blink_phase = 2
                self.blink_at = now
                # Apply state changes while the eyes are closed,
                # hiding the background repaint inside the blink.
                if self.pending:
                    self._apply(self.pending)
        elif phase == 2:
            v = 1.0
            if dt >= _BLINK_HOLD_MS:
                self.blink_phase = 3
                self.blink_at = now
        else:
            v = 1.0 - _smoothstep(dt / _BLINK_OPEN_MS)
            if dt >= _BLINK_OPEN_MS:
                v = 0.0
                self.blink_phase = 0
                lo, hi = pal["blink"]
                self.next_blink = time.ticks_add(now, random.randint(lo, hi))

        for i in (0, 1):
            self.blink[i] = v if i in self.blink_eyes else 0.0

    def _update_gaze(self, now):
        pal = self.pal
        if time.ticks_diff(now, self.next_gaze) >= 0:
            lo, hi = pal["gaze"]
            self.next_gaze = time.ticks_add(now, random.randint(lo, hi))
            rx, ry = pal["gaze_range"]
            self.tgx = random.randint(-rx, rx)
            self.tgy = random.randint(-ry, ry)
        # A short saccade followed by settling, like a camera mechanism.
        ease = pal["gaze_ease"]
        self.gx += (self.tgx - self.gx) * ease
        self.gy += (self.tgy - self.gy) * ease

    def _breath(self, now):
        """Return the breathing backlight level."""
        pal = self.pal
        period, depth = pal["breath"]
        phase = (time.ticks_diff(now, self.t0) % period) / period
        wave = (1.0 - math.cos(phase * 6.2832)) * 0.5   # 0 -> 1 -> 0
        return pal["bright"] * (1.0 - depth + depth * wave)

    def tick(self):
        now = time.ticks_ms()
        self._update_expr(now)
        self._update_blink(now)
        self._update_gaze(now)
        self.lcd.backlight(self._breath(now) * self.gain)
        self._draw(now)

    # ---- drawing ----

    def _target(self, i, breath):
        """Return this frame's target pose, including shape breathing and gaze.

        x/y identify the top-left corner. The returned per-eye work dictionary is
        reused; callers must copy it if they need to keep an earlier value."""
        e = self.tgt[i]
        w = e["w"] * GEOM
        h = (e["h"] + breath * e["breath"]) * GEOM
        # Sideways gaze slightly stretches the eye on the looking side.
        h *= 1.0 + (-self.gx if i == 0 else self.gx) * _LOOK_SQUASH
        t = self.tmp[i]
        t["x"] = self.cx[i] + e["dx"] * GEOM - w * 0.5 + self.gx
        t["y"] = FACE_CY + (e["y"] - FACE_CY) * GEOM + self.gy
        t["w"] = w
        t["h"] = h
        t["rt"] = e["rt"] * GEOM
        t["rb"] = e["rb"] * GEOM
        t["rot"] = e["rot"]
        return t

    def _draw(self, now):
        # The eyes breathe half a radian out of phase.
        # Interpolate both poses first to identify rows to clear.
        # Build vertices one eye at a time because they share
        # the same backing array.
        phase = time.ticks_diff(now, self.t0) * _BREATH_RATE
        top = BAND_H - 1
        bot = 0
        for i in (0, 1):
            t, b = self._advance(i, math.sin(phase + i * _BREATH_SKEW))
            if t < top:
                top = t
            if b > bot:
                bot = b
        if top < 0:
            top = 0
        if bot > BAND_H - 1:
            bot = BAND_H - 1

        # Clear and transfer only rows occupied now or in the previous frame.
        y0 = top if top < self.dirty[0] else self.dirty[0]
        y1 = bot if bot > self.dirty[1] else self.dirty[1]
        self.dirty = (top, bot)

        rows = y1 - y0 + 1
        self.fb.fill_rect(0, y0, BAND_W, rows, _BLACK)
        for i in (0, 1):
            self._eye(i)
        self.lcd.blit(self.view[y0 * BAND_W * 2:(y1 + 1) * BAND_W * 2],
                      BAND_X, BAND_Y + y0, BAND_W, rows)

    def _advance(self, i, breath):
        """Interpolate one eye pose; return occupied band rows including its glow."""
        cur = self.cur[i]
        tgt = self._target(i, breath)
        for key in _KEYS:
            cur[key] += (tgt[key] - cur[key]) * _POSE_EASE

        w = cur["w"]
        h = cur["h"]
        # Blinking collapses the bar around its center.
        drawn = 2.0 + (h - 2.0) * (1.0 - self.blink[i])
        hw = w * 0.5
        hh = drawn * 0.5


        rot = math.radians(cur["rot"])
        cos_a = math.cos(rot)
        sin_a = math.sin(rot)
        cy = cur["y"] + h * 0.5 - BAND_Y

        g = self.geom[i]
        g[0] = int((cur["x"] + w * 0.5 - BAND_X) * 256)
        g[1] = int(cy * 256)
        g[2] = int(cos_a * 256)
        g[3] = int(sin_a * 256)
        g[4] = hw
        g[5] = hh
        g[6] = cur["rt"]
        g[7] = drawn < THIN
        g[8] = cur["rb"]
        g[9] = self.tgt[i]["bite"] * GEOM

        # occupied rows, including glow and a one-pixel guard
        ey = (hw + HALO) * abs(sin_a) + (hh + HALO) * abs(cos_a) + 2.0
        return int(cy - ey), int(cy + ey) + 1

    def _eye(self, i):
        """Build one eye geometry and draw its layers."""
        g = self.geom[i]
        prm = self.prm
        prm[0] = g[0]
        prm[1] = g[1]
        prm[2] = g[2]
        prm[3] = g[3]
        prm[4] = int(g[4] * 256)
        prm[5] = int(g[5] * 256)
        prm[6] = NVERT
        prm[7] = NLAYER
        lay = self.lay
        for k in range(NLAYER):
            off = _LAYERS[k][0]
            lay[k * 3] = int(off * 256)
            rt = g[6] + off
            rb = g[8] + off
            lay[k * 3 + 1] = int(rt * 256) if rt > 0.0 else 0
            lay[k * 3 + 2] = int(rb * 256) if rb > 0.0 else 0
        _vertices(prm, _BASIS, lay, self.verts)

        blink = self.blink[i]
        if blink <= 0.0:
            colors = self.colors
        else:
            colors = self._ramp(
                1.0 - _smoothstep((blink - _FADE_FROM) / (1.0 - _FADE_FROM)))

        thin = g[7]
        fb = self.fb
        slices = self.slices
        for k in range(NLAYER):
            off, fill, ci = _LAYERS[k]
            if thin:
                # Very thin eyes use only the body color, with no rim.
                # Use the silhouette as the body and skip the inner body layer.
                if off < 0.0:
                    continue
                if off == 0.0:
                    ci = _CORE_CI if fill else _CORE_EDGE_CI
            fb.poly(0, 0, slices[k], colors[ci], fill)

        # A black ellipse cuts a crescent into the bottom of the smile.
        # This implements upstream Inverse_Radius_Bottom.
        bite = g[9]
        if bite > 0.0 and not blink:
            # g[0] and g[1] already use band coordinates
            hw = g[4]
            ry = int(hw * 0.85)
            cx = g[0] // 256
            bottom = g[1] // 256 + int(g[5])
            fb.ellipse(cx, bottom + ry - int(bite), int(hw * 1.15), ry,
                       _BLACK, True)
