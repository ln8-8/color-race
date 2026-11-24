"""More 2D racer characters: Duck, Car, Marble + the registry of all 2D character types.

Every character class has the same interface:
  paste(img, x, ground_y, pose, s, phase=0, angle=0, shadow=True)
  poses: "run", "idle", "cheer", "limp" (flying, rotated by angle), "splat" (eliminated, lying on the ground)
  DIV (lane height / DIV = scale), WIN_S (scale in the outro), run_phase(x, s)
"""
import math

import numpy as np
from PIL import Image, ImageDraw

SS = 3
OL = (30, 22, 40, 255)


def shade(c, k):
    return tuple(max(0, min(255, int(v * k))) for v in c[:3]) + (255,)


def mix(c, w, t):
    return tuple(int(a + (b - a) * t) for a, b in zip(c[:3], w[:3])) + (255,)


class Base2D:
    STEPS = 24
    SIZE = 200          # sprite canvas size in units

    def __init__(self, color, idx, seed):
        self.col = tuple(color[:3]) + (255,)
        self.rng = np.random.default_rng(seed * 31 + idx)
        self.cache = {}

    def sprite(self, pose, s, phase=0.0, angle=0.0, shadow=True):
        pidx = int(round((phase % (2 * math.pi)) / (2 * math.pi) * self.STEPS)) % self.STEPS
        aidx = int(round(angle / (math.pi / 8))) % 16
        key = (pose, round(s, 3), pidx, aidx, shadow)
        if key in self.cache:
            return self.cache[key]
        k = s * SS
        size = int(self.SIZE * k)
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        upright = pose != "limp"
        origin = np.array([size / 2, size * 0.8]) if upright else np.array([size / 2, size / 2])
        ang = 0.0 if upright else aidx * math.pi / 8
        self._k, self._origin, self._ang, self._pivot = k, origin, ang, (0.0, 0.0) if upright else self.CENTER
        d = ImageDraw.Draw(img)
        if shadow and upright and pose != "splat":
            w = self.SHADOW_W
            d.ellipse([origin[0] - w * k, origin[1] - 6 * k, origin[0] + w * k, origin[1] + 6 * k], fill=(0, 0, 0, 65))
        self.draw(d, img, pose, pidx / self.STEPS * 2 * math.pi)
        out = img.resize((size // SS, size // SS), Image.LANCZOS)
        res = (out, (origin[0] / SS, origin[1] / SS))
        self.cache[key] = res
        return res

    def T(self, x, y, rot=0.0, about=(0.0, 0.0)):
        """unit coords (y up negative) -> canvas, with an optional local rotation about a point"""
        if rot:
            cx, cy = about
            c, s_ = math.cos(rot), math.sin(rot)
            x, y = cx + (x - cx) * c - (y - cy) * s_, cy + (x - cx) * s_ + (y - cy) * c
        px, py = self._pivot
        x, y = x - px, y - py
        c, s_ = math.cos(self._ang), math.sin(self._ang)
        k = self._k
        return (self._origin[0] + (x * c - y * s_) * k, self._origin[1] + (x * s_ + y * c) * k)

    def ell(self, d, cx, cy, a, b, fill, rot=0.0, about=(0.0, 0.0), outline=True, n=40):
        pts = [self.T(cx + a * math.cos(t), cy + b * math.sin(t), rot, about) for t in np.linspace(0, 2 * math.pi, n, endpoint=False)]
        if outline:
            ptso = [self.T(cx + (a + 2.6) * math.cos(t), cy + (b + 2.6) * math.sin(t), rot, about) for t in np.linspace(0, 2 * math.pi, n, endpoint=False)]
            d.polygon(ptso, fill=OL)
        d.polygon(pts, fill=fill)

    def poly(self, d, pts, fill, rot=0.0, about=(0.0, 0.0), outline=True):
        P = [self.T(x, y, rot, about) for x, y in pts]
        d.polygon(P, fill=fill, outline=OL if outline else None, width=int(2.6 * self._k) if outline else 0)

    def eye(self, d, x, y, r, face, rot=0.0, about=(0.0, 0.0), look=0.35):
        if face == "dead":
            for sg in (-1, 1):
                d.line([self.T(x - r * 0.7, y - r * 0.7 * sg, rot, about), self.T(x + r * 0.7, y + r * 0.7 * sg, rot, about)], fill=OL, width=int(2.8 * self._k))
            return
        if face == "cheer":
            pts = [self.T(x + r * math.cos(t), y + r * 0.6 * math.sin(t), rot, about) for t in np.linspace(math.pi, 2 * math.pi, 10)]
            d.line(pts, fill=OL, width=int(2.8 * self._k), joint="curve")
            return
        self.ell(d, x, y, r, r * 1.1, (255, 255, 255, 255), rot, about)
        self.ell(d, x + r * look, y + r * 0.1, r * 0.5, r * 0.55, OL, rot, about, outline=False)
        self.ell(d, x + r * look - r * 0.2, y - r * 0.15, r * 0.15, r * 0.15, (255, 255, 255, 255), rot, about, outline=False)

    def paste(self, img, x, y, pose, s, phase=0.0, angle=0.0, shadow=True):
        spr, (ax, ay) = self.sprite(pose, s, phase, angle, shadow)
        img.paste(spr, (int(x - ax), int(y - ay)), spr)


# ---------------------------------------------------------------------------- duck
class Duck(Base2D):
    DIV = 100
    WIN_S = 3.3
    CENTER = (0.0, -45.0)
    SHADOW_W = 36

    @staticmethod
    def run_phase(x, s):
        return x * 0.07

    def __init__(self, color, idx, seed):
        super().__init__(color, idx, seed)
        self.belly = mix(self.col, (255, 255, 255), 0.5)
        self.wing = shade(self.col, 0.78)
        self.orange = (255, 150, 30, 255)
        self.hat = bool(self.rng.random() < 0.35)

    def draw(self, d, img, pose, p):
        face = {"run": "run", "idle": "idle", "cheer": "cheer"}.get(pose, "dead")
        if pose == "splat":      # flipped on its back, feet up
            self._ang, self._pivot = math.pi, (0.0, -45.0)
            self._origin = self._origin + np.array([0, -38 * self._k])
            p, pose = 0.0, "limp"
        bob = -5 * abs(math.sin(p)) if pose == "run" else (-30 * abs(math.sin(p)) if pose == "cheer" else 0)
        wad = 0.13 * math.sin(p) if pose == "run" else 0.0
        ab = (0.0, 0.0)
        for side, ph in (("back", p + math.pi), ("front", p)):          # legs + feet
            fx = 12 * math.sin(ph) if pose == "run" else (6 if side == "front" else -6)
            lift = max(0, -6 * math.cos(ph)) if pose == "run" else 0
            col = shade(self.orange, 0.8 if side == "back" else 1)
            d.line([self.T(fx * 0.4, -16 + bob * 0.3), self.T(fx, -3 - lift)], fill=OL, width=int(8 * self._k))
            d.line([self.T(fx * 0.4, -16 + bob * 0.3), self.T(fx, -3 - lift)], fill=col, width=int(4 * self._k))
            self.poly(d, [(fx - 4, -1 - lift), (fx + 14, -1 - lift), (fx + 2, -9 - lift)], col)
        rot = wad
        self.poly(d, [(-30, -52 + bob), (-50, -70 + bob), (-40, -42 + bob)], self.col, rot, ab)         # tail
        self.ell(d, 0, -44 + bob, 37, 28, self.col, rot, ab)                                            # body
        self.ell(d, 10, -36 + bob, 24, 16, self.belly, rot, ab, outline=False)                          # belly
        flap = (0.5 * math.sin(p * 2) if pose == "run" else (-1.2 + 0.4 * math.sin(p * 4) if pose == "cheer" else 0.1))
        self.ell(d, -8, -48 + bob, 21, 12, self.wing, rot + flap, (4, -50 + bob))                       # wing
        self.ell(d, 22, -82 + bob, 20, 19, self.col, rot, ab)                                           # head
        self.poly(d, [(36, -84 + bob), (58, -79 + bob), (37, -72 + bob)], self.orange, rot, ab)         # beak
        if face == "run":
            self.poly(d, [(36, -74 + bob), (52, -71 + bob), (37, -68 + bob)], shade(self.orange, 0.75), rot, ab)
        self.eye(d, 28, -88 + bob, 6.5, face, rot, ab)
        self.ell(d, 30, -74 + bob, 4, 2.5, (255, 140, 160, 255), rot, ab, outline=False)              # blush
        if self.hat:                                                                                   # tiny party hat
            self.poly(d, [(10, -98 + bob), (30, -100 + bob), (17, -124 + bob)], (255, 255, 255, 255), rot, ab)
            self.ell(d, 17, -125 + bob, 4, 4, (255, 210, 40, 255), rot, ab)


# ---------------------------------------------------------------------------- car
class Car(Base2D):
    DIV = 82
    WIN_S = 3.2
    CENTER = (0.0, -38.0)
    SHADOW_W = 58

    @staticmethod
    def run_phase(x, s):
        return x / (14 * s)          # wheel turns with the distance

    def __init__(self, color, idx, seed):
        super().__init__(color, idx, seed)
        self.stripe = bool(self.rng.random() < 0.5)
        self.num = int(self.rng.integers(1, 99))

    def draw(self, d, img, pose, p):
        face = {"run": "run", "idle": "idle", "cheer": "cheer"}.get(pose, "dead")
        if pose == "splat":       # flipped onto its roof
            self._ang, self._pivot = math.pi, (0.0, -38.0)
            self._origin = self._origin + np.array([0, -38 * self._k])
            pose = "limp"
        bounce = -2.5 * abs(math.sin(p * 2)) if pose == "run" else 0
        tilt = -0.28 if pose == "cheer" else 0.0                   # wheelie
        ab = (-34.0, -14.0)
        # exhaust puffs
        if pose == "run":
            for j in range(3):
                q = (p / (2 * math.pi) * 3 + j / 3) % 1
                r = 5 + 9 * q
                self.ell(d, -66 - 22 * q, -22 - 10 * q, r, r, mix((150, 150, 155), (255, 255, 255), q), tilt, ab, outline=False)
        # body
        body = [(-58, -18 + bounce), (58, -18 + bounce), (60, -34 + bounce), (50, -46 + bounce), (-54, -46 + bounce), (-60, -34 + bounce)]
        self.poly(d, body, self.col, tilt, ab)
        cab = [(-34, -46 + bounce), (-22, -74 + bounce), (20, -74 + bounce), (38, -46 + bounce)]
        self.poly(d, cab, self.col, tilt, ab)
        win = [(-27, -49 + bounce), (-18, -69 + bounce), (17, -69 + bounce), (31, -49 + bounce)]
        self.poly(d, win, (190, 225, 255, 255), tilt, ab, outline=False)
        if self.stripe:
            self.poly(d, [(-56, -36 + bounce), (58, -36 + bounce), (58, -30 + bounce), (-58, -30 + bounce)], (255, 255, 255, 255), tilt, ab, outline=False)
        self.ell(d, -8, -32 + bounce, 9, 9, (255, 255, 255, 255), tilt, ab)          # number roundel
        self.ell(d, 54, -38 + bounce, 5, 4, (255, 230, 90, 255), tilt, ab)          # headlight
        self.poly(d, [(-60, -40 + bounce), (-55, -40 + bounce), (-55, -32 + bounce), (-60, -32 + bounce)], (230, 40, 40, 255), tilt, ab)
        # eyes on the windshield
        self.eye(d, 4, -59 + bounce, 7, face, tilt, ab, look=0.4)
        self.eye(d, 20, -59 + bounce, 7.5, face, tilt, ab, look=0.4)
        # wheels with spokes
        for wx in (-34, 34):
            self.ell(d, wx, -14, 14, 14, (35, 35, 40, 255), tilt, ab)
            self.ell(d, wx, -14, 7, 7, (190, 190, 200, 255), tilt, ab, outline=False)
            for j in range(4):
                a = p + j * math.pi / 2
                d.line([self.T(wx, -14, tilt, ab), self.T(wx + 7 * math.cos(a), -14 + 7 * math.sin(a), tilt, ab)], fill=OL, width=int(2 * self._k))


# ---------------------------------------------------------------------------- marble
class Marble(Base2D):
    DIV = 80
    WIN_S = 4.0
    CENTER = (0.0, -32.0)
    SHADOW_W = 30
    R = 32

    @staticmethod
    def run_phase(x, s):
        return x / (32 * s)

    def __init__(self, color, idx, seed):
        super().__init__(color, idx, seed)
        self.swirl = mix(self.col, (255, 255, 255), 0.75)
        self.dark = shade(self.col, 0.65)
        self.twist = self.rng.uniform(1.5, 3.0)

    def draw(self, d, img, pose, p):
        R = self.R
        if pose == "splat":       # shattered glass shards
            r = np.random.default_rng(int(self.twist * 1000))
            for j in range(7):
                cx, sz = (j - 3) * 20 + r.uniform(-5, 5), r.uniform(12, 20)
                pts = [(cx + sz * math.cos(a), -sz * 0.9 * abs(math.sin(a)) - 1) for a in np.linspace(0, math.pi, 4)]
                self.poly(d, pts, self.col if j % 2 else self.swirl)
            return
        hop = -40 * abs(math.sin(p)) if pose == "cheer" else 0
        roll = p if pose in ("run", "limp") else 0.0
        cy = -R + hop
        self.ell(d, 0, cy, R, R, self.dark)
        self.ell(d, -2, cy - 2, R - 4, R - 4, self.col, outline=False)
        for j in range(2):                                     # glass swirls that turn as it rolls
            pts = []
            for t in np.linspace(-1, 1, 18):
                ang = roll + j * math.pi + t * self.twist
                rr = (R - 8) * abs(t)
                pts.append(self.T(rr * math.cos(ang), cy + rr * math.sin(ang)))
            d.line(pts, fill=self.swirl, width=int(6 * self._k), joint="curve")
        layer = Image.new("RGBA", img.size, (0, 0, 0, 0))     # glossy highlight
        g = ImageDraw.Draw(layer)
        a, b = self.T(-R * 0.55, cy - R * 0.62), self.T(-R * 0.1, cy - R * 0.3)
        g.ellipse([min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1])], fill=(255, 255, 255, 170))
        c = self.T(R * 0.45, cy + R * 0.5)
        g.ellipse([c[0] - 3 * self._k, c[1] - 3 * self._k, c[0] + 3 * self._k, c[1] + 3 * self._k], fill=(255, 255, 255, 120))
        img.alpha_composite(layer)
        if pose == "limp":                                   # cracks
            for a0 in (0.3, 2.2, 4.0):
                d.line([self.T(0, cy), self.T(R * 0.5 * math.cos(a0), cy + R * 0.5 * math.sin(a0)),
                        self.T(R * 0.95 * math.cos(a0 + 0.3), cy + R * 0.95 * math.sin(a0 + 0.3))], fill=OL, width=int(2.4 * self._k))
        if pose == "cheer":
            for j in range(4):
                a = j * math.pi / 2 + p
                sx, sy = 1.35 * R * math.cos(a), cy + 1.35 * R * math.sin(a)
                self.poly(d, [(sx, sy - 6), (sx + 2, sy - 2), (sx + 6, sy), (sx + 2, sy + 2), (sx, sy + 6), (sx - 2, sy + 2), (sx - 6, sy), (sx - 2, sy - 2)], (255, 230, 80, 255), outline=False)


def character_classes():
    from jelly2d import Jelly
    from toon2d import Toon
    return {"jelly": Jelly, "person": Toon, "duck": Duck, "car": Car, "marble": Marble}
