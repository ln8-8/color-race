"""
Color Race 2D — fast cartoon-style Shorts (renders in ~30 s).

Same idea as the 3D version: pick a color, countdown, hazards eliminate runners, one winner.
Six locations with their own colors and scenery: stadium, desert, snow, city, forest, volcano.

Usage:  python render2d.py --seed 123 --out out/ [--world desert]
"""
import argparse
import json
import math
import os
import subprocess
import wave

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFont

from chars2d import character_classes

CHARACTERS = ["jelly", "person", "duck", "car", "marble"]

W, H, FPS = 1080, 1920, 30
SR = 44100
HERE = os.path.dirname(os.path.abspath(__file__))
FONT_PATH = os.path.join(HERE, "assets", "font.otf")

PALETTE = [
    ("RED", (235, 59, 59)), ("BLUE", (52, 120, 246)), ("GREEN", (46, 204, 113)), ("YELLOW", (250, 204, 21)),
    ("PURPLE", (155, 89, 232)), ("ORANGE", (255, 140, 0)), ("PINK", (255, 105, 180)), ("CYAN", (0, 206, 209)),
    ("WHITE", (240, 240, 240)),
]
OUTLINE = (20, 20, 28)
KILL_TYPES = ["LIGHTNING", "METEOR", "TRAP", "BOMB"]

WORLDS2D = {
    "stadium": dict(title="STADIUM SPRINT", sky=((25, 30, 70), (70, 40, 110)), lanes=((196, 85, 58), (186, 78, 52)),
                    edge=(60, 150, 70), bottom=(48, 128, 58), line=(245, 240, 230), deco="stands"),
    "desert": dict(title="DESERT DASH", sky=((255, 170, 90), (255, 220, 160)), lanes=((205, 160, 105), (195, 150, 98)),
                   edge=(222, 186, 130), bottom=(226, 192, 140), line=(240, 215, 170), deco="cactus"),
    "snow": dict(title="FROZEN PASS", sky=((150, 180, 215), (220, 232, 245)), lanes=((225, 235, 246), (212, 224, 238)),
                 edge=(245, 249, 255), bottom=(236, 243, 252), line=(170, 195, 225), deco="pines"),
    "city": dict(title="CITY RUSH", sky=((10, 12, 35), (45, 30, 80)), lanes=((60, 60, 66), (54, 54, 60)),
                 edge=(120, 120, 128), bottom=(30, 30, 40), line=(235, 200, 60), deco="buildings"),
    "forest": dict(title="FOREST TRAIL", sky=((120, 190, 235), (200, 235, 250)), lanes=((140, 102, 66), (130, 95, 60)),
                   edge=(70, 130, 55), bottom=(52, 110, 45), line=(110, 80, 50), deco="trees"),
    "volcano": dict(title="VOLCANO RUN", sky=((40, 10, 10), (140, 40, 15)), lanes=((70, 60, 56), (62, 53, 50)),
                    edge=(255, 110, 20), bottom=(255, 90, 10), line=(255, 150, 60), deco="lava"),
}

TITLE_Y = 200
CHIPS_Y = 330
EXTRA_COLORS = [("BLACK", (45, 45, 52)), ("BROWN", (140, 85, 45)), ("LIME", (170, 230, 40))]   # for 12-color tournaments

LAYOUTS = {
    "portrait": dict(W=1080, H=1920, TITLE_Y=200, CHIPS_Y=330, TRACK_TOP=470, TRACK_BOT=1500,
                     title_y=160, bar_y=240, banner_w=480, win_x=540, win_ground=1290, win_k=1.0,
                     txt_x=540, name_y=330, wins_y=500, pick_y=1390, follow_y=1480),
    "landscape": dict(W=1920, H=1080, TITLE_Y=95, CHIPS_Y=178, TRACK_TOP=258, TRACK_BOT=930,
                      title_y=48, bar_y=100, banner_w=520, win_x=560, win_ground=930, win_k=0.8,
                      txt_x=1300, name_y=330, wins_y=490, pick_y=680, follow_y=780),
}
LAY = dict(LAYOUTS["portrait"])


def set_layout(name):
    global W, H, TITLE_Y, CHIPS_Y, TRACK_TOP, TRACK_BOT
    LAY.clear()
    LAY.update(LAYOUTS[name])
    W, H, TITLE_Y, CHIPS_Y = LAY["W"], LAY["H"], LAY["TITLE_Y"], LAY["CHIPS_Y"]
    TRACK_TOP, TRACK_BOT = LAY["TRACK_TOP"], LAY["TRACK_BOT"]
TRACK_TOP, TRACK_BOT = 470, 1500
START_X, FINISH_X = 220, 6400
INTRO_S, COUNT_S, OUTRO_S = 3.0, 2.0, 4.0

_fonts = {}


def font(size):
    size = max(1, int(size))
    if size not in _fonts:
        _fonts[size] = ImageFont.truetype(FONT_PATH, size)
    return _fonts[size]


def text_c(d, xy, s, size, fill, stroke=6, stroke_fill=OUTLINE):
    d.text(xy, s, font=font(size), fill=fill, anchor="mm", stroke_width=stroke, stroke_fill=stroke_fill)


