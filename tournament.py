"""Daily long video (16:9, about 2.5 min): the COLOR RACE TOURNAMENT.

12 colors -> 3 heats of 4 (each in a different place) -> heat winners + 1 lucky loser race the FINAL -> champion.
Also writes YouTube chapters and a 1280x720 thumbnail.

Usage: python tournament.py --seed 7 --character duck --out out/
"""
import argparse
import json
import math
import os
import subprocess
import wave

import numpy as np
from PIL import Image, ImageDraw

import render2d
from chars2d import character_classes
from render2d import EXTRA_COLORS, PALETTE, OUTLINE, font, text_c

W, H, FPS, SR = 1920, 1080, 30, 44100
WORLDS = ["stadium", "desert", "snow", "city", "forest", "volcano"]
CHAR_WORD = {"jelly": "JELLY BLOBS", "person": "RUNNERS", "duck": "DUCKS", "car": "TINY CARS", "marble": "MARBLES"}


# ---------------------------------------------------------------- title cards
def _card_audio(seconds, rng, hit_at=0.25):
    n = int(seconds * SR)
    t = np.arange(n) / SR
    out = np.zeros(n)
    rise = int(min(seconds, 1.2) * SR)
    f = np.geomspace(80, 700, rise)
    out[:rise] += np.sin(2 * np.pi * np.cumsum(f) / SR) * np.linspace(0, 0.25, rise)
    i = int(hit_at * SR)
    m = n - i
    out[i:] += (np.sin(2 * np.pi * np.cumsum(np.geomspace(140, 40, m)) / SR) * np.exp(-t[:m] * 5) * 0.8
                + rng.uniform(-1, 1, m) * np.exp(-t[:m] * 9) * 0.4)
    for k, fq in enumerate([392, 523, 659, 784]):           # little fanfare
        j = int((hit_at + 0.15 + k * 0.12) * SR)
        mm = min(n - j, int(0.5 * SR))
        if mm > 0:
            out[j:j + mm] += np.sign(np.sin(2 * np.pi * fq * t[:mm])) * np.exp(-t[:mm] * 5) * 0.12
    out = np.tanh(out) * 0.8
    return (out * 32767).astype(np.int16)


