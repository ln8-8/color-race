"""FLAG FACTORY — 2D elimination Shorts with country-flag balls and real physics.

32 country balls drop through a factory machine (pegs, spinning paddles, conveyors, moving platforms, bumpers).
Each level only the first half through the exit gate QUALIFY; then the gate shuts, the trapdoor opens and the
rest fall into the SHREDDER. 32 -> 16 -> 8 -> 4 -> 2 -> 1 champion.

Usage: python factory2d.py --seed 5 --out out/
"""
import argparse
import json
import math
import os
import subprocess
import wave

import numpy as np
import pymunk
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
W, H, FPS, SR = 1080, 1920, 30, 44100
SUB = 4                                   # physics sub-steps per frame
FONT = os.path.join(HERE, "assets", "font.otf")
EMOJI_FONTS = ["/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf", "/usr/share/fonts/noto/NotoColorEmoji.ttf",
               os.path.join(HERE, "assets", "NotoColorEmoji.ttf")]
OL = (18, 18, 24)

from countries import COUNTRIES  # noqa: E402  (ISO-2, short label, display name)


def flag_emoji(cc):
    return "".join(chr(0x1F1E6 + ord(c) - 65) for c in cc)


def font(size):
    return ImageFont.truetype(FONT, max(1, int(size)))


