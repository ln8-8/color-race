"""FLAG FACTORY — country-flag balls race through a factory with real physics.

Every level the first half through the exit gate(s) QUALIFY; the gates shut, the trapdoor opens and the rest
fall into the SHREDDER, until one champion is left.

  Shorts (portrait 1080x1920): 32 countries, 5 levels, ~60-85 s
  Long  (landscape 1920x1080): ALL 197 countries, 8 levels, ~2-3 min

Every machine part slopes toward an exit (no flat ledges, no dead-end corners), so balls always reach a gate
on their own. A tiny invisible nudge only frees a ball that has been perfectly still for a while.

Usage: python factory2d.py --seed 5 --out out/                 (Short)
       python factory2d.py --seed 5 --out out/ --long          (2-3 min, all countries)
"""
import argparse
import json
import math
import os
import random
import subprocess
import wave

import numpy as np
import pymunk
from PIL import Image, ImageDraw, ImageFont

from countries import COUNTRIES

HERE = os.path.dirname(os.path.abspath(__file__))
FPS, SR, SUB = 30, 44100, 4
FONT = os.path.join(HERE, "assets", "font.otf")
EMOJI_FONTS = ["/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf", "/usr/share/fonts/noto/NotoColorEmoji.ttf",
               os.path.join(HERE, "assets", "NotoColorEmoji.ttf")]
OL = (18, 18, 24)

LAYOUTS = {
    "portrait": dict(W=1080, H=1920, X0=70, X1=1010, HUD=300, HOLD_Y=640, BANDS=[(690, 1090), (1120, 1490)],
                     FUN_Y=1530, GATE_Y=1690, SHRED_Y=1770, GATES=1, RMAX=66),
    "landscape": dict(W=1920, H=1080, X0=80, X1=1840, HUD=170, HOLD_Y=310, BANDS=[(340, 560), (580, 790)],
                      FUN_Y=820, GATE_Y=950, SHRED_Y=995, GATES=2, RMAX=44),
}
L = dict(LAYOUTS["portrait"])

# Places: purely visual (physics never depends on the place, so a pre-tested seed renders the same race anywhere).
# bg = top/bottom gradient, rail = machine colour, stripe = funnel stripes, pit = what eliminates the losers.
THEMES = {
    "factory": dict(title="Factory", pit="SHREDDER", bg=((34, 38, 48), (52, 52, 58)), rail=(150, 158, 175),
                    stripe=((250, 200, 30), (30, 30, 34)), bump=(230, 50, 70), pit_bg=(30, 12, 12), pit_fx="gears",
                    pit_col=(255, 70, 60), deco="pipes", spark=(255, 200, 40)),
    "space": dict(title="Space Station", pit="BLACK HOLE", bg=((8, 6, 26), (30, 14, 56)), rail=(90, 220, 255),
                  stripe=((90, 220, 255), (20, 24, 60)), bump=(255, 80, 200), pit_bg=(4, 2, 10), pit_fx="vortex",
                  pit_col=(190, 120, 255), deco="stars", spark=(200, 160, 255)),
    "ice": dict(title="Ice Cave", pit="FREEZER", bg=((120, 190, 230), (40, 90, 150)), rail=(225, 245, 255),
                stripe=((240, 250, 255), (70, 150, 210)), bump=(80, 170, 255), pit_bg=(20, 60, 110), pit_fx="spikes",
                pit_col=(200, 240, 255), deco="snow", spark=(230, 250, 255)),
    "jungle": dict(title="Jungle Temple", pit="PIRANHA RIVER", bg=((30, 90, 50), (16, 50, 30)), rail=(150, 105, 60),
                   stripe=((230, 190, 90), (90, 60, 30)), bump=(240, 120, 40), pit_bg=(20, 60, 70), pit_fx="water",
                   pit_col=(120, 255, 160), deco="vines", spark=(120, 220, 255)),
    "volcano": dict(title="Volcano", pit="LAVA", bg=((60, 18, 14), (24, 10, 10)), rail=(120, 110, 105),
                    stripe=((255, 120, 20), (40, 30, 28)), bump=(255, 90, 30), pit_bg=(120, 30, 0), pit_fx="lava",
                    pit_col=(255, 200, 60), deco="embers", spark=(255, 150, 30)),
    "candy": dict(title="Candy Factory", pit="CHOCOLATE", bg=((255, 170, 210), (200, 120, 200)), rail=(255, 250, 250),
                  stripe=((255, 60, 110), (255, 250, 250)), bump=(120, 220, 255), pit_bg=(90, 45, 20), pit_fx="water",
                  pit_col=(255, 230, 200), deco="sprinkles", spark=(255, 240, 120)),
    "sea": dict(title="Deep Sea", pit="SHARK TANK", bg=((20, 110, 160), (6, 30, 70)), rail=(255, 140, 110),
                stripe=((255, 200, 80), (20, 60, 110)), bump=(255, 210, 60), pit_bg=(4, 20, 50), pit_fx="spikes",
                pit_col=(120, 220, 255), deco="bubbles", spark=(180, 240, 255)),
    "neon": dict(title="Neon City", pit="ZAPPER", bg=((16, 8, 36), (50, 10, 60)), rail=(255, 60, 200),
                 stripe=((60, 255, 220), (30, 10, 50)), bump=(255, 230, 50), pit_bg=(10, 4, 24), pit_fx="zap",
                 pit_col=(60, 255, 220), deco="skyline", spark=(255, 255, 120)),
}
THEME_NAMES = list(THEMES)
T = dict(THEMES["factory"])


def font(size):
    return ImageFont.truetype(FONT, max(1, int(size)))


def text_c(d, xy, s, size, fill, stroke=6, sf=OL, anchor="mm", max_w=None):
    if max_w:                                            # shrink long text so it always fits the screen
        w = font(size).getlength(s) + 2 * stroke
        if w > max_w:
            size = size * max_w / w
    d.text(xy, s, font=font(size), fill=fill, anchor=anchor, stroke_width=stroke, stroke_fill=sf)


def flag_emoji(cc):
    return "".join(chr(0x1F1E6 + ord(c) - 65) for c in cc)


def ball_radius(n):
    r = 13 if n > 150 else 17 if n > 80 else 22 if n > 40 else 31 if n > 20 else 38 if n > 10 else 46 if n > 5 else 56 if n > 2 else 66
    return min(r, L["RMAX"])