def render_card(path, seconds, draw, seed):
    wav = path + ".wav"
    with wave.open(wav, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes(_card_audio(seconds, np.random.default_rng(seed)).tobytes())
    ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                           "-r", str(FPS), "-i", "-", "-i", wav, "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                           "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-shortest", path], stdin=subprocess.PIPE)
    for f in range(int(seconds * FPS)):
        ff.stdin.write(draw(f / FPS).convert("RGB").tobytes())
    ff.stdin.close()
    ff.wait()
    os.remove(wav)


def _bg(top=(30, 20, 70), bot=(120, 30, 90)):
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    for y in range(H):
        t = y / H
        d.line([(0, y), (W, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(top, bot)))
    for k in range(14):        # light rays
        a = k / 14 * 2 * math.pi
        d.polygon([(W / 2, H / 2), (W / 2 + 2000 * math.cos(a), H / 2 + 2000 * math.sin(a)),
                   (W / 2 + 2000 * math.cos(a + 0.12), H / 2 + 2000 * math.sin(a + 0.12))], fill=tuple(int(c * 1.15) for c in top))
    return img


def draw_trophy(d, cx, cy, s):
    gold, dark = (255, 205, 40), (200, 140, 20)
    d.rounded_rectangle([cx - 70 * s, cy + 90 * s, cx + 70 * s, cy + 120 * s], 8, fill=dark, outline=OUTLINE, width=5)
    d.rectangle([cx - 16 * s, cy + 40 * s, cx + 16 * s, cy + 92 * s], fill=gold, outline=OUTLINE, width=5)
    for sgn in (-1, 1):
        d.ellipse([cx + sgn * 75 * s - 30 * s, cy - 70 * s, cx + sgn * 75 * s + 30 * s, cy - 10 * s], outline=OUTLINE, width=int(16 * s))
        d.ellipse([cx + sgn * 75 * s - 30 * s, cy - 70 * s, cx + sgn * 75 * s + 30 * s, cy - 10 * s], outline=gold, width=int(9 * s))
    d.pieslice([cx - 85 * s, cy - 150 * s, cx + 85 * s, cy + 60 * s], 0, 180, fill=gold, outline=OUTLINE, width=5)
    d.rectangle([cx - 85 * s, cy - 92 * s, cx + 85 * s, cy - 45 * s], fill=gold, outline=OUTLINE, width=5)
    d.rectangle([cx - 80 * s, cy - 88 * s, cx + 80 * s, cy - 45 * s], fill=gold)
    d.ellipse([cx - 45 * s, cy - 80 * s, cx - 20 * s, cy - 30 * s], fill=(255, 245, 190))


def characters_row(img, toons, names, colors, y, s, t, label=True, pose="idle"):
    n = len(toons)
    gap = min(360, (W - 200) / n)
    x0 = W / 2 - gap * (n - 1) / 2
    d = ImageDraw.Draw(img)
    for k, (tn, nm, col) in enumerate(zip(toons, names, colors)):
        x = x0 + k * gap
        hop = abs(math.sin(t * 5 + k)) * 18 if pose == "cheer" else 0
        tn.paste(img, x, y - hop, pose, s, phase=t * 3 + k)
        if label:
            text_c(d, (x, y + 45), nm, 34, col, stroke=5, stroke_fill=(255, 255, 255) if sum(col[:3]) < 200 else OUTLINE)


# ---------------------------------------------------------------- thumbnail
def make_thumbnail(path, character, entrants, seed):
    C = character_classes()[character]
    img = _bg((20, 30, 90), (200, 40, 90)).resize((W, H))
    toons = [C(c, i, seed) for i, (_, c) in enumerate(entrants)]
    d = ImageDraw.Draw(img)
    draw_trophy(d, W / 2, 420, 1.7)
    text_c(d, (W / 2, 120), "WHO WINS?", 200, (255, 230, 60), stroke=16)
    s = min(2.2, 1.6 * 100 / C.DIV)
    gap = (W - 160) / len(toons)
    for k, tn in enumerate(toons):
        tn.paste(img, 80 + gap * (k + 0.5), 1000 if k % 2 else 960, "cheer", s, phase=k)
    text_c(d, (W / 2, 690), f"12 {CHAR_WORD[character]}  ·  1 CHAMPION", 80, (255, 255, 255), stroke=10)
    img.resize((1280, 720), Image.LANCZOS).save(path, quality=92)


# ---------------------------------------------------------------- tournament
def make_tournament(seed, out_dir, character, start_world=0, race_no=1):
    os.makedirs(out_dir, exist_ok=True)
    rng = np.random.default_rng(seed)
    all_colors = PALETTE + EXTRA_COLORS
    order = rng.permutation(len(all_colors))
    entrants = [all_colors[i] for i in order[:12]]
    heats = [entrants[k * 4:(k + 1) * 4] for k in range(3)]
    worlds = [WORLDS[(start_world + k) % len(WORLDS)] for k in range(4)]
    C = character_classes()[character]
    tmp = os.path.join(out_dir, f"tour_{seed}_parts")
    os.makedirs(tmp, exist_ok=True)
    segments, chapters = [], []
    t_acc = 0.0

    def add(path, title):
        nonlocal t_acc
        dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                                   capture_output=True, text=True).stdout.strip())
        segments.append(path)
        chapters.append((t_acc, title))
        t_acc += dur

    # intro card
    toons = [C(c, i, seed) for i, (_, c) in enumerate(entrants)]
    base_bg = _bg()

    def intro(t):
        img = base_bg.copy()
        d = ImageDraw.Draw(img)
        pop = min(1, t / 0.3)
        text_c(d, (W / 2, 150), "COLOR RACE TOURNAMENT", 120 * pop, (255, 220, 50), stroke=12)
        text_c(d, (W / 2, 270), f"12 {CHAR_WORD[character]}  ·  3 HEATS  ·  1 CHAMPION", 60, (255, 255, 255), stroke=8)
        for row in range(2):
            idx = range(row * 6, row * 6 + 6)
            characters_row(img, [toons[i] for i in idx], [entrants[i][0] for i in idx], [entrants[i][1] for i in idx],
                           560 + row * 300, min(2.0, 1.6 * 100 / C.DIV), t)
        if t > 1.5:
            text_c(d, (W / 2, 1020), "Pick your champion in the comments!", 54, (255, 255, 255), stroke=7)
        return img

    p = os.path.join(tmp, "00_intro.mp4")
    render_card(p, 5.0, intro, seed)
    add(p, "Meet the 12 racers")

    winners = []
    for h, heat in enumerate(heats):
        nxt = f"Next: HEAT {h + 2}!" if h < 2 else "Next: THE FINAL!"
        _, meta = render2d.render_video(seed * 10 + h, tmp, world=worlds[h], character=character, layout="landscape",
                                        runners=heat, label=f"HEAT {h + 1} OF 3", win_word="ADVANCES!",
                                        follow_line=nxt, name=f"{h + 1:02d}_heat")
        winners.append(meta["ranking"])
        add(meta["file"], f"Heat {h + 1} ({render2d.WORLDS2D[worlds[h]]['title'].title()})")

    finalists = [r[0] for r in winners]
    lucky = winners[int(rng.integers(3))][1]                  # one lucky loser gets a second chance
    finalists.append(lucky)
    col = {nm: c for nm, c in entrants}
    fin_runners = [(nm, col[nm]) for nm in finalists]
    ftoons = [C(c, i, seed + 1) for i, (_, c) in enumerate(fin_runners)]

    def fin_card(t):
        img = base_bg.copy()
        d = ImageDraw.Draw(img)
        text_c(d, (W / 2, 160), "THE FINALISTS", 130 * min(1, t / 0.3), (255, 220, 50), stroke=12)
        characters_row(img, ftoons, finalists, [col[n] for n in finalists], 640, min(2.4, 2.0 * 100 / C.DIV), t, pose="cheer")
        text_c(d, (W / 2, 800), f"+ lucky loser: {lucky}", 50, (255, 255, 255), stroke=7)
        text_c(d, (W / 2, 960), "Who will be the CHAMPION?", 64, (255, 255, 255), stroke=8)
        return img

    p = os.path.join(tmp, "04_finalists.mp4")
    render_card(p, 4.0, fin_card, seed + 3)
    add(p, "The finalists")

    _, meta = render2d.render_video(seed * 10 + 9, tmp, world=worlds[3], character=character, layout="landscape",
                                    runners=fin_runners, label="THE FINAL", win_word="IS CHAMPION!",
                                    follow_line="Subscribe for tomorrow's tournament!", name="05_final")
    champion = meta["ranking"][0]
    add(meta["file"], "THE FINAL")

    # stitch everything (re-encode so all parts match)
    out = os.path.join(out_dir, f"tournament_{seed}.mp4")
    inputs = sum([["-i", s] for s in segments], [])
    fc = "".join(f"[{i}:v][{i}:a]" for i in range(len(segments))) + f"concat=n={len(segments)}:v=1:a=1[v][a]"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", fc, "-map", "[v]", "-map", "[a]",
                    "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
                    "-movflags", "+faststart", out], check=True)
    thumb = os.path.join(out_dir, f"tournament_{seed}.jpg")
    make_thumbnail(thumb, character, entrants, seed)
    for f in os.listdir(tmp):
        os.remove(os.path.join(tmp, f))
    os.rmdir(tmp)

    fmt = lambda s: f"{int(s // 60)}:{int(s % 60):02d}"  # noqa: E731
    chap = "\n".join(f"{fmt(t)} {name}" for t, name in chapters)
    meta = {
        "file": out, "thumbnail": thumb, "style": "tournament", "character": character, "worlds": worlds,
        "entrants": [nm for nm, _ in entrants], "finalists": finalists, "champion": champion,
        "duration_s": round(t_acc, 1), "chapters": chap,
        "title": f"COLOR RACE TOURNAMENT #{race_no} 🏆 12 {CHAR_WORD[character].title()}, Only ONE Champion!",
        "description": (f"12 colors. 3 heats. 1 champion. Pick your color before Heat 1 and comment it! 👇\n\n"
                        f"Chapters:\n{chap}\n\n"
                        "Meteors, lightning, landmines and trapdoors decide who makes it to the final.\n"
                        "New tournament every day - subscribe!\n\n#colorrace #pickacolor #tournament #race"),
    }
    with open(os.path.join(out_dir, f"tournament_{seed}.json"), "w") as fh:
        json.dump(meta, fh, indent=2, ensure_ascii=False)
    return out, meta


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", default="out")
    ap.add_argument("--character", default="jelly", choices=list(CHAR_WORD))
    a = ap.parse_args()
    print(json.dumps(make_tournament(a.seed, a.out, a.character)[1], indent=2, ensure_ascii=False))
