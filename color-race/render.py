"""
Color Race 3D — Shorts generator.

Python plans everything (race simulation, hazards, slow-motion, camera cuts, sound design),
then a headless-Chromium three.js renderer (web/) draws every frame in 3D, then ffmpeg encodes.

Usage:  python render.py --seed 123 --out out/          (full video)
        python render.py --seed 123 --out out/ --preview (every 10th frame, fast check)
"""
import argparse
import json
import os
import shutil
import subprocess
import wave

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
FPS = 30
SIM_HZ = 60
SR = 44100
TRACK_LEN = 200.0
HURDLES = [55.0, 110.0, 158.0]
KILL_KINDS = ["METEOR", "LIGHTNING", "MINE", "PIT", "BOULDER"]
WARN = 1.0   # seconds of sim time between a hazard appearing and it hitting

PALETTE = [
    ("RED", "#e8322f"), ("BLUE", "#2f6df0"), ("GREEN", "#25c26a"), ("YELLOW", "#f7cb15"),
    ("PURPLE", "#9b4dea"), ("ORANGE", "#ff7a00"), ("PINK", "#ff5fb4"), ("CYAN", "#00c8d6"),
    ("WHITE", "#f2f2f2"), ("BLACK", "#262626"),
]
THEMES = ["day", "sunset", "night"]
CHARACTERS = ["jelly", "person", "duck", "car", "marble"]
# location -> lighting moods that suit it
WORLDS = {
    "stadium": ["day", "sunset", "night"],
    "desert": ["day", "sunset"],
    "snow": ["day", "sunset"],
    "city": ["night", "sunset"],
    "forest": ["day", "sunset"],
    "volcano": ["volcano"],
}