def lerp(a, b, t):
    return a + (b - a) * t


# ---------------------------------------------------------------- simulation
def simulate(rng, n):
    dt = 1 / FPS
    x = np.full(n, float(START_X))
    v = np.zeros(n)
    target = rng.uniform(190, 250, n)
    alive = np.ones(n, bool)
    finished = np.zeros(n, bool)
    effect = [None] * n

    n_kills = int(rng.integers(max(2, n - 4), n - 1))
    kill_fracs = [lerp(0.15, 0.88, (i + rng.uniform(0.2, 0.8)) / n_kills) for i in range(n_kills)]
    kill_types = [str(k) for k in rng.choice(KILL_TYPES, n_kills)]
    buff_fracs = sorted(rng.uniform(0.1, 0.9, 4))
    buff_types = [str(b) for b in rng.permutation(["BOOST", "BOOST", "SLIP", "SLIP"])]

    WARN = int(0.9 * FPS)
    pending, events, frames = [], [], []
    winner = win_frame = None
    f = 0
    while True:
        lead_x = x[alive].max()
        prog = (lead_x - START_X) / (FINISH_X - START_X)
        while kill_fracs and prog >= kill_fracs[0] and winner is None:
            kill_fracs.pop(0)
            ktype = kill_types.pop(0)
            cand = [i for i in range(n) if alive[i] and not finished[i] and i not in [p[0] for p in pending]]
            if alive.sum() - len(pending) <= 2 or not cand:
                continue
            order = sorted(cand, key=lambda i: -x[i])
            r = rng.random()
            victim = order[0] if r < 0.35 else (order[-1] if r < 0.5 else int(rng.choice(cand)))
            pending.append([victim, f + WARN, ktype])
            events.append((f, "warn", victim, ktype))
        while buff_fracs and prog >= buff_fracs[0] and winner is None:
            buff_fracs.pop(0)
            btype = buff_types.pop(0)
            cand = [i for i in range(n) if alive[i] and not finished[i] and effect[i] is None]
            if not cand:
                continue
            order = sorted(cand, key=lambda i: x[i])
            who = order[0] if (btype == "BOOST" and rng.random() < 0.6) else int(rng.choice(cand))
            effect[who] = [btype, int(1.4 * FPS)]
            events.append((f, btype.lower(), who, None))
        for p in list(pending):
            if f >= p[1]:
                pending.remove(p)
                if alive[p[0]] and not finished[p[0]]:
                    alive[p[0]] = False
                    events.append((f, "kill", p[0], p[2]))
        for i in range(n):
            if not alive[i]:
                v[i] = 0
                continue
            if finished[i]:
                v[i] = max(0.0, v[i] - 400 * dt)
                continue
            if rng.random() < dt / 1.1:
                target[i] = rng.uniform(165, 270)
            tgt = target[i] + (lead_x - x[i]) * 0.06
            if prog > 0.8:
                tgt += 40 * rng.random()
            if effect[i]:
                tgt = 420 if effect[i][0] == "BOOST" else 40
                effect[i][1] -= 1
                if effect[i][1] <= 0:
                    effect[i] = None
            ramp = min(1.0, f / (0.6 * FPS))
            v[i] += (tgt * ramp - v[i]) * min(1, dt * 3)
            x[i] += v[i] * dt
            if x[i] >= FINISH_X and not finished[i]:
                finished[i] = True
                if winner is None:
                    winner, win_frame = i, f
                    events.append((f, "finish", i, None))
        frames.append({"x": x.copy(), "alive": alive.copy(), "eff": [e[0] if e else None for e in effect]})
        f += 1
        if win_frame is not None and f > win_frame + int(1.6 * FPS):
            break
        if f > 90 * FPS:
            break
    if winner is None:
        winner = int(np.argmax(np.where(alive, x, -1)))
        win_frame = f - 1
    return frames, events, winner, win_frame


# ---------------------------------------------------------------- drawing
def limb(d, p1, p2, color, w):
    d.line([p1, p2], fill=OUTLINE, width=w + 6)
    d.line([p1, p2], fill=color, width=w)


def draw_runner(d, sx, gy, color, phase, s=1.0, moving=True):
    sw = math.sin(phase) if moving else 0.0
    hip = (sx, gy - 62 * s)
    sh = (sx + 10 * s, gy - 112 * s)
    L1 = L2 = 32 * s
    w = max(4, int(9 * s))
    for sign in (1, -1):
        a = sign * sw * 0.75
        knee = (hip[0] + L1 * math.sin(a), hip[1] + L1 * math.cos(a))
        b = a - (0.9 if moving else 0) * (0.5 + 0.5 * sign * math.cos(phase))
        foot = (knee[0] + L2 * math.sin(b), knee[1] + L2 * math.cos(b))
        limb(d, hip, knee, color, w)
        limb(d, knee, foot, color, w)
    limb(d, hip, sh, color, int(w * 1.4))
    for sign in (1, -1):
        a = -sign * sw * 0.9
        el = (sh[0] + 26 * s * math.sin(a), sh[1] + 26 * s * math.cos(a))
        hand = (el[0] + 24 * s * math.sin(a + 1.3), el[1] + 24 * s * math.cos(a + 1.3) - 4 * s)
        limb(d, sh, el, color, w)
        limb(d, el, hand, color, w)
    hr = 18 * s
    hc = (sh[0] + 8 * s, sh[1] - 26 * s)
    d.ellipse([hc[0] - hr, hc[1] - hr, hc[0] + hr, hc[1] + hr], fill=color, outline=OUTLINE, width=max(2, int(4 * s)))
    d.ellipse([hc[0] + 4 * s, hc[1] - 6 * s, hc[0] + 10 * s, hc[1]], fill=OUTLINE)