def text_c(d, xy, s, size, fill, stroke=6, sf=OL):
    d.text(xy, s, font=font(size), fill=fill, anchor="mm", stroke_width=stroke, stroke_fill=sf)


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
            bb = im.getbbox()
            im = im.crop(bb)
            w, h = im.size
            side = int(min(w, h) * 0.86)                      # central square of the flag fills the ball
            cx, cy = w // 2, h // 2
            self.flags[cc] = im.crop((cx - side // 2, cy - side // 2, cx + side // 2, cy + side // 2)).convert("RGBA")
        return self.flags[cc]

    def sprite(self, cc, r, angle_deg=0):
        key = (cc, r, int(angle_deg) // 12 % 30)
        if key in self.cache:
            return self.cache[key]
        S = 4
        D = 2 * r * S
        base = self.flag(cc).resize((D, D), Image.LANCZOS)
        if key[2]:
            base = base.rotate(-key[2] * 12, resample=Image.BICUBIC)
        mask = Image.new("L", (D, D), 0)
        ImageDraw.Draw(mask).ellipse([0, 0, D - 1, D - 1], fill=255)
        ball = Image.new("RGBA", (D + 8 * S, D + 8 * S), (0, 0, 0, 0))
        ImageDraw.Draw(ball).ellipse([0, 0, D + 8 * S - 1, D + 8 * S - 1], fill=OL)          # outline
        ball.paste(base, (4 * S, 4 * S), mask)
        hl = Image.new("RGBA", ball.size, (0, 0, 0, 0))                                       # glossy shine
        g = ImageDraw.Draw(hl)
        g.ellipse([D * 0.22, D * 0.12, D * 0.62, D * 0.42], fill=(255, 255, 255, 95))
        g.ellipse([D * 0.3, D * 0.2, D * 0.42, D * 0.3], fill=(255, 255, 255, 150))
        ball = Image.alpha_composite(ball, hl)
        out = ball.resize(((D + 8 * S) // S, (D + 8 * S) // S), Image.LANCZOS)
        self.cache[key] = out
        return out


# ---------------------------------------------------------------- factory levels
X0, X1 = 70, 1010                 # inner walls
TOP_Y, HOLD_Y = 430, 640          # spawn area, holding bar
FUN_Y, GATE_Y = 1530, 1690        # funnel start, gate (exit)
SHRED_Y = 1770


class Level:
    def __init__(self, idx, n, quota, r, rng):
        self.idx, self.n, self.quota, self.r = idx, n, quota, r
        self.space = pymunk.Space()
        self.space.gravity = (0, 1700)
        self.space.iterations = 20
        self.statics, self.kin, self.belts, self.bumpers, self.pegs = [], [], [], [], []
        sb = self.space.static_body
        self.gap = 3 * r + 60                       # wide enough for two balls side by side

        def seg(a, b, rad=6, el=0.4, fr=0.6, body=sb, store=True):
            s = pymunk.Segment(body, a, b, rad)
            s.elasticity, s.friction = el, fr
            self.space.add(s)
            if store and body is sb:
                self.statics.append((a, b, rad))
            return s

        self.seg = seg
        seg((X0, 300), (X0, SHRED_Y), 8)
        seg((X1, 300), (X1, SHRED_Y), 8)
        gl, gr = W / 2 - self.gap / 2, W / 2 + self.gap / 2
        self.funnel = [seg((X0, FUN_Y), (gl, GATE_Y), 9, store=False), seg((X1, FUN_Y), (gr, GATE_Y), 9, store=False)]
        self.funnel_pts = [((X0, FUN_Y), (gl, GATE_Y)), ((X1, FUN_Y), (gr, GATE_Y))]
        self.hold = seg((X0, HOLD_Y), (X1, HOLD_Y), 7, store=False)
        self.gate = None
        self.base_shapes = set(self.space.shapes)        # walls, funnel, holding bar: everything else is an obstacle
        self.cleared = False
        kinds = ["pegs", "paddles", "zigzag", "conveyor", "wheel", "bumpers"]
        rng.shuffle(kinds)
        self.kinds = kinds[:2]
        self._build(self.kinds[0], 700, 1080, rng)
        self._build(self.kinds[1], 1120, 1500, rng)

    def _build(self, kind, y0, y1, rng):
        sb, r = self.space.static_body, self.r
        if kind == "pegs":
            sp = 2 * r + 44
            rows = int((y1 - y0) / (sp * 0.8))
            for j in range(rows):
                off = (sp / 2) if j % 2 else 0
                x = X0 + 40 + off
                while x < X1 - 30:
                    c = pymunk.Circle(sb, 9, (x, y0 + 30 + j * sp * 0.8))
                    c.elasticity, c.friction = 0.55, 0.3
                    self.space.add(c)
                    self.pegs.append((x, y0 + 30 + j * sp * 0.8))
                    x += sp
        elif kind == "paddles":
            n = 3
            for k in range(n):
                b = pymunk.Body(body_type=pymunk.Body.KINEMATIC)
                b.position = (X0 + (k + 0.5) * (X1 - X0) / n, (y0 + y1) / 2 + (k % 2 - 0.5) * 120)
                b.angular_velocity = (1.6 + rng.random()) * (1 if k % 2 else -1)
                L = (X1 - X0) / n * 0.42
                s = pymunk.Segment(b, (-L, 0), (L, 0), 10)
                s.elasticity, s.friction = 0.5, 0.5
                self.space.add(b, s)
                self.kin.append(("paddle", b, L))
        elif kind == "zigzag":
            ys = np.linspace(y0, y1 - 150, 3)
            for k, y in enumerate(ys):
                if k % 2 == 0:
                    self.seg((X0, y), (X1 - self.gap - 20, y + 150), 8, fr=0.2)
                else:
                    self.seg((X1, y), (X0 + self.gap + 20, y + 150), 8, fr=0.2)
            b = pymunk.Body(body_type=pymunk.Body.KINEMATIC)        # moving platform
            b.position = (W / 2, (ys[0] + ys[1]) / 2 + 110)
            s = pymunk.Segment(b, (-90, 0), (90, 0), 9)
            s.elasticity, s.friction = 0.3, 0.8
            self.space.add(b, s)
            self.kin.append(("mover", b, 90))
        elif kind == "conveyor":
            ys = np.linspace(y0 + 40, y1 - 50, 3)
            for k, y in enumerate(ys):
                left = k % 2 == 0
                a, bb = ((X0, y), (X1 - self.gap - 10, y + 60)) if left else ((X0 + self.gap + 10, y + 60), (X1, y))
                s = self.seg(a, bb, 9, el=0.1, fr=1.0)
                s.surface_velocity = ((-260 if left else 260), 0)
                self.belts.append((a, bb, 1 if left else -1))
        elif kind == "wheel":
            for k, cx in enumerate((X0 + (X1 - X0) * 0.3, X0 + (X1 - X0) * 0.7)):
                b = pymunk.Body(body_type=pymunk.Body.KINEMATIC)
                b.position = (cx, (y0 + y1) / 2)
                b.angular_velocity = 1.2 if k else -1.2
                R = min(150, (y1 - y0) / 2 - 20)
                self.space.add(b)
                for a in range(4):
                    ang = a * math.pi / 2
                    s = pymunk.Segment(b, (0, 0), (R * math.cos(ang), R * math.sin(ang)), 9)
                    s.elasticity, s.friction = 0.4, 0.6
                    self.space.add(s)
                self.kin.append(("wheel", b, R))
        elif kind == "bumpers":
            for k in range(7):
                x = X0 + 90 + (k % 4) * ((X1 - X0 - 180) / 3) + (60 if k >= 4 else 0)
                y = y0 + 70 + (k // 4) * (y1 - y0 - 140)
                c = pymunk.Circle(sb, 34, (x, y))
                c.elasticity, c.friction = 1.15, 0.2
                self.space.add(c)
                self.bumpers.append((x, y))

    def release(self):
        self.space.remove(self.hold)
        self.hold = None

    def close_gate(self):
        gl, gr = W / 2 - self.gap / 2, W / 2 + self.gap / 2
        self.gate = self.seg((gl - 4, GATE_Y), (gr + 4, GATE_Y), 9, store=False)

    def clear_obstacles(self):
        """OVERTIME: the machine's obstacles break away so every ball falls freely."""
        if self.cleared:
            return
        for sh in list(self.space.shapes):
            if sh not in self.base_shapes and sh is not self.gate and sh.body.body_type != pymunk.Body.DYNAMIC:
                self.space.remove(sh)
        for kind, b, L in self.kin:
            if b in self.space.bodies:
                self.space.remove(b)
        self.kin, self.belts, self.pegs, self.bumpers = [], [], [], []
        self.statics = self.statics[:2]
        self.cleared = True

    def open_trapdoor(self):
        self.clear_obstacles()
        for s in self.funnel:
            self.space.remove(s)
        self.funnel = []
        if self.gate is not None:
            self.space.remove(self.gate)
            self.gate = None

    def step(self, t, dt):
        for kind, b, L in self.kin:
            if kind == "mover":
                b.velocity = (260 * math.cos(t * 1.6), 0)
        self.space.step(dt)


# ---------------------------------------------------------------- drawing
def factory_background(seed):
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    for y in range(H):
        t = y / H
        d.line([(0, y), (W, y)], fill=(int(34 + 18 * t), int(38 + 14 * t), int(48 + 10 * t)))
    r = np.random.default_rng(seed)
    for k in range(9):                                     # background pipes
        x = int(r.uniform(0, W))
        d.rectangle([x - 14, 300, x + 14, H], fill=(46, 52, 64))
        for y in range(330, H, 160):
            d.rectangle([x - 20, y, x + 20, y + 14], fill=(58, 64, 78))
    for k in range(4):
        y = int(r.uniform(700, 1500))
        d.rectangle([0, y - 10, W, y + 10], fill=(44, 50, 62))
    for x in range(30, W, 120):                            # rivets
        for y in range(340, H, 200):
            d.ellipse([x - 4, y - 4, x + 4, y + 4], fill=(70, 76, 92))
    d.rectangle([0, 0, W, 300], fill=(20, 22, 30))
    return img


def hazard_line(d, a, b, w):
    d.line([a, b], fill=OL, width=int(w + 8))
    L = math.dist(a, b)
    n = max(1, int(L / 28))
    for k in range(n):
        p0 = (a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n)
        p1 = (a[0] + (b[0] - a[0]) * (k + 1) / n, a[1] + (b[1] - a[1]) * (k + 1) / n)
        d.line([p0, p1], fill=(250, 200, 30) if k % 2 == 0 else (30, 30, 34), width=int(w))


def metal_line(d, a, b, w, col=(150, 158, 175)):
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
        d.ellipse([x - 40, y - 40, x + 40, y + 40], fill=OL)
        d.ellipse([x - 36, y - 36, x + 36, y + 36], fill=(230, 50, 70))
        d.ellipse([x - 22, y - 22, x + 22, y + 22], fill=(255, 120, 130))
    # shredder
    d.rectangle([0, SHRED_Y, W, H], fill=(30, 12, 12))
    for x in range(0, W, 60):
        d.ellipse([x - 4, SHRED_Y + 40, x + 64, SHRED_Y + 108], fill=(60, 60, 66), outline=OL, width=4)
    text_c(d, (W / 2, H - 50), "SHREDDER", 52, (255, 70, 60), stroke=6)
    return img


# ---------------------------------------------------------------- audio
def build_audio(seconds, events, rng):
    N = int(seconds * SR) + SR
    out = np.zeros(N)
    t = np.arange(N) / SR

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
    while tt < seconds - 0.5:                                   # industrial beat
        add(kick, tt, 0.55)
        add(noise(0.05, 70) * 0.5, tt + beat / 2, 0.3)
        if k % 2:
            add(noise(0.15, 25), tt, 0.25)
        add(tone(roots[(k // 8) % 4] * 2, beat * 0.9, 4, True), tt, 0.08)
        tt += beat
        k += 1
    q_count = {}
    for at, kind, extra in events:
        if kind == "level":
            add(tone(220, 0.6, 3, True), at, 0.25)
        elif kind == "go":
            add(tone(880, 0.4, 5), at, 0.4)
        elif kind == "qualify":
            n = q_count.get(extra, 0)
            q_count[extra] = n + 1
            add(tone(660 * 2 ** (n / 12), 0.18, 14), at, 0.35)
        elif kind == "gate":
            add(noise(0.4, 10) * 0.8 + tone(90, 0.4, 8), at, 0.7)
        elif kind == "shred":
            add(noise(0.35, 6) * 0.6 + tone(70, 0.35, 6, True) * 0.4, at, 0.5)
        elif kind == "win":
            for j, f in enumerate([523, 659, 784, 1046]):
                add(tone(f, 0.6 if j < 3 else 1.5, 3, True), at + j * 0.14, 0.25)
    out = np.tanh(out * 1.1)
    out /= max(1e-6, np.abs(out).max()) / 0.85
    return (out * 32767).astype(np.int16)


# ---------------------------------------------------------------- main
def render_video(seed, out_dir, n_start=32, preview=False):
    rng = np.random.default_rng(seed)
    pyr = __import__("random").Random(seed)
    idx = rng.permutation(len(COUNTRIES))[:n_start]
    alive = [COUNTRIES[i] for i in idx]
    info = {c[0]: c for c in alive}
    balls = Balls()
    base_bg = factory_background(seed)
    os.makedirs(out_dir, exist_ok=True)
    stem = os.path.join(out_dir, f"factory_{seed}")
    silent, wav, mp4 = stem + "_v.mp4", stem + ".wav", stem + ".mp4"
    ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                           "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                           "-pix_fmt", "yuv420p", silent], stdin=subprocess.PIPE)
    events, frame_no, history = [], [0], []
    vt = lambda: frame_no[0] / FPS                         # noqa: E731
    flying = []                                            # qualified balls flying to the top strip
    sparks = []

    def emit(img):
        if not preview or frame_no[0] % 10 == 0:
            ff.stdin.write(img.tobytes())
        frame_no[0] += 1

    def hud(d, title, sub=None, qualified=(), quota=0, level=None, levels=None):
        text_c(d, (W / 2, 62), title, 74, (255, 220, 50), stroke=8)
        if sub:
            text_c(d, (W / 2, 140), sub, 46, (255, 255, 255), stroke=6)
        if level:
            d.rounded_rectangle([40, 180, 300, 240], 20, fill=(60, 66, 84))
            text_c(d, (170, 210), f"LEVEL {level}/{levels}", 36, (255, 255, 255), stroke=0)
            d.rounded_rectangle([W - 380, 180, W - 40, 240], 20, fill=(40, 120, 70))
            text_c(d, (W - 210, 210), f"QUALIFIED {len(qualified)}/{quota}", 36, (255, 255, 255), stroke=0)
        if quota:                                          # strip with qualified flags
            n = quota
            sz = min(56, (W - 80) / max(1, n) - 4)
            x0 = W / 2 - (sz + 4) * n / 2
            for k in range(n):
                cx, cy = x0 + k * (sz + 4) + sz / 2, 285
                if k < len(qualified):
                    spr = balls.sprite(qualified[k], int(sz / 2))
                    img_ref[0].paste(spr, (int(cx - spr.width / 2), int(cy - spr.height / 2)), spr)
                else:
                    d.ellipse([cx - sz / 2, cy - sz / 2, cx + sz / 2, cy + sz / 2], outline=(110, 116, 130), width=3)

    img_ref = [None]

    # ---- intro: all flags
    intro = 3.2
    for f in range(int(intro * FPS)):
        img = base_bg.copy()
        img_ref[0] = img
        d = ImageDraw.Draw(img)
        p = 1 + 0.05 * math.sin(f * 0.25)
        text_c(d, (W / 2, 90), "FIND YOUR", 84 * p, (255, 255, 255), stroke=8)
        text_c(d, (W / 2, 190), "COUNTRY!", 110 * p, (255, 220, 50), stroke=9)
        cols, sz = 4, 112
        for k, (cc, lab, name) in enumerate(alive):
            if f < k * 1.2:
                continue
            cx = W / 2 + ((k % cols) - (cols - 1) / 2) * 235
            cy = 400 + (k // cols) * 160
            spr = balls.sprite(cc, sz // 2)
            img.paste(spr, (int(cx - 85), int(cy - spr.height / 2)), spr)
            d.text((cx - 20, cy), lab, font=font(40), fill=(255, 255, 255), anchor="lm", stroke_width=5, stroke_fill=OL)
        text_c(d, (W / 2, 1720), "Only ONE survives the factory", 52, (255, 255, 255), stroke=6)
        text_c(d, (W / 2, 1800), "Comment your country below!", 50, (255, 220, 50), stroke=6)
        emit(img)

    levels = int(math.log2(n_start))
    sizes = {64: 22, 32: 31, 16: 38, 8: 46, 4: 56, 2: 66}
    for li in range(levels):
        n = len(alive)
        quota = n // 2
        r = sizes.get(n, 30)
        lv = Level(li, n, quota, r, pyr)
        bg = level_background(base_bg, lv)
        bodies = {}
        cols = max(1, int((X1 - X0 - 20) // (2 * r + 6)))
        for k, (cc, lab, name) in enumerate(alive):
            b = pymunk.Body(1, pymunk.moment_for_circle(1, 0, r))
            b.position = (X0 + 20 + r + (k % cols) * (2 * r + 6) + pyr.uniform(-3, 3), HOLD_Y - r - 8 - (k // cols) * (2 * r + 4))
            s = pymunk.Circle(b, r)
            s.elasticity, s.friction = 0.35, 0.7
            lv.space.add(b, s)
            bodies[cc] = (b, s)
        qualified, eliminated = [], []
        t, phase, phase_t = 0.0, "card", 0.0
        events.append((vt(), "level", li))
        stuck = {}
        overtime_t = -9
        while True:
            dt = 1 / FPS
            if phase == "card" and phase_t > 1.1:
                phase, phase_t = "count", 0.0
            elif phase == "count" and phase_t > 0.9:
                lv.release()
                events.append((vt(), "go", li))
                phase, phase_t = "run", 0.0
            elif phase == "run":
                # qualify balls that drop through the gate
                for cc, (b, s) in list(bodies.items()):
                    if b.position.y > GATE_Y + r + 4 and len(qualified) < quota and lv.gate is None:
                        lv.space.remove(b, s)
                        del bodies[cc]
                        qualified.append(cc)
                        flying.append([cc, b.position.x, b.position.y, vt(), len(qualified) - 1, quota, r])
                        events.append((vt(), "qualify", li))
                if len(qualified) >= quota and lv.gate is None:
                    lv.close_gate()
                    events.append((vt(), "gate", li))
                    phase, phase_t = "close", 0.0
                # anti-stuck nudges (and a hard limit)
                for cc, (b, s) in bodies.items():
                    if b.velocity.length < 20:
                        stuck[cc] = stuck.get(cc, 0) + dt
                        if stuck[cc] > 1.2:
                            b.apply_impulse_at_local_point((pyr.uniform(-250, 250), -pyr.uniform(150, 350)))
                            stuck[cc] = 0
                    else:
                        stuck[cc] = 0
                if phase_t > 9 and not lv.cleared:                    # OVERTIME: obstacles break away
                    lv.clear_obstacles()
                    bg = level_background(base_bg, lv)
                    overtime_t = vt()
                    events.append((vt(), "gate", li))
                if phase_t > 18 and lv.gate is None:                 # last-resort safety
                    for cc in sorted(bodies, key=lambda c: -bodies[c][0].position.y)[: quota - len(qualified)]:
                        bodies[cc][0].position = (W / 2, GATE_Y + r + 10)
            elif phase == "close" and phase_t > 0.5:
                lv.open_trapdoor()
                bg = level_background(base_bg, lv)
                phase, phase_t = "drop", 0.0
            elif phase == "drop":
                for cc, (b, s) in list(bodies.items()):
                    if b.position.y > SHRED_Y + 20:
                        lv.space.remove(b, s)
                        del bodies[cc]
                        eliminated.append(cc)
                        events.append((vt(), "shred", li))
                        for _ in range(18):
                            a = pyr.uniform(0, 2 * math.pi)
                            sp = pyr.uniform(200, 700)
                            sparks.append([b.position.x, SHRED_Y + 20, math.cos(a) * sp, -abs(math.sin(a)) * sp, vt()])
                if not bodies or phase_t > 2.5:
                    for cc in list(bodies):
                        eliminated.append(cc)
                    bodies = {}
                    phase, phase_t = "done", 0.0
            elif phase == "done" and phase_t > 0.6:
                break
            for _ in range(SUB):
                lv.step(t, dt / SUB)
                t += dt / SUB
            phase_t += dt

            # ---- draw
            img = bg.copy()
            img_ref[0] = img
            d = ImageDraw.Draw(img)
            for a, b, sgn in lv.belts:                                   # animated conveyor stripes
                hazard_line(d, a, b, 20)
                L = math.dist(a, b)
                for k in range(int(L / 40)):
                    u = ((k * 40 + sgn * -t * 260) % L) / L
                    p = (a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u)
                    d.ellipse([p[0] - 4, p[1] - 4, p[0] + 4, p[1] + 4], fill=(255, 255, 255))
            for (a, b) in lv.funnel_pts if lv.funnel else []:
                hazard_line(d, a, b, 22)
            if lv.hold is not None:
                hazard_line(d, (X0, HOLD_Y), (X1, HOLD_Y), 18)
            gl, gr = W / 2 - lv.gap / 2, W / 2 + lv.gap / 2
            if lv.gate is not None:
                metal_line(d, (gl - 4, GATE_Y), (gr + 4, GATE_Y), 22, (200, 60, 60))
            else:
                d.rectangle([gl, GATE_Y - 6, gr, GATE_Y + 6], fill=(60, 220, 110))
            for kind, b, L in lv.kin:
                if kind in ("paddle", "mover"):
                    p0, p1 = b.local_to_world((-L, 0)), b.local_to_world((L, 0))
                    metal_line(d, tuple(p0), tuple(p1), 22, (90, 170, 230) if kind == "paddle" else (230, 160, 60))
                    c = b.position
                    d.ellipse([c.x - 14, c.y - 14, c.x + 14, c.y + 14], fill=(240, 240, 245), outline=OL, width=4)
                else:
                    for a4 in range(4):
                        ang = b.angle + a4 * math.pi / 2
                        p1 = (b.position.x + L * math.cos(ang), b.position.y + L * math.sin(ang))
                        metal_line(d, tuple(b.position), p1, 20, (180, 110, 230))
                    c = b.position
                    d.ellipse([c.x - 20, c.y - 20, c.x + 20, c.y + 20], fill=(240, 240, 245), outline=OL, width=4)
            # shredder teeth spin
            for x in range(0, W, 60):
                for k in range(6):
                    a = vt() * 6 * (1 if (x // 60) % 2 else -1) + k * math.pi / 3
                    cx, cy = x + 30, SHRED_Y + 74
                    d.polygon([(cx + 34 * math.cos(a), cy + 34 * math.sin(a)), (cx + 20 * math.cos(a + 0.3), cy + 20 * math.sin(a + 0.3)),
                               (cx + 20 * math.cos(a - 0.3), cy + 20 * math.sin(a - 0.3))], fill=(200, 200, 210))
            for cc, (b, s) in bodies.items():
                spr = balls.sprite(cc, r, math.degrees(b.angle))
                img.paste(spr, (int(b.position.x - spr.width / 2), int(b.position.y - spr.height / 2)), spr)
                if r >= 46:
                    d.text((b.position.x, b.position.y + r + 16), info[cc][1], font=font(30), fill=(255, 255, 255),
                           anchor="mm", stroke_width=4, stroke_fill=OL)
            now = vt()
            for sp in sparks:                                             # shredder sparks
                age = now - sp[4]
                if 0 <= age < 0.8:
                    x, y = sp[0] + sp[2] * age, sp[1] + sp[3] * age + 900 * age * age
                    c = (255, int(200 - 200 * age), 40)
                    d.rectangle([x - 4, y - 4, x + 4, y + 4], fill=c)
            sparks[:] = [s_ for s_ in sparks if now - s_[4] < 0.8]
            shown_q = [q for q in qualified if not any(f_[0] == q and now - f_[3] < 0.5 for f_ in flying)]
            hud(d, "WHICH COUNTRY WINS?", None, shown_q, quota, li + 1, levels)
            for fl in flying:                                             # qualified ball flying to its slot
                age = now - fl[3]
                if 0 <= age < 0.5:
                    sz = min(56, (W - 80) / max(1, fl[5]) - 4)
                    tx = W / 2 - (sz + 4) * fl[5] / 2 + fl[4] * (sz + 4) + sz / 2
                    u = age / 0.5
                    x, y = fl[1] + (tx - fl[1]) * u, fl[2] + (285 - fl[2]) * u - math.sin(u * math.pi) * 200
                    rr = int(fl[6] + (sz / 2 - fl[6]) * u)
                    spr = balls.sprite(fl[0], max(8, rr))
                    img.paste(spr, (int(x - spr.width / 2), int(y - spr.height / 2)), spr)
            if phase == "run" and 0 <= vt() - overtime_t < 1.4:
                text_c(d, (W / 2, 1000), "OVERTIME!", 130, (255, 120, 40), stroke=12)
                text_c(d, (W / 2, 1120), "The machine breaks apart!", 50, (255, 255, 255), stroke=6)
            if phase == "card":
                pop = min(1, phase_t / 0.2)
                d.rounded_rectangle([90, 820, W - 90, 1120], 40, fill=(15, 15, 22), outline=(255, 220, 50), width=8)
                text_c(d, (W / 2, 900), f"LEVEL {li + 1}" if quota > 1 else "THE FINAL", 110 * pop, (255, 220, 50), stroke=8)
                text_c(d, (W / 2, 1030), f"{n} LEFT  ·  TOP {quota} QUALIFY" if quota > 1 else "FIRST THROUGH WINS!", 52, (255, 255, 255), stroke=5)
            elif phase == "count":
                text_c(d, (W / 2, 1000), "3" if phase_t < 0.34 else "2" if phase_t < 0.67 else "1", 280, (255, 255, 255), stroke=14)
            elif phase in ("close", "drop") and phase_t < 1.6:
                text_c(d, (W / 2, 1000), "GATE CLOSED!" if phase == "close" else "TRAPDOOR OPEN!", 100, (255, 80, 70), stroke=10)
                text_c(d, (W / 2, 1110), f"{n - quota} ELIMINATED", 60, (255, 255, 255), stroke=6)
            emit(img)
        history.append({"level": li + 1, "qualified": [info[c][2] for c in qualified], "eliminated": [info[c][2] for c in eliminated]})
        alive = [info[c] for c in qualified]

    # ---- winner
    champ = alive[0]
    events.append((vt(), "win", 0))
    conf = [(pyr.uniform(0, W), pyr.uniform(-H, 0), pyr.uniform(250, 600), pyr.uniform(-80, 80),
             tuple(int(v) for v in pyr.choice([(235, 59, 59), (52, 120, 246), (46, 204, 113), (250, 204, 21), (255, 255, 255)])),
             pyr.uniform(0, 6)) for _ in range(160)]
    for f in range(int(4.5 * FPS)):
        tt = f / FPS
        img = base_bg.copy()
        d = ImageDraw.Draw(img)
        for (cx0, cy0, vy, vx, cc, rot) in conf:
            cx, cy = cx0 + vx * tt, cy0 + vy * tt + 300
            if 0 < cy < H:
                a = rot + tt * 6
                d.polygon([(cx + 14 * math.cos(a + k * 1.57), cy + 7 * math.sin(a + k * 1.57)) for k in range(4)], fill=cc)
        bounce = abs(math.sin(tt * 4)) * 40
        spr = balls.sprite(champ[0], 230, math.sin(tt * 3) * 20)
        img.paste(spr, (int(W / 2 - spr.width / 2), int(1000 - bounce - spr.height / 2)), spr)
        pop = min(1, tt / 0.25)
        text_c(d, (W / 2, 220), "CHAMPION", 80, (255, 220, 50), stroke=8)
        text_c(d, (W / 2, 380), champ[2], (150 if len(champ[2]) < 9 else 105) * pop, (255, 255, 255), stroke=14)
        text_c(d, (W / 2, 520), "WINS THE FACTORY!", 70 * pop, (255, 220, 50), stroke=8)
        if tt > 1.0:
            text_c(d, (W / 2, 1440), "Did your country win?", 66, (255, 255, 255), stroke=7)
        if tt > 1.8:
            text_c(d, (W / 2, 1530), "New race every day - Subscribe!", 52, (255, 220, 50), stroke=6)
        emit(img)

    ff.stdin.close()
    ff.wait()
    total = frame_no[0] / FPS
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
    meta = {"seed": seed, "file": mp4, "style": "factory", "world": "factory", "character": "flags",
            "countries": [c[2] for c in (COUNTRIES[i] for i in idx)], "winner": champ[2], "runners": [c[2] for c in (COUNTRIES[i] for i in idx)],
            "eliminated": [[c, f"LEVEL {h['level']}"] for h in history for c in h["eliminated"]],
            "levels": history, "duration_s": round(total, 1)}
    with open(stem + ".json", "w") as fh:
        json.dump(meta, fh, indent=2, ensure_ascii=False)
    return mp4, meta


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", default="out")
    ap.add_argument("--countries", type=int, default=32, choices=[8, 16, 32, 64])
    ap.add_argument("--preview", action="store_true")
    a = ap.parse_args()
    print(json.dumps(render_video(a.seed, a.out, a.countries, a.preview)[1], indent=2, ensure_ascii=False))