# ------------------------------------------------------------------ simulation
def simulate(rng, n):
    dt = 1 / SIM_HZ
    x = np.zeros(n)
    v = np.zeros(n)
    target = rng.uniform(7.6, 9.0, n)
    alive = np.ones(n, bool)
    fin_t = [None] * n
    slow_until = np.zeros(n)
    boost_until = np.zeros(n)
    events = []

    n_kills = max(2, n - int(rng.integers(2, 4)))            # leave 2-3 for the final fight
    kill_fracs = [0.1 + 0.78 * (k + rng.uniform(0.25, 0.75)) / n_kills for k in range(n_kills)]
    kinds = list(rng.permutation(KILL_KINDS))
    while len(kinds) < n_kills:
        kinds += list(rng.permutation(KILL_KINDS))
    kill_kinds = [str(k) for k in kinds[:n_kills]]
    miss_fracs = sorted(rng.uniform(0.15, 0.8, 2))
    boost_fracs = sorted(rng.uniform(0.2, 0.85, 2))
    hurdle_trip_done = set()

    pending = []                     # (victim, t_kill, kind)
    xs = []
    t = 0.0
    winner = None
    t_end = None
    while True:
        alive_idx = [i for i in range(n) if alive[i]]
        lead = max(x[i] for i in alive_idx)
        prog = lead / TRACK_LEN
        busy = {p[0] for p in pending}

        if winner is None:
            while kill_fracs and prog >= kill_fracs[0]:
                kill_fracs.pop(0)
                kind = kill_kinds.pop(0)
                cand = [i for i in alive_idx if fin_t[i] is None and i not in busy]
                if len(alive_idx) - len(pending) <= 2 or not cand:
                    continue
                order = sorted(cand, key=lambda i: -x[i])
                r = rng.random()
                victim = order[0] if r < 0.4 else (order[-1] if r < 0.55 else int(rng.choice(cand)))
                pending.append((victim, t + WARN, kind))
                busy.add(victim)
            while miss_fracs and prog >= miss_fracs[0]:
                miss_fracs.pop(0)
                cand = [i for i in alive_idx if fin_t[i] is None and i not in busy]
                if cand:
                    who = int(rng.choice(cand))
                    events.append({"type": "miss", "who": who, "t": t + WARN,
                                   "kind": str(rng.choice(["METEOR", "MINE"])), "side": float(rng.choice([-1, 1]))})
                    slow_until[who] = max(slow_until[who], t + WARN + 0.6)   # staggers from the blast
            while boost_fracs and prog >= boost_fracs[0]:
                boost_fracs.pop(0)
                cand = [i for i in alive_idx if fin_t[i] is None]
                who = min(cand, key=lambda i: x[i]) if rng.random() < 0.6 else int(rng.choice(cand))
                boost_until[who] = t + 1.6
                events.append({"type": "boost", "who": int(who), "t": t})

        for p in list(pending):
            if t >= p[1]:
                pending.remove(p)
                if alive[p[0]] and fin_t[p[0]] is None:
                    alive[p[0]] = False
                    events.append({"type": "kill", "who": int(p[0]), "t": p[1], "kind": p[2], "x": float(x[p[0]])})

        for i in range(n):
            if not alive[i]:
                v[i] = 0
                continue
            if fin_t[i] is not None:
                v[i] = max(0.0, v[i] - 5.0 * dt)
            else:
                if rng.random() < dt / 1.2:
                    target[i] = rng.uniform(7.2, 9.6)
                tgt = target[i] + (lead - x[i]) * 0.05
                if prog > 0.8:
                    tgt += 0.8 * rng.random()
                if t < boost_until[i]:
                    tgt = 12.5
                if t < slow_until[i]:
                    tgt = 2.5
                ramp = min(1.0, t / 0.8)
                v[i] += (tgt * ramp - v[i]) * min(1, dt * 3)
            for h in HURDLES:   # occasional trip over a hurdle
                if (x[i] < h <= x[i] + v[i] * dt and fin_t[i] is None and h not in hurdle_trip_done
                        and i not in busy and rng.random() < 0.18):
                    hurdle_trip_done.add(h)
                    slow_until[i] = t + 0.8
                    events.append({"type": "trip", "who": i, "t": t, "x": h})
            x[i] += v[i] * dt
            if x[i] >= TRACK_LEN and fin_t[i] is None:
                fin_t[i] = t
                if winner is None:
                    winner = i
                    events.append({"type": "finish", "who": i, "t": t})
                    t_end = t + 2.2
        xs.append(x.copy())
        t += dt
        if t_end is not None and t >= t_end:
            break
        if t > 120:
            raise RuntimeError("race did not finish")

    t_win = [e for e in events if e["type"] == "finish"][0]["t"]
    fin = sorted([i for i in range(n) if fin_t[i] is not None], key=lambda i: fin_t[i])
    margin = (fin_t[fin[1]] - fin_t[fin[0]]) if len(fin) > 1 else 9.0
    events.sort(key=lambda e: e["t"])
    return np.array(xs), events, winner, t_win, margin