def draw_dead(d, sx, gy, s=1.0):
    g = (120, 120, 128)
    w = max(4, int(9 * s))
    limb(d, (sx - 50 * s, gy - 12 * s), (sx + 15 * s, gy - 12 * s), g, int(w * 1.4))
    limb(d, (sx - 50 * s, gy - 12 * s), (sx - 85 * s, gy - 5 * s), g, w)
    limb(d, (sx - 50 * s, gy - 12 * s), (sx - 80 * s, gy - 28 * s), g, w)
    hr = 18 * s
    d.ellipse([sx + 15 * s, gy - 30 * s - hr / 2, sx + 15 * s + 2 * hr, gy - 30 * s + 1.5 * hr], fill=g, outline=OUTLINE, width=3)
    cx, cy = sx + 15 * s + hr, gy - 30 * s + hr / 2
    for dx in (-7, 7):
        d.line([(cx + dx - 4, cy - 4), (cx + dx + 4, cy + 4)], fill=OUTLINE, width=3)
        d.line([(cx + dx - 4, cy + 4), (cx + dx + 4, cy - 4)], fill=OUTLINE, width=3)


def bolt_points(rng, segs=9):
    return [(0 if k in (0, segs) else rng.uniform(-40, 40), k / segs) for k in range(segs + 1)]


def explosion(d, cx, cy, t, s=1.0, seed=0):
    """Fireball + flying sparks. t in [0, 1]."""
    r = (40 + 170 * t) * s
    a = 1 - t
    for rr, col in ((r, (255, 120, 0)), (r * 0.7, (255, 200, 40)), (r * 0.4, (255, 255, 200))):
        c = tuple(int(lerp(60, cc, a)) for cc in col)
        d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=c)
    rng = np.random.default_rng(seed)
    for _ in range(26):
        ang, sp = rng.uniform(0, 2 * math.pi), rng.uniform(200, 520) * s
        px, py = cx + math.cos(ang) * sp * t, cy + math.sin(ang) * sp * t + 300 * t * t
        sz = max(2, 9 * (1 - t))
        d.rectangle([px - sz, py - sz, px + sz, py + sz], fill=(60, 45, 35) if _ % 3 else (255, 190, 60))


def make_background(n, world):
    cfg = WORLDS2D[world]
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    top, bot = cfg["sky"]
    for y in range(TRACK_TOP):
        t = y / TRACK_TOP
        d.line([(0, y), (W, y)], fill=tuple(int(lerp(a, b, t)) for a, b in zip(top, bot)))
    d.rectangle([0, TRACK_TOP - 30, W, TRACK_BOT + 30], fill=cfg["edge"])
    lane_h = (TRACK_BOT - TRACK_TOP) / n
    for i in range(n):
        y0 = TRACK_TOP + i * lane_h
        d.rectangle([0, y0, W, y0 + lane_h], fill=cfg["lanes"][i % 2])
        d.line([(0, y0), (W, y0)], fill=cfg["line"], width=5)
    d.line([(0, TRACK_BOT), (W, TRACK_BOT)], fill=cfg["line"], width=5)
    d.rectangle([0, TRACK_BOT + 30, W, H], fill=cfg["bottom"])
    return img


