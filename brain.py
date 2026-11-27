"""The agent's memory and decisions.

- data/videos.json : every uploaded video (what it was + its race results + latest stats)
- data/state.json  : replied comment ids, quota usage per Pacific day
- learning         : which characters / places / 2D-3D / cameras get the most views -> choose more of them
- replies          : smart comment replies using the race results of that video
- data/report.md   : human-readable performance report
"""
import datetime as dt
import json
import math
import os
import random
import re
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
PT = ZoneInfo("America/Los_Angeles")          # YouTube quota resets at midnight Pacific time

UPLOAD_RESERVE = int(os.environ.get("UPLOADS_PER_DAY", "7")) * 1600 + 100   # units the daily upload run needs


# ---------------------------------------------------------------- persistence
def _load(name, default):
    try:
        with open(os.path.join(DATA, name)) as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _save(name, obj):
    os.makedirs(DATA, exist_ok=True)
    with open(os.path.join(DATA, name), "w") as fh:
        json.dump(obj, fh, indent=1, ensure_ascii=False)


def load_videos():
    return _load("videos.json", [])


def save_videos(v):
    _save("videos.json", v)


def load_state():
    s = _load("state.json", {})
    s.setdefault("replied", [])
    s.setdefault("quota", {})
    s.setdefault("uploads_done_pt", "")
    return s


def save_state(s):
    s["replied"] = s["replied"][-5000:]
    s["quota"] = dict(sorted(s["quota"].items())[-14:])
    _save("state.json", s)


# ---------------------------------------------------------------- quota budget
def pt_today():
    return dt.datetime.now(PT).date().isoformat()


def spend(state, units):
    d = pt_today()
    state["quota"][d] = state["quota"].get(d, 0) + units


def engage_budget(state):
    """Units the engagement run may still use today without starving tomorrow's uploads."""
    total = int(os.environ.get("QUOTA_UNITS", "10000"))
    used = state["quota"].get(pt_today(), 0)
    reserve = 0 if state.get("uploads_done_pt") == pt_today() else UPLOAD_RESERVE
    return max(0, total - used - reserve - 20)


# ---------------------------------------------------------------- learning
EXPLORE = float(os.environ.get("EXPLORE", "0.35"))


def _score(v):
    s = v.get("stats") or {}
    sc = math.log1p(s.get("views", 0))
    if v.get("retention"):
        sc += 0.01 * v["retention"].get("avg_pct", 0)
    return sc


def performance(videos, dim, kind="short", min_age_h=48):
    """{option: (mean score, count)} over videos old enough to judge."""
    now = dt.datetime.now(dt.timezone.utc)
    acc = {}
    for v in videos:
        if v.get("kind") != kind or dim not in v or not v.get("stats"):
            continue
        try:
            age = (now - dt.datetime.fromisoformat(v["published"].replace("Z", "+00:00"))).total_seconds() / 3600
        except Exception:
            continue
        if age < min_age_h:
            continue
        acc.setdefault(v[dim], []).append(_score(v))
    return {k: (sum(x) / len(x), len(x)) for k, x in acc.items()}


def choose(videos, dim, options, default, rng, allowed=None):
    """Mostly pick what performs best, sometimes explore (the default rotation)."""
    options = [o for o in options if allowed is None or o in allowed]
    perf = performance(videos, dim)
    judged = sum(c for _, c in perf.values())
    if judged < 8 or rng.random() < EXPLORE or not options:
        return default if default in options or not options else rng.choice(options)
    overall = sum(m * c for m, c in perf.values()) / judged
    scores = {o: (perf[o][0] if o in perf and perf[o][1] >= 2 else overall + 0.5) for o in options}   # optimism for untested
    mx = max(scores.values())
    weights = [math.exp((scores[o] - mx) / 0.4) for o in options]
    return rng.choices(options, weights)[0]


def best(videos, dim, options, default):
    perf = performance(videos, dim)
    cand = [(perf[o][0], o) for o in options if o in perf and perf[o][1] >= 2]
    return max(cand)[1] if cand else default


