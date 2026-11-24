"""Elastic jelly-blob runners for the 2D renderer.

Gummy blobs that hop with squash & stretch, wobble, and have googly eyes.
Eliminated blobs splat into a puddle. Sprites are drawn at 3x and downscaled, and cached.
"""
import math

import numpy as np
from PIL import Image, ImageDraw

SS = 3
OL = (30, 22, 40, 255)


def _shade(c, k):
    return tuple(max(0, min(255, int(v * k))) for v in c[:3]) + (255,)


def _mix(c, w, t):
    return tuple(int(a + (b - a) * t) for a, b in zip(c[:3], w[:3])) + (255,)


class Jelly:
    STEPS = 24
    DIV = 95
    WIN_S = 3.6

    @staticmethod
    def run_phase(x, s):
        return x * 0.03

    def __init__(self, color, idx, seed):
        r = np.random.default_rng(seed * 31 + idx)
        self.col = tuple(color[:3]) + (255,)
        self.dark = _shade(color, 0.72)
        self.light = _mix(color, (255, 255, 255), 0.25)
        self.wob = r.uniform(0, 6.28)                  # each blob wobbles a bit differently
        self.eye_gap = r.uniform(0.36, 0.46)
        self.cache = {}

    # body outline: an egg shape, squashed/stretched about the ground point and leaned forward
    def _shape(self, a, b, sx, sy, lean, wob_t, grow=0.0, n=72):
        pts = []
        for k in range(n):
            th = 2 * math.pi * k / n
            w = 1 + 0.035 * math.sin(3 * th + wob_t) + 0.02 * math.sin(5 * th - wob_t * 1.3)
            x = (a + grow) * math.cos(th) * w
            y = (b + grow) * math.sin(th) * (1 + 0.12 * math.sin(th)) * w      # wider, flatter bottom
            y = y - b * 1.05                                                    # put bottom on y=0
            x, y = x * sx, y * sy
            x += lean * (-y)                                                    # top leans forward
            pts.append((x, y))
        return pts

    def _params(self, pose, p):
        """returns hop height, sx, sy, lean, look, face"""
        if pose == "run":
            c = math.sin(p)
            h = abs(c)                                   # 0 on ground, 1 at top of hop
            air = h
            if air < 0.18:                               # squash on landing / take-off
                q = 1 - air / 0.18
                sx, sy = 1 + 0.32 * q, 1 - 0.28 * q
            else:                                        # stretch while flying
                q = min(1, (air - 0.18) / 0.5)
                sx, sy = 1 - 0.12 * q, 1 + 0.16 * q
            return 55 * h, sx, sy, 0.18, 1.0, "run"
        if pose == "idle":
            b = math.sin(p)
            return 0, 1 + 0.04 * b, 1 - 0.04 * b, 0.0, 0.6, "idle"
        if pose == "cheer":
            h = abs(math.sin(p))
            q = max(0, 1 - h / 0.2)
            return 60 * h, 1 + 0.3 * q - 0.1 * h, 1 - 0.25 * q + 0.15 * h, 0.0, 0.0, "cheer"
        if pose == "splat":
            return 0, 2.1, 0.28, 0.0, 0.0, "dead"
        return 0, 0.85, 1.2, 0.0, 0.0, "dead"     # limp (flying)

    def sprite(self, pose, s, phase=0.0, angle=0.0, shadow=True):
        pidx = int(round((phase % (2 * math.pi)) / (2 * math.pi) * self.STEPS)) % self.STEPS
        aidx = int(round(angle / (math.pi / 8))) % 16
        key = (pose, round(s, 3), pidx, aidx, shadow)
        if key in self.cache:
            return self.cache[key]
        p = pidx / self.STEPS * 2 * math.pi
        k = s * SS
        size = int(240 * k)
        body = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        d = ImageDraw.Draw(body)
        a, b = 38.0, 40.0
        hop, sx, sy, lean, look, face = self._params(pose, p)
        wob = p * 2 + self.wob
        upright = pose != "limp"
        origin = np.array([size / 2, size * 0.85]) if upright else np.array([size / 2, size / 2])
        yoff = -hop if upright else b * 1.05 * sy * 0.5
        ang = aidx * math.pi / 8 if not upright else 0.0
        ca, sa = math.cos(ang), math.sin(ang)

        def T(pt):
            x, y = pt[0], pt[1] + yoff
            return (origin[0] + (x * ca - y * sa) * k, origin[1] + (x * sa + y * ca) * k)

        if shadow and upright:
            sw = 42 * (1 - 0.45 * hop / 60) * max(sx, 1)
            d.ellipse([origin[0] - sw * k, origin[1] - 6 * k, origin[0] + sw * k, origin[1] + 6 * k], fill=(0, 0, 0, 60))
        # outline, darker body, lighter inner body (gives a jelly rim)
        d.polygon([T(q) for q in self._shape(a, b, sx, sy, lean, wob, grow=3.2)], fill=OL)
        d.polygon([T(q) for q in self._shape(a, b, sx, sy, lean, wob)], fill=self.dark)
        inner = [(x * 0.9, y * 0.9 - 2.5) for x, y in self._shape(a, b, sx, sy, lean, wob)]
        d.polygon([T(q) for q in inner], fill=self.col)

        # gloss highlight on its own layer so it blends
        gl = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        g = ImageDraw.Draw(gl)
        top = lambda fx, fy: T(((fx * a + lean * (b * 2 * sy) * (-fy)) * sx, -b * 1.05 * sy * (1 + fy)))  # noqa: E731
        h1, h2 = top(-0.5, 0.25), top(-0.3, 0.55)
        g.ellipse([min(h1[0], h2[0]) - 3 * k, min(h1[1], h2[1]) - 6 * k, max(h1[0], h2[0]) + 3 * k, max(h1[1], h2[1]) + 6 * k], fill=(255, 255, 255, 120))
        dot = top(-0.62, 0.05)
        g.ellipse([dot[0] - 4 * k, dot[1] - 4 * k, dot[0] + 4 * k, dot[1] + 4 * k], fill=(255, 255, 255, 170))
        body = Image.alpha_composite(body, gl)
        d = ImageDraw.Draw(body)

        # googly eyes + mouth
        er = 11.5
        jig = 1.6 * math.sin(p * 3)
        for i, fx in enumerate((0.05, 0.05 + self.eye_gap * 2)):
            c = top(fx - 0.15, 0.42)
            if face == "dead":
                for sgn in (-1, 1):
                    d.line([(c[0] - 6 * k, c[1] - 6 * k * sgn), (c[0] + 6 * k, c[1] + 6 * k * sgn)], fill=OL, width=int(3.2 * k))
                continue
            if face == "cheer":
                d.arc([c[0] - 8 * k, c[1] - 6 * k, c[0] + 8 * k, c[1] + 8 * k], 200, 340, fill=OL, width=int(3.2 * k))
                continue
            r_ = er * (1.0 if i else 0.92)
            d.ellipse([c[0] - r_ * k - 2 * k, c[1] - r_ * k - 2 * k, c[0] + r_ * k + 2 * k, c[1] + r_ * k + 2 * k], fill=OL)
            d.ellipse([c[0] - r_ * k, c[1] - r_ * k, c[0] + r_ * k, c[1] + r_ * k], fill=(255, 255, 255, 255))
            px, py = c[0] + (4.5 * look + 0.6 * jig) * k, c[1] + (1.5 + jig) * k
            d.ellipse([px - 5.5 * k, py - 5.5 * k, px + 5.5 * k, py + 5.5 * k], fill=OL)
            d.ellipse([px - 1.5 * k - 2 * k, py - 3.5 * k, px + 0.5 * k - 2 * k, py - 1.5 * k], fill=(255, 255, 255, 255))
        m = top(0.35, 0.05)
        if face == "run":
            d.ellipse([m[0] - 5 * k, m[1] - 4 * k, m[0] + 5 * k, m[1] + 6 * k], fill=(110, 20, 40, 255), outline=OL, width=int(2 * k))
        elif face == "cheer":
            d.chord([m[0] - 13 * k, m[1] - 8 * k, m[0] + 13 * k, m[1] + 14 * k], 0, 180, fill=(110, 20, 40, 255), outline=OL, width=int(2.4 * k))
        elif face == "idle":
            d.arc([m[0] - 8 * k, m[1] - 8 * k, m[0] + 8 * k, m[1] + 5 * k], 20, 160, fill=OL, width=int(2.6 * k))
        else:
            d.line([(m[0] - 6 * k, m[1]), (m[0] - 2 * k, m[1] - 2 * k), (m[0] + 2 * k, m[1]), (m[0] + 6 * k, m[1] - 2 * k)], fill=OL, width=int(2.4 * k))

        if pose == "splat":     # jelly droplets around the puddle
            for dx, rr in ((-60, 5), (-48, 3.5), (56, 4.5), (70, 3)):
                c = T((dx, -4))
                d.ellipse([c[0] - rr * k - 2 * k, c[1] - rr * k - 2 * k, c[0] + rr * k + 2 * k, c[1] + rr * k + 2 * k], fill=OL)
                d.ellipse([c[0] - rr * k, c[1] - rr * k, c[0] + rr * k, c[1] + rr * k], fill=self.col)

        out = body.resize((size // SS, size // SS), Image.LANCZOS)
        res = (out, (origin[0] / SS, origin[1] / SS))
        self.cache[key] = res
        return res

    def paste(self, img, x, y, pose, s, phase=0.0, angle=0.0, shadow=True):
        spr, (ax, ay) = self.sprite(pose, s, phase, angle, shadow)
        img.paste(spr, (int(x - ax), int(y - ay)), spr)