# ------------------------------------------------------------------ time remap + shots
def build_timeline(rng, n, xs, events, winner, t_win, margin, camera="behind"):
    cine = camera == "cinematic"
    intro_lineup, close_each = 1.3, 0.45
    intro = intro_lineup + n * close_each + 0.6
    T0 = intro + 1.8                     # race start in video seconds (3-2-1 = 1.8 s)
    t_race_end = (len(xs) - 1) / SIM_HZ

    slow = []
    for e in events:
        if e["type"] == "kill":
            slow.append((e["t"] - 0.25, e["t"] + 0.75, 0.3))
        elif e["type"] == "miss":
            slow.append((e["t"] - 0.1, e["t"] + 0.35, 0.5))
    slow.append((t_win - (0.6 if margin < 0.5 else 0.35), t_win + 0.25, 0.3))

    def rate(ts):
        r = 1.0
        for a, b, s in slow:
            if a <= ts < b:
                r = min(r, s)
        return r

    sim_t = []
    f = 0
    t = -T0
    while True:
        vt = f / FPS
        if vt < T0 - 1e-9:
            t = vt - T0
        elif t < 0:
            t = 0.0
        else:
            t += rate(t) / FPS
        t = min(t, t_race_end)
        sim_t.append(round(t, 5))
        f += 1
        if t >= t_race_end:
            break
    race_end_frame = len(sim_t)
    OUTRO = 4.5
    sim_t += [round(t_race_end, 5)] * int(OUTRO * FPS)
    total = len(sim_t)
    sim_arr = np.array(sim_t)

    def frame_of(ts):
        return int(np.searchsorted(sim_arr, ts)) if ts >= 0 else int((ts + T0) * FPS)

    # camera anchors (smoothed lead / tail of the alive pack) per video frame
    kill_t = {e["who"]: e["t"] for e in events if e["type"] == "kill"}
    lead_a, tail_a = [], []
    sl = stl = 0.0
    for f, ts in enumerate(sim_t):
        k = int(np.clip(round(ts * SIM_HZ), 0, len(xs) - 1))
        alive = [i for i in range(n) if not (i in kill_t and ts >= kill_t[i])]
        lx = max(xs[k][i] for i in alive)
        tx = min(xs[k][i] for i in alive)
        if f == 0:
            sl, stl = lx, tx
        sl += (lx - sl) * 0.15
        stl += (tx - stl) * 0.1
        lead_a.append(round(float(sl), 3))
        tail_a.append(round(float(stl), 3))

    shots = []
    f_lineup = int(intro_lineup * FPS)
    shots.append({"type": "lineup", "f0": 0, "f1": f_lineup})
    for k in range(n):
        a = f_lineup + int(k * close_each * FPS)
        shots.append({"type": "close", "who": k, "f0": a, "f1": f_lineup + int((k + 1) * close_each * FPS)})
    shots.append({"type": "lineup2", "f0": shots[-1]["f1"], "f1": int(intro * FPS)})
    shots.append({"type": "start_cine" if cine else "start", "f0": int(intro * FPS), "f1": int((T0 + 1.3) * FPS)})

    special = []
    for e in events:
        if e["type"] == "kill":
            special.append({"type": "kill_cine" if cine else "kill", "who": e["who"], "kind": e["kind"], "t": e["t"],
                            "f0": frame_of(e["t"] - 0.95), "f1": frame_of(e["t"] + 1.0)})
    special.append({"type": "finish_cine" if cine else "finish", "who": int(winner), "f0": frame_of(t_win - 2.2), "f1": race_end_frame})
    special.sort(key=lambda s: s["f0"])
    merged = []
    for s in special:
        if merged and s["f0"] < merged[-1]["f1"]:
            if s["type"].startswith("finish"):
                merged[-1]["f1"] = s["f0"]
            else:
                s["f0"] = merged[-1]["f1"]
        if s["f1"] - s["f0"] >= 12:
            merged.append(s)
    # endless-runner style: cameras behind the racers, looking down the track
    cycle = (["chase", "front", "side", "chase", "drone", "front", "side"] if cine
             else ["hero", "pack", "hero", "hero_high", "pack", "hero", "hero"])

    def pick_hero(f0, f1, prev):
        te = sim_arr[min(f1, len(sim_arr) - 1)] + 0.15
        k = int(np.clip(round(sim_arr[min(f0, len(sim_arr) - 1)] * SIM_HZ), 0, len(xs) - 1))
        cand = [i for i in range(n) if not (i in kill_t and kill_t[i] <= te)]
        if not cand:
            return int(winner)
        if len(cand) > 1 and prev in cand:
            cand.remove(prev)
        lead = max(cand, key=lambda i: xs[k][i])
        return int(lead) if rng.random() < 0.4 else int(rng.choice(cand))
    ci = int(rng.integers(len(cycle)))
    f = shots[-1]["f1"]
    for s in merged + [{"f0": race_end_frame, "f1": race_end_frame}]:
        while s["f0"] - f >= 24:
            ln = int(rng.uniform(2.0, 3.4) * FPS)
            if s["f0"] - (f + ln) < 24:
                ln = s["f0"] - f
            sh = {"type": cycle[ci % len(cycle)], "f0": f, "f1": f + ln}
            if sh["type"].startswith("hero"):
                sh["who"] = pick_hero(f, f + ln, shots[-1].get("who"))
            shots.append(sh)
            ci += 1
            f += ln
        if s["f0"] > f:
            shots[-1]["f1"] = s["f0"]
        if s["f1"] > s["f0"]:
            s["f0"] = max(s["f0"], f)
            shots.append(s)
            f = s["f1"]
    shots.append({"type": "outro", "f0": race_end_frame, "f1": total})

    return {
        "fps": FPS, "simHz": SIM_HZ, "trackLen": TRACK_LEN, "hurdles": HURDLES, "warn": WARN,
        "frames": total, "raceStartFrame": int(T0 * FPS), "raceEndFrame": race_end_frame,
        "introFrames": int(intro * FPS), "simT": sim_t, "lead": lead_a, "tail": tail_a,
        "shots": shots, "events": events, "winner": int(winner), "margin": float(margin),
        "xs": [[round(float(v), 3) for v in xs[:, i]] for i in range(n)],
        "slow": slow,
    }