# ---------------------------------------------------------------- comment replies
COLORS = ["RED", "BLUE", "GREEN", "YELLOW", "PURPLE", "ORANGE", "PINK", "CYAN", "WHITE", "BLACK", "BROWN", "LIME"]
EMOJI = {"🔴": "RED", "❤": "RED", "🔵": "BLUE", "💙": "BLUE", "🟢": "GREEN", "💚": "GREEN", "🟡": "YELLOW", "💛": "YELLOW",
         "🟣": "PURPLE", "💜": "PURPLE", "🟠": "ORANGE", "🧡": "ORANGE", "🩷": "PINK", "⚪": "WHITE", "🤍": "WHITE",
         "⚫": "BLACK", "🖤": "BLACK", "🟤": "BROWN", "🤎": "BROWN"}
HAZARD = {"METEOR": "meteor ☄️", "LIGHTNING": "lightning ⚡", "MINE": "landmine 💥", "PIT": "trapdoor 🕳️",
          "BOULDER": "boulder 🪨", "BOMB": "bomb 💣", "TRAP": "trapdoor 🕳️"}


def colors_in(text):
    up = text.upper()
    found = [c for c in COLORS if re.search(r"\b" + c + r"\b", up)]
    found += [c for e, c in EMOJI.items() if e in text and c not in found]
    return found


COUNTRY_ALIASES = {"UNITED STATES": "USA", "AMERICA": "USA", "ENGLAND": "UK", "BRITAIN": "UK", "UNITED KINGDOM": "UK",
                   "SCOTLAND": "UK", "WALES": "UK", "KOREA": "SOUTH KOREA", "CZECH REPUBLIC": "CZECHIA", "HOLLAND": "NETHERLANDS",
                   "DOMINICAN REPUBLIC": "DOMINICAN REP.", "COTE D'IVOIRE": "IVORY COAST", "TURKIYE": "TURKEY", "TÜRKIYE": "TURKEY",
                   "BOSNIA AND HERZEGOVINA": "BOSNIA", "EMIRATES": "UAE", "DEUTSCHLAND": "GERMANY", "ESPAÑA": "SPAIN",
                   "BRASIL": "BRAZIL", "MÉXICO": "MEXICO", "HAYASTAN": "ARMENIA", "ՀԱՅԱՍՏԱՆ": "ARMENIA", "BHARAT": "INDIA",
                   "NIPPON": "JAPAN", "PERÚ": "PERU"}


def countries_in(text):
    """Country names mentioned in a comment (names, common aliases and flag emoji)."""
    try:
        from countries import COUNTRIES
    except Exception:
        return []
    up = text.upper()
    found = []
    for cc, lab, name in COUNTRIES:
        if re.search(r"(?<![A-Z])" + re.escape(name) + r"(?![A-Z])", up) or (len(lab) == 3 and re.search(r"\b" + lab + r"\b", text)):
            found.append(name)
    for alias, name in COUNTRY_ALIASES.items():
        if alias in up and name not in found:
            found.append(name)
    for a, b in re.findall("([\U0001F1E6-\U0001F1FF])([\U0001F1E6-\U0001F1FF])", text):
        cc = chr(ord(a) - 0x1F1E6 + 65) + chr(ord(b) - 0x1F1E6 + 65)
        name = next((n for c, _, n in COUNTRIES if c == cc), None)
        if name and name not in found:
            found.append(name)
    return found


def factory_reply(text, video, rng):
    picks = countries_in(text)
    winner = video.get("winner") or ""
    if not picks:
        return None
    c = picks[0]
    nice = c.title() if len(c) > 3 else c
    win = winner.title() if len(winner) > 3 else winner
    if c == winner:
        return rng.choice([f"🏆 {nice} WON the whole factory! You called it!", f"Champion {nice}! 🏆 What a run!",
                           f"{nice} survived every level and took the crown 👑🔥"])
    out = {n: lv for n, lv in video.get("eliminated", [])}
    if c in out:
        lv = str(out[c]).replace("LEVEL ", "")
        if lv == "1":
            return rng.choice([f"{nice} got shredded in level 1 😭 Revenge tomorrow?",
                               f"Oof, {nice} didn't make it past level 1… next time! 💪"])
        return rng.choice([f"{nice} made it to level {lv} before the shredder got it 😢 So close!",
                           f"Respect — {nice} survived until level {lv}! {win} won this one 🏆",
                           f"{nice} reached level {lv}! 🔥 Maybe the crown tomorrow?"])
    if video.get("runners") and c not in video["runners"]:
        return rng.choice([f"{nice} wasn't in this one 👀 Maybe in tomorrow's factory!",
                           f"No {nice} today 😅 Watch for it tomorrow!"])
    return rng.choice([f"Go {nice}! 🔥", f"Team {nice}! 🌍 New factory every day!"])