def make_deco_strip(world, length, rng):
    """A long transparent strip of scenery drawn below the track, scrolled with parallax."""
    real_h = H - TRACK_BOT - 30
    hgt = 390                                   # designed for the portrait layout, scaled to fit below
    length = int(length * hgt / real_h) if real_h < hgt else length
    strip = Image.new("RGBA", (length, hgt), (0, 0, 0, 0))
    d = ImageDraw.Draw(strip)
    kind = WORLDS2D[world]["deco"]
    x = 0
    while x < length:
        if kind == "stands":
            for row in range(5):
                for k in range(12):
                    c = PALETTE[int(rng.integers(len(PALETTE)))][1]
                    px, py = x + k * 22 + row * 6, 40 + row * 44
                    d.ellipse([px, py, px + 16, py + 16], fill=c)
                    d.rectangle([px - 2, py + 16, px + 18, py + 38], fill=c)
            x += 270
        elif kind == "cactus":
            hgt_c = rng.uniform(90, 200)
            base = hgt - 60
            d.rounded_rectangle([x, base - hgt_c, x + 34, base], 16, fill=(60, 130, 60), outline=OUTLINE, width=4)
            d.rounded_rectangle([x - 38, base - hgt_c * 0.7, x - 14, base - hgt_c * 0.35], 12, fill=(60, 130, 60), outline=OUTLINE, width=4)
            d.rectangle([x - 20, base - hgt_c * 0.42, x + 4, base - hgt_c * 0.35], fill=(60, 130, 60))
            x += int(rng.uniform(160, 380))
        elif kind == "pines":
            hgt_c = rng.uniform(140, 260)
            base = hgt - 40
            for k in range(3):
                w_ = 70 - k * 18
                y1 = base - hgt_c * (0.25 + k * 0.3)
                d.polygon([(x - w_, y1 + 70), (x + w_, y1 + 70), (x, y1 - 30)], fill=(40, 95, 60), outline=OUTLINE)
                d.polygon([(x - w_ * 0.5, y1 + 5), (x + w_ * 0.5, y1 + 5), (x, y1 - 30)], fill=(245, 250, 255))
            d.rectangle([x - 8, base - 40, x + 8, base], fill=(80, 55, 35))
            x += int(rng.uniform(90, 180))
        elif kind == "buildings":
            bw, bh = rng.uniform(120, 220), rng.uniform(150, hgt - 20)
            d.rectangle([x, hgt - bh, x + bw, hgt], fill=(30 + int(rng.integers(30)), 30, 50), outline=OUTLINE, width=3)
            for wy in range(int(hgt - bh + 15), hgt - 20, 34):
                for wx in range(int(x + 12), int(x + bw - 20), 30):
                    if rng.random() < 0.55:
                        d.rectangle([wx, wy, wx + 16, wy + 20], fill=(255, 215, 120))
            x += int(bw + rng.uniform(10, 40))
        elif kind == "trees":
            hgt_c = rng.uniform(150, 260)
            base = hgt - 40
            d.rectangle([x - 12, base - hgt_c * 0.5, x + 12, base], fill=(100, 70, 40), outline=OUTLINE, width=3)
            for ox, oy, r_ in ((0, 0.75, 70), (-45, 0.6, 55), (45, 0.6, 55)):
                cy = base - hgt_c * oy
                d.ellipse([x + ox - r_, cy - r_, x + ox + r_, cy + r_], fill=(55, 130, 50), outline=OUTLINE, width=3)
            x += int(rng.uniform(120, 240))
        elif kind == "lava":
            bh = rng.uniform(60, 200)
            d.polygon([(x, hgt), (x + 60, hgt - bh), (x + 110, hgt - bh * 0.7), (x + 170, hgt)], fill=(45, 35, 32), outline=OUTLINE)
            x += int(rng.uniform(140, 300))
    if real_h != hgt:
        strip = strip.resize((max(W + 10, int(strip.width * real_h / hgt)), real_h), Image.LANCZOS)
    return strip