# ------------------------------------------------------------------ audio
class Mixer:
    def __init__(self, seconds, rng):
        self.N = int(seconds * SR) + SR
        self.L = np.zeros(self.N)
        self.rng = rng

    def add(self, sig, at, gain=1.0, buf=None):
        buf = self.L if buf is None else buf
        i = int(at * SR)
        if i < 0:
            sig, i = sig[-i:], 0
        j = min(self.N, i + len(sig))
        if i < self.N and j > i:
            buf[i:j] += sig[: j - i] * gain

    def env(self, n, attack=0.003, decay=6.0):
        t = np.arange(n) / SR
        e = np.exp(-t * decay)
        a = min(n, int(attack * SR))
        if a > 0:
            e[:a] *= np.linspace(0, 1, a)
        return e

    def noise(self, dur):
        return self.rng.uniform(-1, 1, max(1, int(dur * SR)))

    def filt(self, sig, lo=20, hi=20000):
        F = np.fft.rfft(sig)
        fr = np.fft.rfftfreq(len(sig), 1 / SR)
        F[(fr < lo) | (fr > hi)] = 0
        return np.fft.irfft(F, len(sig))

    def sweep(self, f0, f1, dur, shape="sine"):
        n = max(1, int(dur * SR))
        f = np.geomspace(max(f0, 1), max(f1, 1), n)
        ph = 2 * np.pi * np.cumsum(f) / SR
        if shape == "saw":
            return 2 * ((ph / (2 * np.pi)) % 1) - 1
        if shape == "square":
            return np.sign(np.sin(ph))
        return np.sin(ph)

    def tone(self, f, dur, decay=5, shape="sine"):
        return self.sweep(f, f, dur, shape) * self.env(max(1, int(dur * SR)), decay=decay)

    def explosion(self, big=1.0):
        d = 2.5
        n = int(d * SR)
        out = self.filt(self.noise(d), 20, 900) * self.env(n, 0.002, 2.2) * 2.5
        out += self.sweep(90, 28, d) * self.env(n, 0.002, 2.5) * 1.4
        crack = self.filt(self.noise(0.25), 800, 9000) * self.env(int(0.25 * SR), 0.001, 18)
        out[: len(crack)] += crack
        return out * big

    def thunder(self):
        d = 2.8
        n = int(d * SR)
        out = self.filt(self.noise(d), 25, 300) * self.env(n, 0.05, 1.3) * 3
        crack = self.filt(self.noise(0.4), 1500, 12000) * self.env(int(0.4 * SR), 0.0005, 9) * 1.4
        zap = self.sweep(3000, 200, 0.3, "saw") * self.env(int(0.3 * SR), 0.001, 10) * 0.4
        out[: len(crack)] += crack
        out[: len(zap)] += zap
        return out

    def whistle(self, dur):
        n = max(1, int(dur * SR))
        s = self.sweep(1800, 300, dur)[:n] * np.linspace(0.1, 1, n) * 0.4
        s += self.filt(self.noise(dur), 200, 3000)[:n] * np.linspace(0, 1, n) ** 2 * 0.6
        return s

    def rumble(self, dur):
        n = max(1, int(dur * SR))
        return self.filt(self.noise(dur), 20, 160)[:n] * np.linspace(0.2, 1, n) * 2.5

    def whoosh_down(self):
        d = 0.9
        return (self.sweep(500, 50, d) * 0.7 + self.filt(self.noise(d), 100, 1200)[: int(d * SR)] * 0.6) * self.env(int(d * SR), 0.02, 3)

    def thud(self):
        d = 0.35
        n = int(d * SR)
        return (self.sweep(120, 40, d) + self.filt(self.noise(d), 30, 400)[:n]) * self.env(n, 0.001, 12)

    def gunshot(self):
        d = 0.8
        n = int(d * SR)
        return (self.filt(self.noise(d), 300, 10000)[:n] * self.env(n, 0.0005, 9) * 1.5
                + self.sweep(150, 50, d) * self.env(n, 0.001, 8))

    def riser(self, dur):
        n = int(dur * SR)
        return (self.sweep(80, 900, dur, "saw")[:n] * 0.15 + self.filt(self.noise(dur), 500, 6000)[:n] * 0.3) * np.linspace(0, 1, n) ** 2

    def creak_fall(self):
        out = np.zeros(int(1.2 * SR))
        a = self.sweep(300, 120, 0.3, "saw") * self.env(int(0.3 * SR), 0.01, 5) * 0.3
        b = self.sweep(900, 80, 1.0) * self.env(int(1.0 * SR), 0.01, 2) * 0.5
        out[: len(a)] += a
        i = int(0.15 * SR)
        out[i: i + len(b)] += b
        return out