# ---------------------------------------------------------------- ball sprites
class Balls:
    def __init__(self):
        path = next((p for p in EMOJI_FONTS if os.path.exists(p)), None)
        if not path:
            raise RuntimeError("Noto Color Emoji font not found (apt-get install fonts-noto-color-emoji)")
        self.ef = ImageFont.truetype(path, 109)
        self.flags, self.cache = {}, {}

    def flag(self, cc):
        if cc not in self.flags:
            im = Image.new("RGBA", (160, 160), (0, 0, 0, 0))
            ImageDraw.Draw(im).text((10, 10), flag_emoji(cc), font=self.ef, embedded_color=True)
            im = im.crop(im.getbbox())
            w, h = im.size
            side = int(min(w, h) * 0.86)
            cx, cy = w // 2, h // 2
            self.flags[cc] = im.crop((cx - side // 2, cy - side // 2, cx + side // 2, cy + side // 2)).convert("RGBA")
        return self.flags[cc]

    def sprite(self, cc, r, angle_deg=0):
        r = max(6, int(r))
        key = (cc, r, int(angle_deg) // 12 % 30)
        if key in self.cache:
            return self.cache[key]
        S = 4 if r < 80 else 2
        D = 2 * r * S
        base = self.flag(cc).resize((D, D), Image.LANCZOS)
        if key[2]:
            base = base.rotate(-key[2] * 12, resample=Image.BICUBIC)
        mask = Image.new("L", (D, D), 0)
        ImageDraw.Draw(mask).ellipse([0, 0, D - 1, D - 1], fill=255)
        o = max(2, int(r * 0.12)) * S
        ball = Image.new("RGBA", (D + 2 * o, D + 2 * o), (0, 0, 0, 0))
        ImageDraw.Draw(ball).ellipse([0, 0, D + 2 * o - 1, D + 2 * o - 1], fill=OL)
        ball.paste(base, (o, o), mask)
        hl = Image.new("RGBA", ball.size, (0, 0, 0, 0))
        g = ImageDraw.Draw(hl)
        g.ellipse([D * 0.22, D * 0.12, D * 0.62, D * 0.42], fill=(255, 255, 255, 95))
        g.ellipse([D * 0.3, D * 0.2, D * 0.42, D * 0.3], fill=(255, 255, 255, 150))
        ball = Image.alpha_composite(ball, hl)
        out = ball.resize((ball.width // S, ball.height // S), Image.LANCZOS)
        if len(self.cache) > 6000:
            self.cache.clear()
        self.cache[key] = out
        return out


# ---------------------------------------------------------------- the machine
SLOPE = math.radians(22)          # every rail slopes at least this much -> balls never rest on it


class Level:
    def __init__(self, n, quota, r, rng):
        self.n, self.quota, self.r = n, quota, r
        X0, X1 = L["X0"], L["X1"]
        self.space = pymunk.Space()
        self.space.gravity = (0, 1700 if L["GATES"] == 1 else 1050)
        self.space.iterations = 20
        self.statics, self.kin, self.belts, self.bumpers, self.pegs = [], [], [], [], []
        self.obstacles = []                     # shapes removed when the trapdoor opens
        sb = self.space.static_body

        def seg(a, b, rad=7, el=0.35, fr=0.5, store=True, obstacle=True):
            s = pymunk.Segment(sb, a, b, rad)
            s.elasticity, s.friction = el, fr
            self.space.add(s)
            if store:
                self.statics.append((a, b, rad))
            if obstacle:
                self.obstacles.append(s)
            return s

        self.seg = seg
        seg((X0, L["HUD"]), (X0, L["SHRED_Y"]), 8, obstacle=False)
        seg((X1, L["HUD"]), (X1, L["SHRED_Y"]), 8, obstacle=False)
        # exit gates + V funnels (a peak between two gates sends balls to both sides)
        self.gw = 3 * r + 60 + (50 if n > 60 and L["GATES"] == 1 else 0)
        G = L["GATES"]
        centers = [X0 + (X1 - X0) * (k + 0.5) / G for k in range(G)]
        self.gates = [(c - self.gw / 2, c + self.gw / 2) for c in centers]
        pts, x_prev = [], X0
        for k, (gl, gr) in enumerate(self.gates):
            pts.append(((x_prev, L["FUN_Y"]), (gl, L["GATE_Y"])))
            peak = (X1 if k == G - 1 else (gr + self.gates[k + 1][0]) / 2)
            pts.append(((gr, L["GATE_Y"]), (peak, L["FUN_Y"])))
            x_prev = peak
        self.funnel_pts = pts
        self.funnel = [seg(a, b, 9, fr=0.3, store=False, obstacle=False) for a, b in pts]
        self.hold = seg((X0, L["HOLD_Y"]), (X1, L["HOLD_Y"]), 7, store=False, obstacle=False)
        self.closed = []
        kinds = ["pegs", "paddles", "rails", "belts", "wheels", "bumpers", "flippers", "splitters", "spinners", "ramps"]
        rng.shuffle(kinds)
        self.kinds = kinds[:2]
        low = L["HOLD_Y"]
        for kind, (y0, y1) in zip(self.kinds, L["BANDS"]):
            y1 = min(y1, L["FUN_Y"] - 2 * r - 60)          # always leave a full ball-height of space above the funnel
            y0 = max(y0, low + 2 * r + 50)                 # ...and below the section above (no wedge between them)
            if y1 - y0 >= 90:
                ns, nk = len(self.statics), len(self.kin)
                self._build(kind, y0, y1, rng)
                ys = [max(a[1], b[1]) + rad for a, b, rad in self.statics[ns:]]
                ys += [item[1].position.y + (item[2] if item[0] != "flipper" else item[2] * math.sin(math.radians(40)))
                       for item in self.kin[nk:]]
                ys += [y + 38 for _, y in self.bumpers] + [y + 13 for _, y in self.pegs]
                low = max([low] + ys)

    # every builder keeps a free lane of at least 2r+44 next to walls and at the ends of rails
    def _build(self, kind, y0, y1, rng):
        X0, X1, r = L["X0"], L["X1"], self.r
        sb, lane = self.space.static_body, 2.6 * r + 60
        width = X1 - X0
        if kind == "pegs":
            sp = 2 * r + 52
            rows = max(2, int((y1 - y0 - 40) / (sp * 0.85)))
            for j in range(rows):
                y = y0 + 30 + j * sp * 0.85
                x = X0 + lane + (sp / 2 if j % 2 else 0)
                while x < X1 - lane:
                    c = pymunk.Circle(sb, 9, (x, y))
                    c.elasticity, c.friction = 0.6, 0.2
                    self.space.add(c)
                    self.obstacles.append(c)
                    self.pegs.append((x, y))
                    x += sp
        elif kind in ("rails", "belts", "flippers"):
            # herringbone: short sloped rails from alternating walls, each ending in a free lane
            seg_len = min(width * 0.48, 560, (y1 - y0 - 10) / math.tan(math.radians(40 if kind == "flippers" else 22)))
            if seg_len < 4 * r:
                return
            dy = seg_len * math.tan(SLOPE)
            rows = max(1, int((y1 - y0) / (dy + 2 * r + 30)))
            for j in range(rows):
                y = y0 + 10 + j * (y1 - y0) / rows
                left = (j + rng.randrange(2)) % 2 == 0
                a = (X0, y) if left else (X1, y)
                b = (X0 + seg_len, y + dy) if left else (X1 - seg_len, y + dy)
                if kind == "rails":
                    self.seg(a, b, 8, fr=0.25)
                elif kind == "belts":
                    s = self.seg(a, b, 9, el=0.1, fr=0.9)
                    sp = 280 * (1 if left else -1)
                    s.surface_velocity = (sp * math.cos(SLOPE), sp * math.sin(SLOPE) * (1 if left else -1))  # downhill
                    self.belts.append((a, b, 1 if left else -1))
                    self.statics.pop()
                else:     # flipper: pivots at the wall and swings between 10 and 40 degrees (always downhill)
                    body = pymunk.Body(body_type=pymunk.Body.KINEMATIC)
                    body.position = a
                    sgn = 1 if left else -1
                    body.angle = sgn * math.radians(25)
                    s = pymunk.Segment(body, (0, 0), (sgn * seg_len * 0.9, 0), 10)
                    s.elasticity, s.friction = 0.3, 0.4
                    self.space.add(body, s)
                    self.obstacles.append(s)
                    self.kin.append(("flipper", body, seg_len * 0.9, sgn, rng.uniform(0, 6)))
        elif kind == "paddles":
            n = max(2, int(width / 330))
            for k in range(n):
                b = pymunk.Body(body_type=pymunk.Body.KINEMATIC)
                b.position = (X0 + (k + 0.5) * width / n, (y0 + y1) / 2 + (k % 2 - 0.5) * (y1 - y0) * 0.25)
                b.angular_velocity = rng.uniform(1.5, 2.6) * (1 if k % 2 else -1)
                Lh = width / n * 0.38
                s = pymunk.Segment(b, (-Lh, 0), (Lh, 0), 10)
                s.elasticity, s.friction = 0.5, 0.4
                self.space.add(b, s)
                self.obstacles.append(s)
                self.kin.append(("paddle", b, Lh, 0, 0))
        elif kind == "wheels":
            n = max(2, int(width / 450))
            R = min(150, (y1 - y0) / 2 - 15)
            for k in range(n):
                b = pymunk.Body(body_type=pymunk.Body.KINEMATIC)
                b.position = (X0 + (k + 0.5) * width / n, (y0 + y1) / 2)
                b.angular_velocity = 1.4 * (1 if k % 2 else -1)
                self.space.add(b)
                for a4 in range(4):
                    ang = a4 * math.pi / 2
                    s = pymunk.Segment(b, (0, 0), (R * math.cos(ang), R * math.sin(ang)), 9)
                    s.elasticity, s.friction = 0.4, 0.4
                    self.space.add(s)
                    self.obstacles.append(s)
                self.kin.append(("wheel", b, R, 0, 0))
        elif kind == "bumpers":
            # bouncy round bumpers with a full free lane between every pair and next to the walls
            R = 32
            step = 2 * R + lane
            cols = max(1, int((width - lane) // step))
            x_first = X0 + (width - (cols * 2 * R + (cols - 1) * lane)) / 2 + R
            rows = [(y0 + R + 10, [x_first + k * step for k in range(cols)])]
            y2 = y0 + R + 10 + 2 * R + 2 * r + 60
            if y2 + R < y1 and cols > 1:
                rows.append((y2, [x_first + (k + 0.5) * step for k in range(cols - 1)]))
            for y, xs in rows:
                for x in xs:
                    c = pymunk.Circle(sb, R, (x, y))
                    c.elasticity, c.friction = 1.1, 0.1
                    self.space.add(c)
                    self.obstacles.append(c)
                    self.bumpers.append((x, y))
        elif kind == "spinners":
            # small 3-arm rotors in a staggered row, a free lane around every one
            R = min(r + 40, (y1 - y0) / 2 - 15, 110)
            step = 2 * R + lane
            cols = max(1, int((width - lane) // step))
            x_first = X0 + (width - (cols * 2 * R + (cols - 1) * lane)) / 2 + R
            rows = [((y0 + y1) / 2 if (y1 - y0) < 4 * R + 2 * r + 60 else y0 + R + 10, [x_first + k * step for k in range(cols)])]
            y2 = rows[0][0] + 2 * R + 2 * r + 50
            if y2 + R < y1 and cols > 1:
                rows.append((y2, [x_first + (k + 0.5) * step for k in range(cols - 1)]))
            for j, (y, xs) in enumerate(rows):
                for k, x in enumerate(xs):
                    b = pymunk.Body(body_type=pymunk.Body.KINEMATIC)
                    b.position = (x, y)
                    b.angular_velocity = rng.uniform(1.8, 2.8) * (1 if (j + k) % 2 else -1)
                    self.space.add(b)
                    for a3 in range(3):
                        ang = a3 * 2 * math.pi / 3
                        sh = pymunk.Segment(b, (0, 0), (R * math.cos(ang), R * math.sin(ang)), 8)
                        sh.elasticity, sh.friction = 0.5, 0.3
                        self.space.add(sh)
                        self.obstacles.append(sh)
                    self.kin.append(("spinner", b, R, 3, 0))
        elif kind == "ramps":
            # short free-standing sloped ramps in a staggered pattern; both ends are open lanes
            ramp = min(260, (width - 3 * lane) / 2)
            if ramp < 80:
                return
            dy = ramp * math.tan(SLOPE)
            rows = max(1, int((y1 - y0) / (dy + 2 * r + 40)))
            for j in range(rows):
                y = y0 + 10 + j * (y1 - y0) / rows
                sgn = 1 if (j + rng.randrange(2)) % 2 else -1
                n_r = max(1, int((width - lane) // (ramp + lane)))
                gap = (width - n_r * ramp) / (n_r + 1)
                for k in range(n_r):
                    xa = X0 + gap + k * (ramp + gap)
                    a, b = ((xa, y), (xa + ramp, y + dy)) if sgn > 0 else ((xa, y + dy), (xa + ramp, y))
                    self.seg(a, b, 8, fr=0.25)
        elif kind == "splitters":
            # roof-shaped deflectors (apex up). Every gap (roof-roof and roof-wall) is a full free lane,
            # so there is never a valley narrower than a ball.
            n = max(1, int(width / 420))
            while n > 1 and (width - (n + 1) * lane) / (2 * n) < 50:
                n -= 1
            half = (width - (n + 1) * lane) / (2 * n)
            if half < 40:
                return
            h = half * math.tan(math.radians(30))
            row1 = y0 + 20
            centers1 = [X0 + lane + half + k * (2 * half + lane) for k in range(n)]
            rows = [(row1, centers1)]
            row2 = row1 + h + 2 * r + 40
            if n > 1 and row2 + h < y1:
                rows.append((row2, [(centers1[k] + centers1[k + 1]) / 2 for k in range(n - 1)]))
            for yy, cxs in rows:
                for cx in cxs:
                    self.seg((cx - half, yy + h), (cx, yy), 8, fr=0.2)
                    self.seg((cx, yy), (cx + half, yy + h), 8, fr=0.2)

    def release(self):
        self.space.remove(self.hold)
        self.hold = None

    def close_gates(self):
        for gl, gr in self.gates:
            self.closed.append(self.seg((gl - 4, L["GATE_Y"]), (gr + 4, L["GATE_Y"]), 9, store=False, obstacle=False))

    def open_trapdoor(self):
        for s in self.funnel + self.closed + self.obstacles:
            if s in self.space.shapes:
                self.space.remove(s)
        for item in self.kin:
            if item[1] in self.space.bodies:
                self.space.remove(item[1])
        self.funnel, self.closed, self.obstacles, self.kin = [], [], [], []
        self.statics = self.statics[:2]
        self.pegs, self.bumpers, self.belts = [], [], []

    def step(self, t, dt):
        for kind, b, Lh, sgn, ph in self.kin:
            if kind == "flipper":
                b.angular_velocity = sgn * math.radians(15) * 2.2 * math.cos(t * 2.2 + ph)   # angle 25 +/- 15 deg
        self.space.step(dt)


# ---------------------------------------------------------------- drawing
def _mix(a, b, t):
    return tuple(int(a[k] + (b[k] - a[k]) * t) for k in range(3))


def factory_background(seed):
    W, H = L["W"], L["H"]
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    c0, c1 = T["bg"]
    for y in range(H):
        d.line([(0, y), (W, y)], fill=_mix(c0, c1, y / H))
    r = np.random.default_rng(seed)
    soft = lambda k: _mix(c0, (255, 255, 255), k) if sum(c0) < 380 else _mix(c0, (0, 0, 0), k)   # noqa: E731
    top, deco = L["HUD"], T["deco"]
    if deco == "pipes":
        for k in range(int(W / 120)):
            x = int(r.uniform(0, W))
            d.rectangle([x - 14, top, x + 14, H], fill=soft(0.08))
            for y in range(top + 30, H, 160):
                d.rectangle([x - 20, y, x + 20, y + 14], fill=soft(0.14))
        for x in range(30, W, 120):
            for y in range(top + 40, H, 200):
                d.ellipse([x - 4, y - 4, x + 4, y + 4], fill=soft(0.2))
    elif deco == "stars":
        px, py, pr = r.uniform(0.15, 0.85) * W, r.uniform(top + 200, H * 0.6), r.uniform(90, 160)
        d.ellipse([px - pr, py - pr, px + pr, py + pr], fill=(70, 50, 130))
        d.ellipse([px - pr * 0.8, py - pr * 0.9, px + pr * 0.6, py + pr * 0.3], fill=(100, 80, 170))
        d.ellipse([px - pr * 1.7, py - pr * 0.25, px + pr * 1.7, py + pr * 0.25], outline=(170, 150, 230), width=6)
        for _ in range(int(W * H / 9000)):
            x, y, s_ = r.uniform(0, W), r.uniform(top, H), r.uniform(1, 3.2)
            d.ellipse([x - s_, y - s_, x + s_, y + s_], fill=(255, 255, int(r.uniform(200, 255))))
    elif deco == "snow":
        for x in range(0, W, 70):
            ln = r.uniform(30, 110)
            d.polygon([(x, top), (x + 34, top), (x + 17, top + ln)], fill=(235, 248, 255))
        for _ in range(int(W * H / 14000)):
            x, y, s_ = r.uniform(0, W), r.uniform(top, H), r.uniform(2, 6)
            d.ellipse([x - s_, y - s_, x + s_, y + s_], fill=(245, 252, 255))
    elif deco == "vines":
        for k in range(int(W / 200)):
            x0 = r.uniform(0, W)
            for y in range(top, int(top + r.uniform(0.3, 0.8) * (H - top)), 44):
                x = x0 + 30 * math.sin(y / 90 + k)
                d.ellipse([x - 16, y - 8, x + 16, y + 8], fill=(40 + int(r.uniform(0, 40)), 130 + int(r.uniform(0, 60)), 50))
        for x in range(0, W, 160):
            for y in range(top + 80, H, 220):
                d.rectangle([x, y, x + 150, y + 100], outline=soft(0.07), width=4)
    elif deco == "embers":
        for k in range(6):
            x = r.uniform(0, W)
            d.polygon([(x - 300, H), (x, H * r.uniform(0.45, 0.7)), (x + 300, H)], fill=soft(0.06))
        for _ in range(int(W * H / 12000)):
            x, y, s_ = r.uniform(0, W), r.uniform(top, H), r.uniform(1.5, 4)
            d.ellipse([x - s_, y - s_, x + s_, y + s_], fill=(255, int(r.uniform(90, 200)), 30))
    elif deco == "sprinkles":
        cols = [(255, 80, 120), (120, 220, 255), (255, 240, 120), (140, 255, 160), (255, 255, 255)]
        for _ in range(int(W * H / 5000)):
            x, y, a = r.uniform(0, W), r.uniform(top, H), r.uniform(0, math.pi)
            d.line([(x, y), (x + 14 * math.cos(a), y + 14 * math.sin(a))], fill=cols[int(r.uniform(0, 5))], width=6)
    elif deco == "bubbles":
        for k in range(int(W / 110)):
            x = r.uniform(0, W)
            for y in range(H, top + 300, -30):
                xx = x + 25 * math.sin(y / 60 + k)
                d.line([(xx, y), (xx, y - 26)], fill=(20, 120 + k % 40, 80), width=10)
        for _ in range(int(W * H / 10000)):
            x, y, s_ = r.uniform(0, W), r.uniform(top, H), r.uniform(4, 14)
            d.ellipse([x - s_, y - s_, x + s_, y + s_], outline=(170, 230, 255), width=2)
    elif deco == "skyline":
        x = 0
        while x < W:
            bw, bh = r.uniform(70, 160), r.uniform(H * 0.2, H * 0.6)
            d.rectangle([x, H - bh, x + bw, H], fill=(28, 14, 50))
            for wy in range(int(H - bh + 20), H, 34):
                for wx in range(int(x + 12), int(x + bw - 12), 26):
                    if r.uniform() < 0.4:
                        d.rectangle([wx, wy, wx + 12, wy + 16], fill=[(255, 60, 200), (60, 255, 220), (255, 230, 80)][int(r.uniform(0, 3))])
            x += bw + 6
    d.rectangle([0, 0, W, top], fill=_mix(c0, (0, 0, 0), 0.45))
    return img


def hazard_line(d, a, b, w):
    d.line([a, b], fill=OL, width=int(w + 8))
    Ls = math.dist(a, b)
    n = max(1, int(Ls / 28))
    for k in range(n):
        p0 = (a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n)
        p1 = (a[0] + (b[0] - a[0]) * (k + 1) / n, a[1] + (b[1] - a[1]) * (k + 1) / n)
        d.line([p0, p1], fill=T["stripe"][k % 2], width=int(w))


def metal_line(d, a, b, w, col=None):
    col = col or T["rail"]
    d.line([a, b], fill=OL, width=int(w + 8))
    d.line([a, b], fill=col, width=int(w))
    d.line([(a[0], a[1] - w * 0.2), (b[0], b[1] - w * 0.2)], fill=tuple(min(255, c + 50) for c in col), width=max(2, int(w * 0.3)))


def level_background(base, lv):
    img = base.copy()
    d = ImageDraw.Draw(img)
    for a, b, rad in lv.statics:
        metal_line(d, a, b, 2 * rad + 4)
    for (x, y) in lv.pegs:
        d.ellipse([x - 13, y - 13, x + 13, y + 13], fill=OL)
        d.ellipse([x - 10, y - 10, x + 10, y + 10], fill=(185, 190, 200))
        d.ellipse([x - 5, y - 7, x + 2, y - 2], fill=(240, 240, 245))
    for (x, y) in lv.bumpers:
        d.ellipse([x - 38, y - 38, x + 38, y + 38], fill=OL)
        d.ellipse([x - 34, y - 34, x + 34, y + 34], fill=T["bump"])
        d.ellipse([x - 20, y - 20, x + 20, y + 20], fill=_mix(T["bump"], (255, 255, 255), 0.45))
    W, H, SY = L["W"], L["H"], L["SHRED_Y"]
    d.rectangle([0, SY, W, H], fill=T["pit_bg"])
    if T["pit_fx"] == "gears":
        sz = min(68, H - SY)
        for x in range(0, W, 60):
            d.ellipse([x - 4, SY + (H - SY - sz) / 2, x + 64, SY + (H - SY + sz) / 2], fill=(60, 60, 66), outline=OL, width=4)
    d.line([(0, SY), (W, SY)], fill=OL, width=6)
    return img


# ---------------------------------------------------------------- audio
def build_audio(seconds, events, rng):
    N = int(seconds * SR) + SR
    out = np.zeros(N)

    def add(sig, at, g=1.0):
        i = int(at * SR)
        j = min(N, i + len(sig))
        if 0 <= i < N:
            out[i:j] += sig[: j - i] * g

    def tone(f, d, dec=6, sq=False):
        n = int(d * SR)
        ph = 2 * np.pi * f * np.arange(n) / SR
        return (np.sign(np.sin(ph)) * 0.5 if sq else np.sin(ph)) * np.exp(-np.arange(n) / SR * dec)

    def noise(d, dec=8):
        n = int(d * SR)
        return rng.uniform(-1, 1, n) * np.exp(-np.arange(n) / SR * dec)

    beat = 60 / 128
    kick = np.sin(2 * np.pi * np.cumsum(np.geomspace(150, 45, int(0.25 * SR))) / SR) * np.exp(-np.arange(int(0.25 * SR)) / SR * 12)
    roots = [55, 55, 73.4, 65.4]
    k, tt = 0, 0.5
    while tt < seconds - 0.5:
        add(kick, tt, 0.55)
        add(noise(0.05, 70) * 0.5, tt + beat / 2, 0.3)
        if k % 2:
            add(noise(0.15, 25), tt, 0.25)
        add(tone(roots[(k // 8) % 4] * 2, beat * 0.9, 4, True), tt, 0.08)
        tt += beat
        k += 1
    q, last_q = {}, -1
    for at, kind, extra in events:
        if kind == "level":
            add(tone(220, 0.6, 3, True), at, 0.25)
        elif kind == "go":
            add(tone(880, 0.4, 5), at, 0.4)
        elif kind == "qualify" and at - last_q > 0.06:          # don't machine-gun when 90 balls qualify
            n = q.get(extra, 0)
            q[extra] = n + 1
            add(tone(660 * 2 ** ((n % 24) / 24), 0.18, 14), at, 0.3)
            last_q = at
        elif kind == "gate":
            add(noise(0.4, 10) * 0.8 + tone(90, 0.4, 8), at, 0.7)
        elif kind == "shred":
            add(noise(0.3, 7) * 0.5 + tone(70, 0.3, 6, True) * 0.3, at, 0.35)
        elif kind == "win":
            for j, f in enumerate([523, 659, 784, 1046]):
                add(tone(f, 0.6 if j < 3 else 1.5, 3, True), at + j * 0.14, 0.25)
    out = np.tanh(out * 1.1)
    out /= max(1e-6, np.abs(out).max()) / 0.85
    return (out * 32767).astype(np.int16)


# ---------------------------------------------------------------- the show
def render_video(seed, out_dir, n_start=32, layout="portrait", preview=False, render=True, name=None, theme="factory"):
    """render=False runs only the physics (for testing that no level ever gets stuck)."""
    L.clear()
    L.update(LAYOUTS[layout])
    T.clear()
    T.update(THEMES[theme])
    W, H = L["W"], L["H"]
    long_form = layout == "landscape"
    rng = np.random.default_rng(seed)
    pyr = random.Random(seed)              # physics + layout decisions only
    fx = random.Random(seed + 1)           # visual effects (so the test run and the real render match exactly)
    n_start = min(n_start, len(COUNTRIES))
    idx = rng.permutation(len(COUNTRIES))[:n_start]
    start = [COUNTRIES[i] for i in idx]
    alive = list(start)
    info = {c[0]: c for c in alive}
    balls = Balls() if render else None
    base_bg = factory_background(seed) if render else None
    os.makedirs(out_dir, exist_ok=True)
    stem = os.path.join(out_dir, name or f"factory_{seed}")
    silent, wav, mp4 = stem + "_v.mp4", stem + ".wav", stem + ".mp4"
    ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                           "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                           "-pix_fmt", "yuv420p", silent], stdin=subprocess.PIPE) if render else None
    events, frame_no, history, chapters, level_times, paths = [], [0], [], [], [], []
    vt = lambda: frame_no[0] / FPS                         # noqa: E731
    flying, sparks = [], []

    def emit(img):
        if render and (not preview or frame_no[0] % 10 == 0):
            ff.stdin.write(img.tobytes())
        frame_no[0] += 1

    # ---- intro: every country, appearing fast
    intro = 7.0 if long_form else 3.2
    chapters.append((0.0, f"All {n_start} countries"))
    if render:
        cols = max(4, int(math.ceil(math.sqrt(n_start * (W / (H - 330)))))) if long_form else 4
        rows = math.ceil(n_start / cols)
        cell = min((W - 80) / cols, (H - 330) / rows) if long_form else 160
        for f in range(int(intro * FPS)):
            img = base_bg.copy()
            d = ImageDraw.Draw(img)
            p = 1 + 0.05 * math.sin(f * 0.25)
            if long_form:
                text_c(d, (W / 2, 70), f"ALL {n_start} COUNTRIES", 90 * p, (255, 220, 50), stroke=8)
                text_c(d, (W / 2, 150), f"Find your country - only ONE survives the {T['title'].upper()}!", 44, (255, 255, 255), stroke=5)
            else:
                text_c(d, (W / 2, 90), "FIND YOUR", 84 * p, (255, 255, 255), stroke=8)
                text_c(d, (W / 2, 190), "COUNTRY!", 110 * p, (255, 220, 50), stroke=9)
            shown = int(min(n_start, (f + 1) * n_start / (intro * FPS * 0.6)))
            for k, (cc, lab, nm) in enumerate(start[:shown]):
                if long_form:
                    cx = W / 2 + ((k % cols) - (cols - 1) / 2) * cell
                    cy = 230 + (k // cols + 0.5) * cell
                    spr = balls.sprite(cc, cell * 0.36)
                    img.paste(spr, (int(cx - spr.width / 2), int(cy - spr.height / 2 - cell * 0.1)), spr)
                    d.text((cx, cy + cell * 0.32), lab, font=font(max(12, cell * 0.2)), fill=(255, 255, 255), anchor="mm",
                           stroke_width=3, stroke_fill=OL)
                else:
                    cx = W / 2 + ((k % 4) - 1.5) * 235
                    cy = 400 + (k // 4) * 160
                    spr = balls.sprite(cc, 56)
                    img.paste(spr, (int(cx - 85), int(cy - spr.height / 2)), spr)
                    d.text((cx - 20, cy), lab, font=font(40), fill=(255, 255, 255), anchor="lm", stroke_width=5, stroke_fill=OL)
            if not long_form:
                text_c(d, (W / 2, 1720), f"Only ONE survives the {T['title'].upper()}", 52, (255, 255, 255), stroke=6, max_w=W - 60)
                text_c(d, (W / 2, 1800), "Comment your country below!", 50, (255, 220, 50), stroke=6)
            emit(img)
    else:
        frame_no[0] += int(intro * FPS)

    li = 0
    while len(alive) > 1:
        n = len(alive)
        # Shorts halve the field each level; long videos remove a third (more levels, 2-3 minutes)
        quota = (n - max(1, round(n / 3))) if (long_form and n > 4) else max(1, n // 2)
        final = quota == 1
        r = ball_radius(n)
        lv = Level(n, quota, r, pyr)
        bg = level_background(base_bg, lv) if render else None
        bodies = {}
        cols = max(1, int((L["X1"] - L["X0"] - 20) // (2 * r + 6)))
        for k, (cc, lab, nm) in enumerate(alive):
            b = pymunk.Body(1, pymunk.moment_for_circle(1, 0, r))
            b.position = (L["X0"] + 14 + r + (k % cols) * (2 * r + 6) + pyr.uniform(-3, 3),
                          L["HOLD_Y"] - r - 8 - (k // cols) * (2 * r + 4))
            s = pymunk.Circle(b, r)
            s.elasticity, s.friction = 0.35, 0.6
            lv.space.add(b, s)
            bodies[cc] = (b, s)
        qualified, eliminated = [], []
        t, phase, phase_t, run_t = 0.0, "card", 0.0, 0.0
        events.append((vt(), "level", li))
        chapters.append((vt(), "THE FINAL" if final else f"Level {li + 1}: {n} countries, top {quota} qualify"))
        still = {}
        while True:
            dt = 1 / FPS
            if phase == "card" and phase_t > (2.0 if long_form else 1.1):
                phase, phase_t = "count", 0.0
            elif phase == "count" and phase_t > 0.9:
                lv.release()
                events.append((vt(), "go", li))
                phase, phase_t = "run", 0.0
            elif phase == "run":
                for cc, (b, s) in list(bodies.items()):
                    if b.position.y > L["GATE_Y"] + r + 4 and len(qualified) < quota:
                        lv.space.remove(b, s)
                        del bodies[cc]
                        qualified.append(cc)
                        flying.append([cc, b.position.x, b.position.y, vt(), len(qualified) - 1, quota, r])
                        events.append((vt(), "qualify", li))
                if len(qualified) >= quota:
                    lv.close_gates()
                    events.append((vt(), "gate", li))
                    run_t = phase_t
                    phase, phase_t = "close", 0.0
                for cc, (b, s) in bodies.items():          # invisible safety: free a ball that is perfectly still
                    if b.velocity.length < 10:
                        still[cc] = still.get(cc, 0) + dt
                        if still[cc] > 1.5:
                            b.apply_impulse_at_local_point((pyr.uniform(-250, 250), -pyr.uniform(150, 350)))
                            still[cc] = 0
                    else:
                        still[cc] = 0
            elif phase == "close" and phase_t > 0.5:
                lv.open_trapdoor()
                if render:
                    bg = level_background(base_bg, lv)
                phase, phase_t = "drop", 0.0
            elif phase == "drop":
                for cc, (b, s) in list(bodies.items()):
                    if b.position.y > L["SHRED_Y"] + 15:
                        lv.space.remove(b, s)
                        del bodies[cc]
                        eliminated.append(cc)
                        events.append((vt(), "shred", li))
                        if render:
                            for _ in range(10 if n > 60 else 18):
                                a = fx.uniform(0, 2 * math.pi)
                                sp = fx.uniform(200, 700)
                                sparks.append([b.position.x, L["SHRED_Y"] + 15, math.cos(a) * sp, -abs(math.sin(a)) * sp, vt()])
                if not bodies or phase_t > 3.0:
                    eliminated += list(bodies)
                    bodies = {}
                    phase, phase_t = "done", 0.0
            elif phase == "done" and phase_t > 0.6:
                break
            if phase == "run" and phase_t > 90:
                where = sorted((int(b.position.x), int(b.position.y), int(b.velocity.length)) for b, _ in bodies.values())[:6]
                raise RuntimeError(f"level {li + 1} did not finish (seed {seed}) kinds={lv.kinds} r={r} "
                                   f"q={len(qualified)}/{quota} left={len(bodies)} at={where}")
            for _ in range(SUB):
                lv.step(t, dt / SUB)
                t += dt / SUB
            phase_t += dt
            if render:
                draw_frame(lv, bg, bodies, balls, info, r, qualified, quota, li, n, final, phase, phase_t,
                           flying, sparks, vt(), emit, W, H, long_form)
            else:
                frame_no[0] += 1
        if long_form and eliminated and len(alive) > 2:         # recap: who just got shredded
            recap_s = 2.6 + min(1.5, len(eliminated) / 40)
            if render:
                draw_recap(eliminated, li, base_bg, balls, info, emit, W, H, recap_s)
            else:
                frame_no[0] += int(recap_s * FPS)
        level_times.append(round(run_t, 1))
        paths.append(lv.kinds)
        history.append({"level": li + 1, "qualified": [info[c][2] for c in qualified], "eliminated": [info[c][2] for c in eliminated]})
        alive = [info[c] for c in qualified]
        li += 1

    champ = alive[0]
    events.append((vt(), "win", 0))
    chapters.append((vt(), f"Champion: {champ[2].title()}"))
    if render:
        draw_outro(champ, base_bg, balls, emit, W, H, long_form, pyr)
        ff.stdin.close()
        ff.wait()
    else:
        frame_no[0] += int(5.0 * FPS)
    total = frame_no[0] / FPS
    meta = {"seed": seed, "style": "factory", "world": theme, "place": T["title"], "pit": T["pit"], "paths": paths, "character": "flags", "layout": layout,
            "countries": [c[2] for c in start], "runners": [c[2] for c in start], "winner": champ[2],
            "eliminated": [[c, f"LEVEL {h['level']}"] for h in history for c in h["eliminated"]],
            "levels": len(history), "level_run_seconds": level_times, "duration_s": round(total, 1),
            "chapters": "\n".join(f"{int(t_ // 60)}:{int(t_ % 60):02d} {name_}" for t_, name_ in chapters)}
    if not render:
        return None, meta
    audio = build_audio(total, events, rng)
    with wave.open(wav, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes(audio.tobytes())
    vrate = ["-r", str(FPS / 10)] if preview else []
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *vrate, "-i", silent, "-i", wav, "-c:v", "copy", "-c:a", "aac",
                    "-b:a", "160k", "-shortest", "-movflags", "+faststart", mp4], check=True)
    os.remove(silent)
    os.remove(wav)
    meta["file"] = mp4
    if long_form:
        meta["thumbnail"] = stem + ".jpg"
        make_thumbnail(meta["thumbnail"], start, balls, pyr)
    with open(stem + ".json", "w") as fh:
        json.dump(meta, fh, indent=2, ensure_ascii=False)
    return mp4, meta


def draw_frame(lv, bg, bodies, balls, info, r, qualified, quota, li, n, final, phase, phase_t,
               flying, sparks, now, emit, W, H, long_form):
    img = bg.copy()
    d = ImageDraw.Draw(img)
    for a, b, sgn in lv.belts:
        hazard_line(d, a, b, 20)
        Ls = math.dist(a, b)
        for k in range(int(Ls / 40)):
            u = ((k * 40 + now * 280) % Ls) / Ls
            p = (a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u)
            d.ellipse([p[0] - 4, p[1] - 4, p[0] + 4, p[1] + 4], fill=(255, 255, 255))
    for a, b in (lv.funnel_pts if lv.funnel else []):
        hazard_line(d, a, b, 22)
    if lv.hold is not None:
        hazard_line(d, (L["X0"], L["HOLD_Y"]), (L["X1"], L["HOLD_Y"]), 18)
    for gl, gr in lv.gates:
        if lv.closed:
            metal_line(d, (gl - 4, L["GATE_Y"]), (gr + 4, L["GATE_Y"]), 22, (200, 60, 60))
        elif lv.funnel:
            d.rectangle([gl, L["GATE_Y"] - 6, gr, L["GATE_Y"] + 6], fill=(60, 220, 110))
    for kind, b, Lh, sgn, ph in lv.kin:
        if kind == "paddle":
            p0, p1 = b.local_to_world((-Lh, 0)), b.local_to_world((Lh, 0))
            metal_line(d, tuple(p0), tuple(p1), 22, (90, 170, 230))
        elif kind == "flipper":
            p0, p1 = b.local_to_world((0, 0)), b.local_to_world((sgn * Lh, 0))
            metal_line(d, tuple(p0), tuple(p1), 22, (230, 160, 60))
        elif kind == "spinner":
            for a3 in range(3):
                ang = b.angle + a3 * 2 * math.pi / 3
                p1 = (b.position.x + Lh * math.cos(ang), b.position.y + Lh * math.sin(ang))
                metal_line(d, tuple(b.position), p1, 18, _mix(T["bump"], (255, 255, 255), 0.2))
        else:
            for a4 in range(4):
                ang = b.angle + a4 * math.pi / 2
                p1 = (b.position.x + Lh * math.cos(ang), b.position.y + Lh * math.sin(ang))
                metal_line(d, tuple(b.position), p1, 20, (180, 110, 230))
        c = b.position
        d.ellipse([c.x - 14, c.y - 14, c.x + 14, c.y + 14], fill=(240, 240, 245), outline=OL, width=4)
    draw_pit(d, W, H, now)
    show_labels = r >= (40 if not long_form else 30)
    for cc, (b, s) in bodies.items():
        spr = balls.sprite(cc, r, math.degrees(b.angle))
        img.paste(spr, (int(b.position.x - spr.width / 2), int(b.position.y - spr.height / 2)), spr)
        if show_labels:
            d.text((b.position.x, b.position.y + r + 16), info[cc][1], font=font(28), fill=(255, 255, 255),
                   anchor="mm", stroke_width=4, stroke_fill=OL)
    for sp in sparks:
        age = now - sp[4]
        if 0 <= age < 0.8:
            x, y = sp[0] + sp[2] * age, sp[1] + sp[3] * age + 900 * age * age
            d.rectangle([x - 4, y - 4, x + 4, y + 4], fill=_mix(T["spark"], (255, 60, 30), age))
    sparks[:] = [s_ for s_ in sparks if now - s_[4] < 0.8]

    # HUD
    if long_form:
        text_c(d, (W / 2, 45), "WHICH COUNTRY WINS?", 60, (255, 220, 50), stroke=7)
        y_box, sy = 100, 145
    else:
        text_c(d, (W / 2, 62), "WHICH COUNTRY WINS?", 74, (255, 220, 50), stroke=8)
        y_box, sy = 180, 285
    d.rounded_rectangle([40, y_box, 330, y_box + 56], 20, fill=(60, 66, 84))
    text_c(d, (185, y_box + 28), "THE FINAL" if final else f"LEVEL {li + 1}", 34, (255, 255, 255), stroke=0)
    shown_q = [q for q in qualified if not any(f_[0] == q and now - f_[3] < 0.5 for f_ in flying)]
    d.rounded_rectangle([W - 400, y_box, W - 40, y_box + 56], 20, fill=(40, 120, 70))
    text_c(d, (W - 220, y_box + 28), f"QUALIFIED {len(shown_q)}/{quota}", 34, (255, 255, 255), stroke=0)
    strip = quota <= (24 if long_form else 16)
    if strip:
        sz = min(56, (W - 80) / max(1, quota) - 4)
        x0 = W / 2 - (sz + 4) * quota / 2
        for k in range(quota):
            cx = x0 + k * (sz + 4) + sz / 2
            if long_form and abs(cx - W / 2) > W / 2 - 440:
                continue
            if k < len(shown_q):
                spr = balls.sprite(shown_q[k], sz / 2)
                img.paste(spr, (int(cx - spr.width / 2), int(sy - spr.height / 2)), spr)
            else:
                d.ellipse([cx - sz / 2, sy - sz / 2, cx + sz / 2, sy + sz / 2], outline=(110, 116, 130), width=3)
    else:                                                    # many qualifiers: progress bar + the latest flags
        bx0, bx1 = 360, W - 430
        d.rounded_rectangle([bx0, y_box + 14, bx1, y_box + 42], 14, fill=(30, 32, 42))
        d.rounded_rectangle([bx0, y_box + 14, bx0 + (bx1 - bx0) * len(shown_q) / quota, y_box + 42], 14, fill=(60, 220, 110))
        if long_form:
            for k, cc in enumerate(shown_q[-16:]):
                spr = balls.sprite(cc, 18)
                img.paste(spr, (int(bx0 + 10 + k * 42), int(sy - spr.height / 2)), spr)
    for fl in flying:
        age = now - fl[3]
        if 0 <= age < 0.5:
            if strip:
                sz = min(56, (W - 80) / max(1, fl[5]) - 4)
                tx, ty = W / 2 - (sz + 4) * fl[5] / 2 + fl[4] * (sz + 4) + sz / 2, sy
            else:
                sz, tx, ty = 32, W - 220, y_box + 28
            u = age / 0.5
            x, y = fl[1] + (tx - fl[1]) * u, fl[2] + (ty - fl[2]) * u - math.sin(u * math.pi) * 150
            spr = balls.sprite(fl[0], max(8, fl[6] + (sz / 2 - fl[6]) * u))
            img.paste(spr, (int(x - spr.width / 2), int(y - spr.height / 2)), spr)
    flying[:] = [f_ for f_ in flying if now - f_[3] < 0.6]
    cy = (L["HOLD_Y"] + L["FUN_Y"]) / 2
    if phase == "card":
        pop = min(1, phase_t / 0.2)
        bw = 440 if long_form else W / 2 - 90
        d.rounded_rectangle([W / 2 - bw, cy - 150, W / 2 + bw, cy + 150], 40, fill=(15, 15, 22), outline=(255, 220, 50), width=8)
        text_c(d, (W / 2, cy - 60), "THE FINAL" if final else f"LEVEL {li + 1}", 110 * pop, (255, 220, 50), stroke=8)
        text_c(d, (W / 2, cy + 70), f"{n} LEFT  ·  TOP {quota} QUALIFY" if not final else "FIRST THROUGH WINS!", 52, (255, 255, 255), stroke=5)
    elif phase == "count":
        text_c(d, (W / 2, cy), "3" if phase_t < 0.3 else "2" if phase_t < 0.6 else "1", 260, (255, 255, 255), stroke=14)
    elif phase in ("close", "drop") and phase_t < 1.6:
        text_c(d, (W / 2, cy - 40), "GATE CLOSED!" if phase == "close" else "INTO THE " + T["pit"] + "!", 100, (255, 80, 70), stroke=10,
               max_w=W - 60)
        text_c(d, (W / 2, cy + 70), f"{n - quota} ELIMINATED", 60, (255, 255, 255), stroke=6)
    emit(img)


def draw_pit(d, W, H, now):
    SY = L["SHRED_Y"]
    cy0 = SY + (H - SY) / 2
    R1 = min(34, (H - SY) / 2 - 2)
    fx, col = T["pit_fx"], T["pit_col"]
    if fx == "gears":
        for x in range(0, W, 60):
            for k in range(6):
                a = now * 6 * (1 if (x // 60) % 2 else -1) + k * math.pi / 3
                cx = x + 30
                d.polygon([(cx + R1 * math.cos(a), cy0 + R1 * math.sin(a)), (cx + R1 * 0.6 * math.cos(a + 0.3), cy0 + R1 * 0.6 * math.sin(a + 0.3)),
                           (cx + R1 * 0.6 * math.cos(a - 0.3), cy0 + R1 * 0.6 * math.sin(a - 0.3))], fill=(200, 200, 210))
    elif fx in ("lava", "water"):
        base = (255, 110, 10) if fx == "lava" else _mix(T["pit_bg"], (255, 255, 255), 0.25)
        pts = [(x, SY + 14 + 8 * math.sin(x / 50 + now * 4)) for x in range(0, W + 20, 20)]
        d.polygon(pts + [(W, SY + 30), (0, SY + 30)], fill=base)
        d.line(pts, fill=col, width=5)
        for k in range(int(W / 90)):
            ph = (now * 1.3 + k * 0.37) % 1
            x = (k * 97) % W
            d.ellipse([x - 7 * ph - 3, cy0 - 3 - 7 * ph, x + 7 * ph + 3, cy0 + 3 + 7 * ph], outline=col, width=3)
    elif fx == "spikes":
        for x in range(0, W, 40):
            up = 6 * math.sin(now * 5 + x / 70)
            d.polygon([(x, H), (x + 20, SY + 6 + up), (x + 40, H)], fill=col, outline=OL)
    elif fx == "vortex":
        for k in range(14):
            a = now * 3 + k * 0.45
            rx = (k + 1) * W / 30
            d.arc([W / 2 - rx, cy0 - R1 * 0.9, W / 2 + rx, cy0 + R1 * 0.9], math.degrees(a) % 360, math.degrees(a) % 360 + 120,
                  fill=_mix(col, (255, 255, 255), k / 20), width=4)
    else:                                                    # zap
        for k in range(int(W / 120) + 1):
            x0 = k * 120 + 60
            pts = [(x0 + (18 if (j + int(now * 12)) % 2 else -18), SY + 6 + j * (H - SY - 12) / 6) for j in range(7)]
            d.line(pts, fill=col, width=4)
    if H - SY > 100:
        text_c(d, (W / 2, H - 50), T["pit"], 56, (255, 255, 255), stroke=8, sf=_mix(T["pit_bg"], (0, 0, 0), 0.5))


def pick_seed(base_seed, n_start, layout, lo, hi, max_level_s, tries=40, avoid_winners=(), avoid_paths=()):
    """Test-runs the physics (fast, no rendering) and returns the first seed whose video fits [lo, hi] seconds,
    whose slowest level is under max_level_s (flows smoothly), whose champion did not win recently and whose
    machine layout differs from the other videos of the day."""
    best = stale = None
    avoid_winners = set(avoid_winners)
    avoid_paths = {tuple(map(tuple, p)) for p in avoid_paths}
    for k in range(tries):
        s = base_seed * 100 + k
        try:
            _, m = render_video(s, "/tmp", n_start, layout, render=False)
        except RuntimeError:
            continue
        fresh = m["winner"] not in avoid_winners and tuple(map(tuple, m["paths"])) not in avoid_paths
        if not fresh:
            stale = stale or (s, m)
            continue
        ok = lo <= m["duration_s"] <= hi and max(m["level_run_seconds"]) <= max_level_s
        if ok:
            return s, m
        if best is None or max(m["level_run_seconds"]) < max(best[1]["level_run_seconds"]):
            best = (s, m)
    return best or stale


def draw_recap(eliminated, li, base_bg, balls, info, emit, W, H, seconds):
    n = len(eliminated)
    cols = max(6, int(math.ceil(math.sqrt(n * 2.6))))
    rows = math.ceil(n / cols)
    cell = min((W - 120) / cols, (H - 300) / max(1, rows), 150)
    bg = base_bg.copy()
    ov = Image.new("RGB", (W, H), (10, 8, 12))
    bg = Image.blend(bg, ov, 0.75)
    for f in range(int(seconds * FPS)):
        img = bg.copy()
        d = ImageDraw.Draw(img)
        pop = min(1, f / 6)
        text_c(d, (W / 2, 80), f"ELIMINATED IN LEVEL {li + 1}", 76 * pop, (255, 80, 70), stroke=8)
        text_c(d, (W / 2, 160), f"{n} countries fell into the {T['pit']}", 40, (255, 255, 255), stroke=5)
        shown = int(min(n, (f + 1) * n / (FPS * 0.8)))
        for k, cc in enumerate(eliminated[:shown]):
            cx = W / 2 + ((k % cols) - (cols - 1) / 2) * cell
            cy = 240 + (k // cols + 0.5) * cell
            spr = balls.sprite(cc, cell * 0.33)
            img.paste(spr, (int(cx - spr.width / 2), int(cy - spr.height / 2 - cell * 0.1)), spr)
            d.line([(cx - cell * 0.25, cy - cell * 0.35), (cx + cell * 0.25, cy + cell * 0.15)], fill=(255, 60, 60), width=4)
            d.text((cx, cy + cell * 0.3), info[cc][1], font=font(max(12, cell * 0.2)), fill=(230, 230, 230), anchor="mm",
                   stroke_width=3, stroke_fill=OL)
        emit(img)


def draw_outro(champ, base_bg, balls, emit, W, H, long_form, pyr):
    conf = [(pyr.uniform(0, W), pyr.uniform(-H, 0), pyr.uniform(250, 600), pyr.uniform(-80, 80),
             pyr.choice([(235, 59, 59), (52, 120, 246), (46, 204, 113), (250, 204, 21), (255, 255, 255)]), pyr.uniform(0, 6))
            for _ in range(200)]
    name = champ[2]
    for f in range(int(5.0 * FPS)):
        tt = f / FPS
        img = base_bg.copy()
        d = ImageDraw.Draw(img)
        for (cx0, cy0, vy, vx, cc, rot) in conf:
            cx, cy = cx0 + vx * tt, cy0 + vy * tt + 300
            if 0 < cy < H:
                a = rot + tt * 6
                d.polygon([(cx + 14 * math.cos(a + k * 1.57), cy + 7 * math.sin(a + k * 1.57)) for k in range(4)], fill=cc)
        bounce = abs(math.sin(tt * 4)) * 40
        pop = min(1, tt / 0.25)
        if long_form:
            spr = balls.sprite(champ[0], 250, math.sin(tt * 3) * 20)
            img.paste(spr, (int(W * 0.28 - spr.width / 2), int(H * 0.55 - bounce - spr.height / 2)), spr)
            tx = W * 0.68
            text_c(d, (tx, 260), "CHAMPION OF THE WORLD", 64, (255, 220, 50), stroke=8)
            text_c(d, (tx, 420), name, (150 if len(name) < 10 else 100) * pop, (255, 255, 255), stroke=14)
            if tt > 1.0:
                text_c(d, (tx, 620), "Did your country win?", 60, (255, 255, 255), stroke=7)
            if tt > 1.8:
                text_c(d, (tx, 720), "New place every day - Subscribe!", 48, (255, 220, 50), stroke=6)
        else:
            spr = balls.sprite(champ[0], 230, math.sin(tt * 3) * 20)
            img.paste(spr, (int(W / 2 - spr.width / 2), int(1000 - bounce - spr.height / 2)), spr)
            text_c(d, (W / 2, 220), "CHAMPION", 80, (255, 220, 50), stroke=8)
            text_c(d, (W / 2, 380), name, (150 if len(name) < 9 else 100) * pop, (255, 255, 255), stroke=14)
            text_c(d, (W / 2, 520), "WINS THE " + T["title"].upper() + "!", 70 * pop, (255, 220, 50), stroke=8, max_w=W - 60)
            if tt > 1.0:
                text_c(d, (W / 2, 1440), "Did your country win?", 66, (255, 255, 255), stroke=7)
            if tt > 1.8:
                text_c(d, (W / 2, 1530), "New race every day - Subscribe!", 52, (255, 220, 50), stroke=6)
        emit(img)


def make_thumbnail(path, start, balls, pyr):
    W, H = 1920, 1080
    img = Image.new("RGB", (W, H), (25, 28, 40))
    d = ImageDraw.Draw(img)
    for y in range(H):
        d.line([(0, y), (W, y)], fill=_mix(T["bg"][0], T["bg"][1], y / H))
    sample = list(start)
    pyr.shuffle(sample)
    for c in sample[:70]:                                    # a pile of flag balls
        x, y, rr = pyr.uniform(40, W - 40), pyr.uniform(600, H + 40), pyr.uniform(55, 85)
        spr = balls.sprite(c[0], rr)
        img.paste(spr, (int(x - spr.width / 2), int(y - spr.height / 2)), spr)
    text_c(d, (W / 2, 150), f"{len(start)} COUNTRIES", 170, (255, 220, 50), stroke=16)
    text_c(d, (W / 2, 330), "ONLY 1 SURVIVES", 130, (255, 255, 255), stroke=14)
    text_c(d, (W / 2, 470), T["title"].upper(), 90, (255, 90, 70), stroke=10)
    img.resize((1280, 720), Image.LANCZOS).save(path, quality=92)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", default="out")
    ap.add_argument("--long", action="store_true", help="landscape 2-3 min video with all countries")
    ap.add_argument("--countries", type=int, default=None)
    ap.add_argument("--preview", action="store_true")
    ap.add_argument("--theme", default="factory", choices=THEME_NAMES)
    a = ap.parse_args()
    n = a.countries or (len(COUNTRIES) if a.long else 32)
    m = render_video(a.seed, a.out, n, "landscape" if a.long else "portrait", a.preview, theme=a.theme)[1]
    print(json.dumps(m, indent=2, ensure_ascii=False))