def make_reply(text, video, rng):
    """A short, varied reply based on what actually happened in that video's race."""
    if re.search(r"https?://|www\.", text, re.I):
        return None                                            # never engage with links/spam
    if (video or {}).get("format") == "factory":
        r = factory_reply(text, video, rng)
        if r:
            return r
        return rng.choice(["Thanks for watching! 🌍 Which country do you pick next time?",
                           "Comment your country before the next factory starts! 🏭", "❤️ Thanks! New factory every day!"])
    winner = (video or {}).get("winner") or (video or {}).get("champion")
    elim = {c: k for c, k in (video or {}).get("eliminated", [])}
    raced = set((video or {}).get("runners") or (video or {}).get("entrants") or [])
    picks = colors_in(text)
    if picks and winner:
        c = picks[0]
        if c == winner:
            return rng.choice([f"🏆 {c} WON! You called it — great pick!", f"Legendary pick! {c} took the win 🏆🔥",
                               f"{c} for the win! 🏁 You've got the eye for champions 👀", f"Called it! {c} crossed first 🏆"])
        if c in elim:
            hz = HAZARD.get(elim[c], "a trap")
            return rng.choice([f"Oof… {c} got taken out by the {hz} 😭 Revenge race tomorrow?",
                               f"RIP {c} 😢 that {hz} came out of nowhere. Try again in the next race!",
                               f"{c} was doing so well until the {hz} 💀 {winner} won this one!",
                               f"Unlucky! The {hz} got {c}… {winner} took the win this time 🏁"])
        if raced and c not in raced:
            return rng.choice([f"{c} sat this one out 👀 Keep an eye out for {c} in the next race!",
                               f"No {c} in this race 😅 {winner} won — pick again tomorrow!"])
        return rng.choice([f"{c} survived but {winner} was just faster 😅 So close!",
                           f"{c} made it to the end! {winner} took the win though 🏁 Next time!",
                           f"Respect — {c} survived everything! But {winner} won this one 🏆"])
    if picks:
        return rng.choice([f"Good luck {picks[0]}! 🍀 New race every day!", f"Team {picks[0]}! 🔥 Who do you pick next time?"])
    return rng.choice(["Thanks for watching! 🏁 Which color will you pick next race?", "Glad you enjoyed it! 🙌 New race every day!",
                       "Thanks! 🔥 Comment your color before the next race starts!", "❤️ Thanks for watching! Pick a color next time 👀"])


# ---------------------------------------------------------------- report
def write_report(videos):
    lines = [f"# Channel report — {dt.date.today().isoformat()}", ""]
    shorts = [v for v in videos if v.get("kind") == "short" and v.get("stats")]
    longs = [v for v in videos if v.get("kind") == "long" and v.get("stats")]
    tot = sum(v["stats"]["views"] for v in shorts + longs)
    lines += [f"**{len(shorts)} Shorts + {len(longs)} long videos tracked · {tot:,} total views**", ""]
    for dim, title in (("character", "Character"), ("world", "Place"), ("style", "Style"), ("camera", "3D camera")):
        perf = {}
        for v in shorts:
            if dim in v:
                perf.setdefault(v[dim], []).append(v["stats"]["views"])
        if not perf:
            continue
        lines += [f"## {title}", "", "| option | videos | avg views | best |", "|---|---|---|---|"]
        for k, vs in sorted(perf.items(), key=lambda kv: -sum(kv[1]) / len(kv[1])):
            lines.append(f"| {k} | {len(vs)} | {sum(vs) / len(vs):,.0f} | {max(vs):,} |")
        lines.append("")
    lines += ["## Top 10 videos", "", "| views | likes | avg % viewed | video |", "|---|---|---|---|"]
    for v in sorted(shorts + longs, key=lambda v: -v["stats"]["views"])[:10]:
        r = v.get("retention", {}).get("avg_pct")
        lines.append(f"| {v['stats']['views']:,} | {v['stats']['likes']} | {f'{r:.0f}%' if r else '-'} | "
                     f"[{v.get('title', v['video_id'])[:50]}](https://youtu.be/{v['video_id']}) |")
    os.makedirs(DATA, exist_ok=True)
    with open(os.path.join(DATA, "report.md"), "w") as fh:
        fh.write("\n".join(lines) + "\n")