def build_audio(tl, rng):
    fps = tl["fps"]
    total_s = tl["frames"] / fps
    m = Mixer(total_s, rng)
    sim_t = np.array(tl["simT"])
    T0 = tl["raceStartFrame"] / fps
    rend = tl["raceEndFrame"] / fps

    def vt(ts):
        if ts < 0:
            return T0 + ts
        return int(np.searchsorted(sim_t, ts)) / fps

    world = tl.get("world", "stadium")
    tt_ = np.arange(int((total_s + 1) * SR)) / SR
    if world in ("stadium", "city"):        # crowd
        amb = m.filt(m.noise(total_s + 1), 300, 2500) * 0.35 + m.filt(m.noise(total_s + 1), 80, 400) * 0.3
        m.add(amb, 0, 0.35 if world == "stadium" else 0.25)
    if world in ("desert", "snow", "forest"):  # wind gusts
        wind = m.filt(m.noise(total_s + 1), 150, 1200 if world != "snow" else 2500)
        wind *= 0.5 + 0.5 * np.sin(2 * np.pi * 0.13 * tt_) ** 2
        m.add(wind, 0, 0.35)
    if world == "forest":                      # birds
        for k in range(int(total_s / 1.7)):
            f0 = rng.uniform(2500, 4200)
            chirp = m.sweep(f0, f0 * rng.uniform(1.2, 1.6), 0.09) * m.env(int(0.09 * SR), 0.005, 25)
            for q in range(int(rng.integers(2, 5))):
                m.add(chirp, k * 1.7 + rng.uniform(0, 1) + q * 0.12, 0.12)
    if tl.get("character") == "car":           # engine drone that revs with the race
        T0_ = tl["raceStartFrame"] / fps
        dur = max(0.1, tl["raceEndFrame"] / fps - T0_)
        n_ = int(dur * SR)
        f_ = 55 + 25 * np.minimum(1, np.arange(n_) / SR / 1.5) + 6 * np.sin(np.arange(n_) / SR * 2.1)
        eng = np.sin(2 * np.pi * np.cumsum(f_) / SR) + 0.5 * np.sign(np.sin(2 * np.pi * np.cumsum(f_ * 2) / SR))
        m.add(m.filt(eng, 30, 900), T0_, 0.18)
    if world == "volcano":                     # deep rumble + lava crackle
        m.add(m.filt(m.noise(total_s + 1), 20, 120), 0, 1.2)
        for k in range(int(total_s * 6)):
            m.add(m.filt(m.noise(0.02), 1500, 8000) * m.env(int(0.02 * SR), 0.001, 80), rng.uniform(0, total_s), 0.15)

    intro_s = tl["introFrames"] / fps
    pad = m.sweep(55, 55, intro_s, "saw") * 0.08 + m.sweep(82.4, 82.4, intro_s, "saw") * 0.06
    pad = m.filt(pad, 20, 600) * np.minimum(1, np.arange(len(pad)) / (0.4 * SR))
    m.add(pad, 0)
    n_run = len(tl["runners"])
    for k in range(n_run):
        m.add(m.tone(1600, 0.06, 50), 1.3 + k * 0.45, 0.25)
    m.add(m.riser(1.8), T0 - 1.8, 0.8)
    for k in range(3):
        m.add(m.tone(700, 0.3, 8, "square"), T0 - 1.8 + k * 0.6, 0.3)
    m.add(m.gunshot(), T0, 1.0)

    # music, ducked during slow-mo
    beat = 60 / 150
    music = np.zeros(m.N)
    roots = [55.0, 55.0, 65.41, 49.0]
    kick = m.sweep(160, 45, 0.3) * m.env(int(0.3 * SR), 0.001, 11)
    snare = m.filt(m.noise(0.2), 900, 8000) * m.env(int(0.2 * SR), 0.001, 18) * 0.8 + m.tone(190, 0.2, 25) * 0.4
    hat = m.filt(m.noise(0.05), 6000, 16000) * m.env(int(0.05 * SR), 0.0005, 70)
    bass = {r: m.filt(m.sweep(r, r, beat * 0.95, "saw"), 20, 700) * m.env(int(beat * 0.95 * SR), 0.005, 3) for r in set(roots)}
    stab = {r: m.filt(m.tone(r * 8, beat * 0.5, 6, "square"), 200, 4000) for r in set(roots)}
    b, tt = 0, T0
    while tt < rend:
        m.add(kick, tt, 0.9, music)
        if b % 2:
            m.add(snare, tt, 0.6, music)
        m.add(hat, tt + beat / 2, 0.35, music)
        root = roots[(b // 8) % 4]
        m.add(bass[root], tt, 0.45, music)
        if b % 4 == 2:
            m.add(stab[root], tt + beat / 2, 0.08, music)
        tt += beat
        b += 1
    duck = np.ones(m.N)
    for a, bb, _ in tl["slow"]:
        duck[int(vt(a) * SR): int(vt(bb) * SR)] = 0.25
    duck = np.convolve(duck, np.ones(2000) / 2000, mode="same")
    m.L += music * duck

    for e in tl["events"]:
        t = vt(e["t"])
        warn_at = vt(e["t"] - tl["warn"])
        if e["type"] == "kill":
            k = e["kind"]
            m.add(m.whoosh_down(), vt(e["t"] - 0.25), 0.7)
            if k == "METEOR":
                m.add(m.whistle(t - warn_at), warn_at, 0.6)
                m.add(m.explosion(1.2), t)
            elif k == "MINE":
                for q in range(5):
                    m.add(m.tone(1800, 0.08, 30, "square"), warn_at + q * (t - warn_at) / 5, 0.2)
                m.add(m.explosion(1.0), t)
            elif k == "LIGHTNING":
                m.add(m.rumble(t - warn_at), warn_at, 0.3)
                m.add(m.thunder(), t)
            elif k == "PIT":
                m.add(m.creak_fall(), t - 0.05, 0.9)
            elif k == "BOULDER":
                m.add(m.rumble(t - warn_at + 0.3), warn_at - 0.3, 0.8)
                m.add(m.thud(), t, 2.0)
            m.add(m.thud(), vt(e["t"] + 0.9), 0.5)
            m.add(m.filt(m.noise(1.5), 300, 2500) * m.env(int(1.5 * SR), 0.15, 1.5), t + 0.1, 0.5)
        elif e["type"] == "miss":
            m.add(m.whistle(t - warn_at), warn_at, 0.4)
            m.add(m.explosion(0.7), t, 0.8)
        elif e["type"] == "boost":
            m.add(m.sweep(200, 1500, 0.5) * m.env(int(0.5 * SR), 0.01, 3), t, 0.4)
        elif e["type"] == "trip":
            m.add(m.thud(), t, 0.6)
        elif e["type"] == "finish":
            m.add(m.filt(m.noise(3.5), 300, 3000) * m.env(int(3.5 * SR), 0.2, 0.9), t, 1.0)

    for k, fq in enumerate([523.25, 659.25, 783.99, 1046.5, 783.99, 1046.5]):
        m.add(m.filt(m.tone(fq, 0.6 if k < 5 else 1.8, 3, "square"), 100, 5000), rend + 0.2 + k * 0.16, 0.18)

    out = np.tanh(m.L * 0.9)
    out /= max(1e-6, np.abs(out).max()) / 0.9
    return (out * 32767).astype(np.int16)


# ------------------------------------------------------------------ main
def render_video(seed, out_dir, preview=False, workers=None, world=None, character=None, camera="behind"):
    rng = np.random.default_rng(seed)
    n = int(rng.integers(6, 8))
    runners = [PALETTE[i] for i in rng.permutation(len(PALETTE))[:n]]
    pick = int(rng.integers(1000))
    world = world or list(WORLDS)[pick % len(WORLDS)]
    theme = WORLDS[world][(pick // len(WORLDS)) % len(WORLDS[world])]

    xs, events, winner, t_win, margin = simulate(rng, n)
    tl = build_timeline(rng, n, xs, events, winner, t_win, margin, camera)
    tl["runners"] = [{"name": a, "color": c} for a, c in runners]
    tl["theme"] = theme
    tl["world"] = world
    tl["character"] = character or CHARACTERS[pick % len(CHARACTERS)]
    tl["seed"] = seed

    os.makedirs(out_dir, exist_ok=True)
    base = os.path.join(out_dir, f"race_{seed}")
    tl_path = base + "_timeline.json"
    with open(tl_path, "w") as fh:
        json.dump(tl, fh)

    audio = build_audio(tl, np.random.default_rng(seed + 7))
    wav = base + ".wav"
    with wave.open(wav, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes(audio.tobytes())

    frames_dir = base + "_frames"
    shutil.rmtree(frames_dir, ignore_errors=True)
    os.makedirs(frames_dir)
    step = 10 if preview else 1
    subprocess.run(["node", os.path.join(HERE, "web", "render.js"), tl_path, frames_dir, str(step),
                    str(workers or 2)], check=True)

    mp4 = base + ".mp4"
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS / step), "-i", os.path.join(frames_dir, "%05d.jpg"),
        "-i", wav, "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
        "-r", str(FPS), "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", mp4,
    ], check=True)
    os.remove(wav)
    if not preview:
        shutil.rmtree(frames_dir, ignore_errors=True)
        os.remove(tl_path)

    meta = {
        "seed": seed, "file": mp4, "theme": theme, "world": world, "style": "3d", "character": tl["character"], "camera": camera,
        "runners": [r[0] for r in runners], "winner": runners[winner][0],
        "eliminated": [(runners[e["who"]][0], e["kind"]) for e in events if e["type"] == "kill"],
        "duration_s": round(tl["frames"] / FPS, 1),
    }
    with open(base + ".json", "w") as fh:
        json.dump(meta, fh, indent=2)
    return mp4, meta


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", default="out")
    ap.add_argument("--preview", action="store_true")
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--world", choices=list(WORLDS), default=None)
    ap.add_argument("--character", choices=CHARACTERS, default=None)
    ap.add_argument("--camera", choices=["behind", "cinematic"], default="behind")
    a = ap.parse_args()
    print(json.dumps(render_video(a.seed, a.out, a.preview, a.workers, a.world, a.character, a.camera)[1], indent=2))
