"""Cartoon people for the 2D renderer (side view, rounded limbs, faces, hair, shirt, shorts, sneakers).
Sprites are drawn at 3x and downscaled (smooth edges), and cached."""
import math

import numpy as np
from PIL import Image, ImageDraw

SS = 3
OL = (28, 24, 34, 255)
SKINS = [(255, 219, 172), (241, 194, 125), (224, 172, 105), (198, 134, 66), (141, 85, 36), (255, 205, 160)]
HAIRS = [(40, 28, 20), (90, 55, 30), (20, 20, 24), (200, 150, 60), (150, 60, 30), (60, 40, 35)]
SHORTS = [(35, 40, 70), (30, 30, 34), (60, 60, 66), (245, 245, 245), (25, 60, 50)]
STYLES = ["short", "pony", "bun", "buzz", "curly"]


def _shade(c, k):
    return tuple(max(0, min(255, int(v * k))) for v in c[:3]) + (255,)


def _rgba(c):
    return tuple(c[:3]) + (255,)


class Toon:
    DIV = 128          # lane height / DIV = sprite scale
    WIN_S = 2.9        # scale of the winner in the outro

    @staticmethod
    def run_phase(x, s):
        return x * 0.045

    def __init__(self, color, idx, seed):
        r = np.random.default_rng(seed * 31 + idx)
        self.shirt = _rgba(color)
        self.skin = _rgba(SKINS[int(r.integers(len(SKINS)))])
        self.hair = _rgba(HAIRS[int(r.integers(len(HAIRS)))])
        self.shorts = _rgba(SHORTS[int(r.integers(len(SHORTS)))])
        self.style = STYLES[int(r.integers(len(STYLES)))]
        if sum(color[:3]) > 600 and self.shorts[0] > 200:
            self.shorts = _rgba(SHORTS[0])
        self.cache = {}

    @staticmethod
    def _joints(pose, p):
        J = {}
        lean = {"run": 0.24, "idle": 0.02, "cheer": -0.04, "limp": 0.0}[pose]
        hip = np.array([0.0, 0.0])
        legs, arms = {}, {}
        for side, q in (("back", p + math.pi), ("front", p)):
            if pose == "run":
                th = 0.85 * math.sin(q)
                flex = 0.25 + 1.35 * max(0.0, math.cos(q))
                ua = 0.95 * math.sin(q + math.pi)
                fa = ua + 1.75
            elif pose == "idle":
                th, flex = (0.07 if side == "front" else -0.07), 0.06
                ua = 0.12 if side == "front" else -0.12
                fa = ua + 0.35
            elif pose == "cheer":
                th, flex = (0.1 if side == "front" else -0.1), 0.1
                ua = math.pi + (0.75 if side == "front" else -0.75) + 0.12 * math.sin(p * 2 + (side == "back"))
                fa = ua + (0.35 if side == "front" else -0.35)
            else:
                th, flex = (0.3 if side == "front" else -0.25), 0.25
                ua = 1.3 if side == "front" else -1.2
                fa = ua + 0.4
            knee = hip + 36 * np.array([math.sin(th), math.cos(th)])
            sa = th - flex
            ankle = knee + 34 * np.array([math.sin(sa), math.cos(sa)])
            toe = ankle + 15 * np.array([math.cos(sa), -math.sin(sa)])
            legs[side] = (hip, knee, ankle, toe)
            arms[side] = (ua, fa)
        up = np.array([math.sin(lean), -math.cos(lean)])
        breath = 1.2 * math.sin(p) if pose == "idle" else 0.0
        sh = hip + 50 * up + np.array([0, breath])
        for side in ("back", "front"):
            ua, fa = arms[side]
            el = sh + 26 * np.array([math.sin(ua), math.cos(ua)])
            hand = el + 23 * np.array([math.sin(fa), math.cos(fa)])
            arms[side] = (sh, el, hand)
        J["hip"], J["sh"], J["legs"], J["arms"] = hip, sh, legs, arms
        J["neck"] = sh + 7 * up
        J["head"] = sh + 27 * up + np.array([4, 0])
        return J

    @staticmethod
    def _seg(d, pts, w, fill, ow):
        pts = [tuple(p) for p in pts]
        for col, ww in ((OL, w + 2 * ow), (fill, w)):
            d.line(pts, fill=col, width=int(ww), joint="curve")
            for p in (pts[0], pts[-1]):
                r = ww / 2
                d.ellipse([p[0] - r, p[1] - r, p[0] + r, p[1] + r], fill=col)

    def _draw(self, d, J, k, tf, face):
        ow = 2.6 * k
        P = tf

        def limb_leg(side, dark):
            hip, knee, ankle, toe = J["legs"][side]
            self._seg(d, [P(hip), P(knee), P(ankle)], 13 * k, _shade(self.skin, dark), ow)
            self._seg(d, [P(ankle), P(toe)], 10 * k, _shade((250, 250, 250), dark), ow)
            self._seg(d, [P(hip), P(hip + 0.3 * (knee - hip))], 16 * k, _shade(self.shorts, dark), ow)

        def limb_arm(side, dark):
            sh, el, hand = J["arms"][side]
            self._seg(d, [P(sh), P(el), P(hand)], 10 * k, _shade(self.skin, dark), ow)
            self._seg(d, [P(sh), P(sh + 0.42 * (el - sh))], 14 * k, _shade(self.shirt, dark), ow)

        limb_arm("back", 0.8)
        limb_leg("back", 0.8)
        hip, sh = J["hip"], J["sh"]
        self._seg(d, [P(hip), P(sh)], 30 * k, self.shirt, ow)
        self._seg(d, [P(hip + 0.02 * (sh - hip)), P(hip + 0.22 * (sh - hip))], 31 * k, self.shorts, ow)
        limb_leg("front", 1.0)
        self._seg(d, [P(J["sh"]), P(J["neck"])], 11 * k, self.skin, ow)
        self._head(d, P(J["head"]), 19 * k, ow, tf, face)
        limb_arm("front", 1.0)

    def _head(self, d, c, r, ow, tf, face):
        rot = tf.angle
        fwd = np.array([math.cos(rot), math.sin(rot)])
        upv = np.array([math.sin(rot), -math.cos(rot)])
        at = lambda fx, fy: c + fwd * (fx * r) - upv * (fy * r)   # noqa: E731

        def circ(p, rr, fill):
            d.ellipse([p[0] - rr - ow, p[1] - rr - ow, p[0] + rr + ow, p[1] + rr + ow], fill=OL)
            d.ellipse([p[0] - rr, p[1] - rr, p[0] + rr, p[1] + rr], fill=fill)

        hair_back = {"pony": (at(-1.15, 0.05), 0.45), "bun": (at(-0.55, -0.95), 0.42), "curly": (at(-0.6, -0.55), 0.62)}
        if self.style in hair_back:
            p, rr = hair_back[self.style]
            circ(p, rr * r, self.hair)
        nose = at(0.98, 0.1)
        d.ellipse([c[0] - r - ow, c[1] - r - ow, c[0] + r + ow, c[1] + r + ow], fill=OL)
        d.ellipse([nose[0] - 0.2 * r - ow, nose[1] - 0.2 * r - ow, nose[0] + 0.2 * r + ow, nose[1] + 0.2 * r + ow], fill=OL)
        d.ellipse([c[0] - r, c[1] - r, c[0] + r, c[1] + r], fill=self.skin)
        d.ellipse([nose[0] - 0.2 * r, nose[1] - 0.2 * r, nose[0] + 0.2 * r, nose[1] + 0.2 * r], fill=self.skin)
        deg = math.degrees(rot)
        start, end = (165, 335) if self.style != "buzz" else (195, 320)
        bb = [c[0] - r - ow * 0.5, c[1] - r - ow * 0.5, c[0] + r + ow * 0.5, c[1] + r + ow * 0.5]
        d.chord(bb, start + deg, end + deg, fill=self.hair)
        if self.style == "curly":
            for fx, fy in ((-0.6, -0.7), (0.0, -0.95), (0.45, -0.8), (-0.9, -0.2)):
                p = at(fx, fy)
                d.ellipse([p[0] - 0.32 * r, p[1] - 0.32 * r, p[0] + 0.32 * r, p[1] + 0.32 * r], fill=self.hair)
        ear = at(-0.12, 0.1)
        d.ellipse([ear[0] - 0.2 * r, ear[1] - 0.25 * r, ear[0] + 0.2 * r, ear[1] + 0.25 * r], fill=_shade(self.skin, 0.85), outline=OL, width=int(ow * 0.6))
        eye = at(0.45, -0.1)
        if face == "dead":
            for s in (-1, 1):
                d.line([tuple(eye + np.array([-0.18 * r, -0.18 * r * s])), tuple(eye + np.array([0.18 * r, 0.18 * r * s]))], fill=OL, width=int(ow))
            m = at(0.55, 0.5)
            d.line([tuple(m - fwd * 0.2 * r), tuple(m + fwd * 0.2 * r)], fill=OL, width=int(ow * 0.8))
            return
        d.ellipse([eye[0] - 0.17 * r, eye[1] - 0.22 * r, eye[0] + 0.17 * r, eye[1] + 0.22 * r], fill=(255, 255, 255, 255), outline=OL, width=max(1, int(ow * 0.5)))
        pu = eye + fwd * 0.07 * r
        d.ellipse([pu[0] - 0.1 * r, pu[1] - 0.12 * r, pu[0] + 0.1 * r, pu[1] + 0.12 * r], fill=OL)
        brow = at(0.42, -0.46)
        tilt = 0.12 if face == "run" else -0.05
        d.line([tuple(brow - fwd * 0.2 * r - upv * tilt * r), tuple(brow + fwd * 0.2 * r + upv * tilt * r)], fill=self.hair if self.hair[0] < 120 else OL, width=int(ow * 0.9))
        m = at(0.62, 0.48)
        if face == "run":
            d.ellipse([m[0] - 0.12 * r, m[1] - 0.12 * r, m[0] + 0.12 * r, m[1] + 0.14 * r], fill=(120, 30, 40, 255), outline=OL, width=max(1, int(ow * 0.5)))
        elif face == "cheer":
            d.chord([m[0] - 0.3 * r, m[1] - 0.25 * r, m[0] + 0.25 * r, m[1] + 0.3 * r], 0, 180, fill=(120, 30, 40, 255), outline=OL, width=max(1, int(ow * 0.5)))
        else:
            d.arc([m[0] - 0.25 * r, m[1] - 0.25 * r, m[0] + 0.15 * r, m[1] + 0.15 * r], 20, 150, fill=OL, width=max(1, int(ow * 0.6)))

    def sprite(self, pose, s, phase=0.0, angle=0.0, shadow=True):
        steps = 20
        pidx = int(round((phase % (2 * math.pi)) / (2 * math.pi) * steps)) % steps
        aidx = int(round(angle / (math.pi / 8))) % 16
        key = (pose, round(s, 3), pidx, aidx, shadow)
        if key in self.cache:
            return self.cache[key]
        ph = pidx / steps * 2 * math.pi
        k = s * SS
        size = int(260 * k)
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        J = self._joints(pose, ph)
        upright = pose != "limp"
        if upright:
            pts = [p for side in J["legs"].values() for p in side[2:]]
            ground = max(p[1] for p in pts) + 6
            origin = np.array([size / 2, size * 0.86])
            shift = np.array([0.0, -ground])
            ang = 0.0
        else:
            origin = np.array([size / 2, size / 2])
            shift = np.array([0.0, -25.0])
            ang = aidx * math.pi / 8

        class TF:
            angle = ang

            def __call__(self, p):
                q = (np.asarray(p) + shift) * k
                ca, sa = math.cos(ang), math.sin(ang)
                return origin + np.array([q[0] * ca - q[1] * sa, q[0] * sa + q[1] * ca])

        if shadow and upright:
            d.ellipse([origin[0] - 34 * k, origin[1] - 7 * k, origin[0] + 40 * k, origin[1] + 7 * k], fill=(0, 0, 0, 70))
        face = {"run": "run", "idle": "idle", "cheer": "cheer", "limp": "dead"}[pose]
        self._draw(d, J, k, TF(), face)
        out = img.resize((size // SS, size // SS), Image.LANCZOS)
        res = (out, (origin[0] / SS, origin[1] / SS))
        self.cache[key] = res
        return res

    def paste(self, img, x, y, pose, s, phase=0.0, angle=0.0, shadow=True):
        if pose == "splat":                       # knocked out: lying on the back
            pose, angle, y, shadow = "limp", -math.pi / 2, y - 14 * s, False
        spr, (ax, ay) = self.sprite(pose, s, phase, angle, shadow)
        img.paste(spr, (int(x - ax), int(y - ay)), spr)