# ---------------------------------------------------------------- audio
def synth_audio(total_s, race_start_s, events_s, win_s, rng):
    N = int(total_s * SR) + SR
    out = np.zeros(N)

    def add(sig, at, gain=1.0):
        i = int(at * SR)
        j = min(N, i + len(sig))
        if 0 <= i < N:
            out[i:j] += sig[: j - i] * gain

    def env(n, decay=8.0):
        return np.exp(-np.arange(n) / SR * decay)

    def tone(freq, dur, decay=6, square=False):
        n = int(dur * SR)
        ph = 2 * np.pi * freq * np.arange(n) / SR
        return (np.sign(np.sin(ph)) * 0.6 if square else np.sin(ph)) * env(n, decay)

    def sweep(f0, f1, dur, decay=3):
        n = int(dur * SR)
        return np.sin(2 * np.pi * np.cumsum(np.linspace(f0, f1, n)) / SR) * env(n, decay)

    def noise(dur, decay=10):
        n = int(dur * SR)
        return rng.uniform(-1, 1, n) * env(n, decay)

    kick = sweep(150, 40, 0.25, decay=14)
    hat = np.diff(noise(0.05, decay=60), prepend=0)
    beat = 60 / 140
    roots = [55, 55, 65.4, 49]
    b, tt = 0, race_start_s
    while tt < win_s + 0.3:
        add(kick, tt, 0.55)
        add(hat, tt + beat / 2, 0.25)
        root = roots[(b // 4) % 4]
        add(tone(root * 2, beat * 0.9, 4, True), tt, 0.12)
        add(tone(root * 4 * (1.5 if b % 2 else 1), beat * 0.45, 9, True), tt + beat / 2, 0.05)
        tt += beat
        b += 1
    for k in range(int((race_start_s - 2.0) / 0.5)):
        add(tone(1200, 0.05, 60), k * 0.5, 0.12)
    for k in range(3):
        add(tone(660, 0.25, 10), race_start_s - COUNT_S + k * COUNT_S / 3, 0.45)
    add(tone(1320, 0.6, 4), race_start_s, 0.5)
    sfx = {
        "warn": lambda: np.concatenate([tone(900, 0.12, 4, True), tone(600, 0.12, 4, True)] * 2),
        "LIGHTNING": lambda: noise(0.8, 5) * 0.9 + sweep(2000, 100, 0.8, 5) * 0.3,
        "METEOR": lambda: noise(1.0, 4) * 0.6 + sweep(120, 30, 1.0, 3) * 0.8,
        "BOMB": lambda: noise(1.0, 4) * 0.6 + sweep(100, 30, 1.0, 3) * 0.8,
        "TRAP": lambda: sweep(900, 80, 0.7, 2) * 0.7,
        "boost": lambda: sweep(300, 1400, 0.4, 2) * 0.5,
        "slip": lambda: sweep(600, 200, 0.5, 2) * np.sin(np.linspace(0, 40, int(0.5 * SR))) * 0.6,
    }
    for at, kind, extra in events_s:
        if kind == "warn":
            add(sfx["warn"](), at, 0.25)
        elif kind == "kill":
            add(sfx[extra](), at, 0.8)
        elif kind in ("boost", "slip"):
            add(sfx[kind](), at, 0.6)
    for k, fq in enumerate([523, 659, 784, 1046]):
        add(tone(fq, 0.5 if k < 3 else 1.4, 3, True), win_s + k * 0.13, 0.25)
    out = np.tanh(out * 1.2)
    out /= max(1e-6, np.abs(out).max()) / 0.85
    return (out * 32767).astype(np.int16)


# ---------------------------------------------------------------- main render
def render_video(seed, out_dir, world=None, preview=False, character=None, layout="portrait",
                 runners=None, label=None, win_word="WINS!", pick_line=None, follow_line=None, name=None):
    """runners: optional list of (NAME, (r,g,b)); label: stage text (e.g. 'HEAT 1 OF 3') for tournaments."""
    set_layout(layout)
    rng = np.random.default_rng(seed)
    fx_rng = np.random.default_rng(seed + 999)
    n = int(rng.integers(5, 8))
    picked = [PALETTE[i] for i in rng.permutation(len(PALETTE))[:n]]
    runners = list(runners) if runners else picked
    n = len(runners)
    world = world or list(WORLDS2D)[int(rng.integers(len(WORLDS2D)))]
    cfg = WORLDS2D[world]

    frames, events, winner, win_frame = simulate(rng, n)
    race_start = int((INTRO_S + COUNT_S) * FPS)
    race_len = len(frames)
    outro_start = race_start + race_len
    total = outro_start + int(OUTRO_S * FPS)

    lane_h = (TRACK_BOT - TRACK_TOP) / n
    character = character or CHARACTERS[int(rng.integers(len(CHARACTERS)))]
    Char = character_classes()[character]
    s = min(1.9, lane_h / Char.DIV)
    toons = [Char(c, i, seed) for i, (_, c) in enumerate(runners)]
    bg = make_background(n, world)
    deco = make_deco_strip(world, FINISH_X + 2 * W, np.random.default_rng(seed + 5))

    kills = {e[2]: e for e in events if e[1] == "kill"}
    warns = {e[2]: e for e in events if e[1] == "warn"}
    buffs = [e for e in events if e[1] in ("boost", "slip")]
    bolts = {e[2]: bolt_points(fx_rng) for e in events if e[1] == "kill"}

    os.makedirs(out_dir, exist_ok=True)
    base = os.path.join(out_dir, name or f"race2d_{seed}")
    wav_path, mp4_path = base + ".wav", base + ".mp4"
    ev_s = [((race_start + e[0]) / FPS, e[1], e[3]) for e in events]
    audio = synth_audio(total / FPS, race_start / FPS, ev_s, (race_start + win_frame) / FPS, fx_rng)
    with wave.open(wav_path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes(audio.tobytes())

    ff = subprocess.Popen([
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
        "-i", wav_path, "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart", mp4_path,
    ], stdin=subprocess.PIPE)

    cam = 0.0
    confetti = [(fx_rng.uniform(0, W), fx_rng.uniform(-H, 0), fx_rng.uniform(250, 600), fx_rng.uniform(-80, 80),
                 PALETTE[int(fx_rng.integers(len(PALETTE)))][1], fx_rng.uniform(0, 6.28)) for _ in range(160)]
    frame_iter = range(0, total, 15) if preview else range(total)

    for F in frame_iter:
        rf = min(max(F - race_start, 0), race_len - 1)
        st = frames[rf]
        xs = st["x"]
        lead = xs[st["alive"]].max()
        cam_target = max(0.0, min(lead - 620, FINISH_X + 300 - W))
        cam = cam_target if F == 0 or preview else lerp(cam, cam_target, 0.15)

        img = bg.copy()
        dx = int(cam * 0.6) % max(1, deco.width - W)
        img.paste(deco.crop((dx, 0, dx + W, deco.height)), (0, TRACK_BOT + 30), deco.crop((dx, 0, dx + W, deco.height)))
        d = ImageDraw.Draw(img)

        step = 400
        for mx in range(int(cam // step) * step, int(cam + W) + step, step):
            sx = mx - cam
            if START_X < mx < FINISH_X:
                d.line([(sx, TRACK_TOP), (sx, TRACK_BOT)], fill=tuple(max(0, c - 25) for c in cfg["lanes"][0]), width=4)
                d.text((sx, TRACK_BOT + 60), f"{int((mx - START_X) / 10)}m", font=font(34), fill=(255, 255, 255),
                       anchor="mm", stroke_width=4, stroke_fill=OUTLINE)
        for lx, checker in ((START_X - 30, False), (FINISH_X, True)):
            sx = lx - cam
            if -40 < sx < W + 40:
                if checker:
                    sq = 20
                    for yy in range(TRACK_TOP, TRACK_BOT, sq):
                        for c in range(2):
                            col = (255, 255, 255) if ((yy // sq) + c) % 2 == 0 else (20, 20, 20)
                            d.rectangle([sx + c * sq, yy, sx + c * sq + sq, yy + sq], fill=col)
                    text_c(d, (sx + 20, TRACK_TOP - 55), "FINISH", 52, (255, 255, 255))
                else:
                    d.line([(sx, TRACK_TOP), (sx, TRACK_BOT)], fill=(255, 255, 255), width=8)

        shake = 0.0
        for i, (name, col) in enumerate(runners):
            gy = TRACK_TOP + (i + 1) * lane_h - 14
            sx = xs[i] - cam
            kill, warn = kills.get(i), warns.get(i)
            dead = kill is not None and rf >= kill[0] and F >= race_start
            dt_k = (rf - kill[0]) / FPS if kill else -1
            if kill and F >= race_start and 0 <= dt_k < 0.6:
                shake = max(shake, 22 * (1 - dt_k / 0.6))

            if dead and kill[3] == "TRAP":
                if dt_k < 0.5:
                    hole_w = 70 * s
                    d.ellipse([sx - hole_w, gy - 14, sx + hole_w, gy + 10], fill=(10, 10, 10))
                    sink = dt_k / 0.5
                    spr, (ax, ay) = toons[i].sprite("idle", s, shadow=False)
                    drop = 180 * s * sink
                    vis = spr.crop((0, 0, spr.width, max(1, int(ay - drop))))
                    img.paste(vis, (int(sx - ax), int(gy - ay + drop)), vis)
                elif dt_k < 1.0:
                    k = 1 - (dt_k - 0.5) / 0.5
                    d.ellipse([sx - 70 * s * k, gy - 14 * k, sx + 70 * s * k, gy + 10 * k], fill=(10, 10, 10))
            elif dead:
                if dt_k < 0.7 and kill[3] in ("METEOR", "BOMB"):   # thrown into the air, spinning
                    p = dt_k / 0.7
                    fly_y = gy - 25 * s - 420 * s * 4 * p * (1 - p)
                    toons[i].paste(img, sx - 60 * p * s, fly_y, "limp", s, angle=-math.pi / 2 - p * 3 * math.pi)
                elif -200 < sx < W + 200:
                    toons[i].paste(img, sx, gy, "splat", s, shadow=False)
            else:
                if sx < 10:
                    cy = gy - 60 * s
                    d.polygon([(8, cy), (40, cy - 22), (40, cy + 22)], fill=col, outline=OUTLINE)
                elif sx < W + 100:
                    if F >= race_start:
                        toons[i].paste(img, sx, gy, "run", s, phase=Char.run_phase(xs[i], s) + i)
                    else:
                        toons[i].paste(img, sx, gy, "idle", s, phase=F * 0.15 + i)
                    if st["eff"][i] == "BOOST":
                        for k in range(3):
                            yy = gy - (40 + 25 * k) * s
                            d.line([(sx - 60 * s - 40 * k, yy), (sx - 20 * s, yy)], fill=(255, 255, 255), width=5)
            if not dead and -50 < sx < W + 50 and F < race_start + 2 * FPS:
                d.text((sx + 75 * s, gy - 75 * s), name, font=font(int(56 * s)), fill=col, anchor="lm",
                       stroke_width=6, stroke_fill=OUTLINE)

            if warn and F >= race_start and warn[0] <= rf < (kill[0] if kill else warn[0] + 27):
                p = (rf - warn[0]) / max(1, ((kill[0] if kill else warn[0] + 27) - warn[0]))
                cx, cy = sx + 10 * s, gy - 70 * s
                kt = warn[3]
                if kt == "LIGHTNING":
                    for k in range(3):
                        ox = cx + (k - 1) * 45 * s
                        d.ellipse([ox - 50 * s, TRACK_TOP - 80 - 30 * s, ox + 50 * s, TRACK_TOP - 80 + 30 * s], fill=(60, 60, 70))
                elif kt == "METEOR":
                    mx_, my_ = lerp(cx + 500, cx, p), lerp(TRACK_TOP - 400, cy, p)
                    for k in range(6):
                        tr = 30 * s * (1 - k / 6)
                        tx, ty = mx_ + k * 40, my_ - k * 32
                        d.ellipse([tx - tr, ty - tr, tx + tr, ty + tr], fill=(255, 160 - k * 15, 40))
                    d.ellipse([mx_ - 32 * s, my_ - 32 * s, mx_ + 32 * s, my_ + 32 * s], fill=(110, 70, 50), outline=(255, 120, 0), width=5)
                elif kt == "BOMB":
                    bx = cx + 40 * s
                    by = lerp(TRACK_TOP - 100, gy - 30 * s, min(1, p * 2))
                    d.ellipse([bx - 28 * s, by - 28 * s, bx + 28 * s, by + 28 * s], fill=(25, 25, 30), outline=(90, 90, 100), width=3)
                    if (rf // 3) % 2:
                        d.ellipse([bx + 10 * s, by - 46 * s, bx + 26 * s, by - 30 * s], fill=(255, 220, 60))
                rr = 85 * s * (1 + 0.15 * math.sin(rf * 0.8))
                d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], outline=(255, 50, 50), width=6)
                d.line([(cx - rr - 15, cy), (cx + rr + 15, cy)], fill=(255, 50, 50), width=3)
                d.line([(cx, cy - rr - 15), (cx, cy + rr + 15)], fill=(255, 50, 50), width=3)

            if kill and F >= race_start and 0 <= dt_k < 0.8:
                cx, cy = sx + 10 * s, gy - 60 * s
                kt = kill[3]
                if kt == "LIGHTNING" and dt_k < 0.35:
                    pts = [(cx + bx * 0.9, lerp(TRACK_TOP - 80, cy, by)) for bx, by in bolts[i]]
                    d.line(pts, fill=(255, 255, 160), width=16)
                    d.line(pts, fill=(255, 255, 255), width=6)
                if kt in ("METEOR", "BOMB", "LIGHTNING"):
                    explosion(d, cx, cy, min(1, dt_k / 0.8), s if kt != "LIGHTNING" else 0.6 * s, seed=seed + i)

        for e in events:
            if e[1] == "kill" and e[3] == "LIGHTNING" and 0 <= rf - e[0] < 3 and F >= race_start:
                img = Image.blend(img, Image.new("RGB", (W, H), (255, 255, 255)), 0.45)
                d = ImageDraw.Draw(img)
        if shake > 0:
            img = ImageChops.offset(img, int(shake * math.sin(F * 2.1)), int(shake * math.cos(F * 1.7)))
            d = ImageDraw.Draw(img)

        for e in buffs:
            if F >= race_start and 0 <= rf - e[0] < int(1.2 * FPS):
                i = e[2]
                if kills.get(i) and rf >= kills[i][0]:
                    continue
                gy = TRACK_TOP + (i + 1) * lane_h - 14
                sx = max(120, min(W - 120, xs[i] - cam))
                text_c(d, (sx, max(500, gy - 135 * s)), "BOOST!" if e[1] == "boost" else "SLIP!", int(44 * s),
                       (120, 255, 120) if e[1] == "boost" else (255, 230, 90))

        alive_now = st["alive"] if F >= race_start else np.ones(n, bool)
        if F < race_start:
            pulse = 1 + 0.06 * math.sin(F * 0.3)
            if layout == "portrait":
                text_c(d, (W / 2, 105), label or "PICK YOUR", int(90 * pulse), (255, 255, 255), stroke=8)
                text_c(d, (W / 2, 210), "COLOR!" if not label else "PICK YOUR COLOR!", int(115 * pulse), (255, 220, 50), stroke=9)
                d.rounded_rectangle([W / 2 - 230, 395, W / 2 + 230, 445], 25, fill=(0, 0, 0))
                text_c(d, (W / 2, 420), cfg["title"], 38, (255, 255, 255), stroke=0)
                text_c(d, (W / 2, TRACK_BOT + 150), "Comment your pick below!", 54, (255, 255, 255))
            else:
                text_c(d, (W / 2, 62), f"{label}  -  PICK YOUR COLOR!" if label else "PICK YOUR COLOR!", int(66 * pulse), (255, 220, 50), stroke=8)
                d.rounded_rectangle([W - 330, 20, W - 30, 64], 22, fill=(0, 0, 0))
                text_c(d, (W - 180, 42), cfg["title"], 30, (255, 255, 255), stroke=0)
                text_c(d, (W / 2, TRACK_BOT + 90), "Comment your pick below!", 50, (255, 255, 255))
        elif F < outro_start:
            ttl = f"{label}  -  WHO WILL WIN?" if (label and layout == "landscape") else "WHO WILL WIN?"
            text_c(d, (W / 2, LAY["title_y"]), ttl, 84 if layout == "portrait" else 70, (255, 255, 255), stroke=8)
            prog = min(1, (lead - START_X) / (FINISH_X - START_X))
            by = LAY["bar_y"]
            d.rounded_rectangle([90, by, W - 90, by + 24], 12, fill=(30, 30, 40))
            d.rounded_rectangle([90, by, 90 + (W - 180) * prog, by + 24], 12, fill=(255, 220, 50))
        if F < outro_start:
            order = sorted(range(n), key=lambda i: (not alive_now[i], -xs[i]))
            cw = min(140, (W - 80) / n)
            x0 = W / 2 - cw * n / 2 + cw / 2
            for rank, i in enumerate(order):
                cx, r = x0 + rank * cw, cw * 0.36
                c = runners[i][1] if alive_now[i] else (90, 90, 95)
                d.ellipse([cx - r, CHIPS_Y - r, cx + r, CHIPS_Y + r], fill=c, outline=OUTLINE, width=4)
                if not alive_now[i]:
                    d.line([(cx - r * .6, CHIPS_Y - r * .6), (cx + r * .6, CHIPS_Y + r * .6)], fill=(255, 40, 40), width=7)
                    d.line([(cx - r * .6, CHIPS_Y + r * .6), (cx + r * .6, CHIPS_Y - r * .6)], fill=(255, 40, 40), width=7)
                elif F >= race_start:
                    text_c(d, (cx, CHIPS_Y), str(rank + 1), r * 1.1, (255, 255, 255), stroke=4)

        cd_t = (F - INTRO_S * FPS) / FPS
        if 0 <= cd_t < COUNT_S + 0.7:
            stp = COUNT_S / 3
            lab = ["3", "2", "1"][int(cd_t / stp)] if cd_t < COUNT_S else "GO!"
            frac = (cd_t % stp) / stp
            text_c(d, (W / 2, (TRACK_TOP + TRACK_BOT) / 2), lab, lerp(320, 200, frac) if lab != "GO!" else 260,
                   (255, 255, 255) if lab != "GO!" else (80, 255, 120), stroke=12)

        if F >= race_start:
            for e in events:
                if e[1] == "kill" and 0 <= rf - e[0] < int(1.4 * FPS):
                    pop = min(1, (rf - e[0]) / FPS / 0.15)
                    nm, cl = runners[e[2]]
                    cy = (TRACK_TOP + TRACK_BOT) / 2
                    bw = LAY["banner_w"]
                    d.rounded_rectangle([W / 2 - bw, cy - 130, W / 2 + bw, cy + 130], 30, fill=(15, 15, 22), outline=cl, width=8)
                    text_c(d, (W / 2, cy - 50), e[3] + "!", 90 * pop, (255, 255, 255), stroke=6)
                    text_c(d, (W / 2, cy + 55), f"{nm} IS OUT", 80 * pop, cl, stroke=6)
                if e[1] == "finish" and 0 <= rf - e[0] < int(1.5 * FPS):
                    text_c(d, (W / 2, (TRACK_TOP + TRACK_BOT) / 2), "FINISH!", 170, runners[e[2]][1], stroke=12)

        if F >= outro_start:
            t = (F - outro_start) / FPS
            img = Image.blend(img, Image.new("RGB", (W, H), (12, 12, 20)), min(0.88, t * 3))
            d = ImageDraw.Draw(img)
            nm, cl = runners[winner]
            for (cx0, cy0, vy, vx, cc, rot) in confetti:
                cx, cy = cx0 + vx * t, cy0 + vy * t + 300
                if 0 < cy < H:
                    a = rot + t * 6
                    d.polygon([(cx + 14 * math.cos(a + k * 1.57), cy + 7 * math.sin(a + k * 1.57)) for k in range(4)], fill=cc)
            wx, wg, wk, tx = LAY["win_x"], LAY["win_ground"], LAY["win_k"], LAY["txt_x"]
            d.ellipse([wx - 260 * wk, wg - 25, wx + 260 * wk, wg + 25], fill=(0, 0, 0))
            hop = 0
            toons[winner].paste(img, wx, wg - hop, "cheer", Char.WIN_S * wk, phase=t * 4.5, shadow=False)
            pop = min(1, t / 0.25)
            text_c(d, (tx, LAY["name_y"]), nm, 190 * pop, cl, stroke=12)
            text_c(d, (tx, LAY["wins_y"]), win_word, (160 if len(win_word) < 8 else 110) * pop, (255, 255, 255), stroke=12)
            if t > 0.8:
                text_c(d, (tx, LAY["pick_y"]), pick_line or f"Did you pick {nm}?", 66, (255, 255, 255))
            if t > 1.5:
                text_c(d, (tx, LAY["follow_y"]), follow_line or "Follow for a new race every day!", 50, (255, 220, 50))

        ff.stdin.write(img.tobytes())
        if preview and F % 150 == 0:
            img.save(f"{base}_f{F:05d}.png")

    ff.stdin.close()
    ff.wait()
    os.remove(wav_path)
    meta = {
        "seed": seed, "file": mp4_path, "style": "2d", "world": world, "character": character,
        "runners": [r[0] for r in runners], "winner": runners[winner][0],
        "eliminated": [(runners[e[2]][0], e[3]) for e in events if e[1] == "kill"],
        "duration_s": round(total / FPS, 1),
        "ranking": [runners[i][0] for i in sorted(range(n), key=lambda i: (-1 if i == winner else
            0 if frames[-1]["alive"][i] else 1, -frames[-1]["x"][i] if frames[-1]["alive"][i] else -next(e[0] for e in events if e[1] == "kill" and e[2] == i)))],
        "colors": {nm_: list(c_) for nm_, c_ in runners},
    }
    with open(base + ".json", "w") as fh:
        json.dump(meta, fh, indent=2)
    return mp4_path, meta


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", default="out")
    ap.add_argument("--world", choices=list(WORLDS2D), default=None)
    ap.add_argument("--preview", action="store_true")
    ap.add_argument("--character", choices=CHARACTERS, default=None)
    a = ap.parse_args()
    print(json.dumps(render_video(a.seed, a.out, a.world, a.preview, a.character)[1], indent=2))
