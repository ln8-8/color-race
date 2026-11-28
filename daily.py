"""The daily agent: renders today's Shorts + long videos and uploads/schedules them on YouTube.

Env vars (all optional):
  SHORT_TIMES_UTC  HH:MM list, one Short per time       (default "08:00,11:00,14:00,17:00,20:00")
  LONG_TIMES_UTC   HH:MM list, one long video per time  (default "15:00,19:00"; "off" = none)
  LONG_FORMAT      "factory" (all countries, 2-3 min, default) or "tournament" (color race tournament)
  SHORT_FORMAT     "countries" (default): every Short is a country race, each in a different place
                   "mixed": the old rotation of 3D colour races + country races (uses STYLES)
  STYLES           styles cycled over the Shorts in "mixed" mode (default "3d,2d,2d,3d,2d")
  UPLOAD           "0" = only render, don't upload
  YT_CLIENT_ID / YT_CLIENT_SECRET / YT_REFRESH_TOKEN  for uploading
"""
import datetime as dt
import json
import os
import random
import sys
import traceback

import brain
import render
import factory2d
import render2d
import tournament

EPOCH = dt.date(2026, 1, 1)
WORLD_ORDER = ["stadium", "desert", "snow", "city", "forest", "volcano"]
CHARACTER_ORDER = ["jelly", "person", "duck", "car", "marble"]
CHARACTER_WORD = {"jelly": "Jelly Blobs", "person": "Runners", "duck": "Ducks", "car": "Tiny Cars", "marble": "Marbles"}

TITLES = [
    "Pick a Color! Only ONE Survives 🏁 #shorts",
    "Choose Your {who}… Who Makes It? 😱 #shorts",
    "Comment Your Color BEFORE the Race! 🏃 #shorts",
    "Which Color Wins This Race? 🤔 #shorts",
    "Pick Fast! Who Survives the Deadly Race? ⚡ #shorts",
    "Meteors vs {who} — Pick Your Survivor! ☄️ #shorts",
    "Only One Makes It Out Alive… Pick a Color! 💥 #shorts",
    "{who} vs Lightning & Traps — Pick One! ⚡ #shorts",
    "Color Survival Race #{n} — Pick Now! #shorts",
]
DESCRIPTION = """Pick a color before the race starts and comment it below! 👇
Today's track: {place}. {n_runners} {who}. Meteors, lightning, landmines, trapdoors and boulders. Only one wins.

New races every day — subscribe so you don't miss your color's revenge.

#shorts #pickacolor #colorrace #race #whowillwin #satisfying"""
PLACE_EMOJI = {"factory": "🏭", "space": "🚀", "ice": "🧊", "jungle": "🌴", "volcano": "🌋", "candy": "🍭", "sea": "🦈", "neon": "🌃"}
FACTORY_TITLES = [
    "Which Country Survives the {place}? {e} #shorts",
    "32 Countries Enter the {place}, Only ONE Survives! 🌍 #shorts",
    "Find Your Country! Will It Escape the {pit}? {e} #shorts",
    "Country Ball Elimination: {place} Edition 🏆 #shorts",
    "Comment Your Country BEFORE Level 1! {e} #shorts",
    "The {pit} Decides the Champion! {e} #shorts",
]
FACTORY_DESCRIPTION = """Find your country and comment it below! 👇
32 country balls race through the {place}. Each level only the first half gets through the gate. The rest fall into the {pit}.
Today's champion: watch till the end!

New race every day — subscribe and see if your country survives tomorrow.

#shorts #countryballs #countries #marblerace #flags #whowillwin"""
LONG_FACTORY_TITLES = [
    "ALL {n} COUNTRIES in the {place} — Only ONE Survives! 🌍{e}",
    "{n} Countries vs the {pit}… Who Wins? 🏆",
    "Every Country in the World Races Through the {place} — Only 1 Champion! 🌍",
    "{n} Country Balls Elimination: {place} Edition — Find Your Country! 🏁",
]
LONG_FACTORY_DESCRIPTION = """ALL {n} countries of the world race through the {place}. Every level the slowest third falls into the {pit}.
Find your country and comment how far it got! 👇

Chapters:
{chapters}

New place every day — subscribe and see if your country becomes champion!

#countries #countryballs #marblerace #flags #elimination #whowillwin"""
LONG_FACTORY_TAGS = ["all countries", "countries race", "country balls", "flags", "marble race", "elimination", "who will win"]
FACTORY_TAGS = ["countries", "country balls", "flags", "marble race", "elimination", "who will win", "shorts", "satisfying"]
TAGS = ["pick a color", "color race", "who will win", "survival race", "shorts", "satisfying", "race simulation", "choose your color"]
LONG_TAGS = ["color race tournament", "pick a color", "who will win", "marble race", "race simulation", "tournament", "satisfying"]


def at_time(today, hhmm, now):
    """RFC3339 publish time, or None (publish immediately) if it's already too close/past."""
    h, m = map(int, hhmm.split(":"))
    when = dt.datetime.combine(today, dt.time(h, m), tzinfo=dt.timezone.utc)
    return when.strftime("%Y-%m-%dT%H:%M:%SZ") if when > now + dt.timedelta(minutes=20) else None


def main():
    now = dt.datetime.now(dt.timezone.utc)
    today = now.date()
    day = (today - EPOCH).days
    times = [t.strip() for t in os.environ.get("SHORT_TIMES_UTC", "08:00,11:00,14:00,17:00,20:00").split(",") if t.strip()]
    long_raw = os.environ.get("LONG_TIMES_UTC", os.environ.get("LONG_TIME_UTC", "15:00,19:00")).strip()
    long_times = [] if long_raw == "off" else [t.strip() for t in long_raw.split(",") if t.strip()]
    long_format = os.environ.get("LONG_FORMAT", "factory")
    short_format = os.environ.get("SHORT_FORMAT", "countries")
    styles = [x.strip() for x in os.environ.get("STYLES", "3d,2d,2d,3d,2d").split(",") if x.strip()]
    if short_format == "countries":
        styles = ["2d"]
    do_upload = os.environ.get("UPLOAD", "1") != "0" and bool(os.environ.get("YT_REFRESH_TOKEN"))
    out_dir = os.path.join("out", today.isoformat())
    os.makedirs(out_dir, exist_ok=True)
    max_3d = int(os.environ.get("MAX_3D", "2"))                        # 3D takes ~20 min each to render
    videos, state = brain.load_videos(), brain.load_state()
    # a delayed scheduled run must not redo a day that is already done (manual runs always go ahead)
    if os.environ.get("GITHUB_EVENT_NAME") == "schedule" and state.get("last_daily") == today.isoformat():
        print(f"== {today} already done earlier today - skipping this scheduled run")
        return
    print(f"== {today}: {len(times)} shorts + {len(long_times)} long videos ({long_format}), upload={do_upload}, "
          f"memory={len(videos)} videos")
    log, failed = [], 0
    n3d = 0
    # variety: a different place for every video today, no recent champion wins again, no repeated machine layout
    cutoff = (now - dt.timedelta(days=14)).isoformat()
    recent_winners = {v.get("winner") for v in videos if v.get("format") == "factory" and str(v.get("published", "")) >= cutoff}
    used_places, used_paths, day_winners = [], [], set()
    place_order = factory2d.THEME_NAMES

    def next_place(k, rng):
        default = place_order[(day * 7 + k) % len(place_order)]
        free = [p for p in place_order if p not in used_places] or list(place_order)
        if default not in free:
            default = free[0]
        place = brain.choose(videos, "world", place_order, default, rng, allowed=free)
        used_places.append(place)
        return place

    def fresh_seed(base, n, layout, lo, hi, mx):
        fseed, m = factory2d.pick_seed(base, n, layout, lo, hi, mx, avoid_winners=recent_winners | day_winners,
                                       avoid_paths=used_paths)
        day_winners.add(m["winner"])
        used_paths.append(m["paths"])
        return fseed
    starter = int(os.environ.get("QUOTA_UNITS", "10000")) >= 15000      # first comment only when quota allows

    def remember(entry, kind, extra):
        if entry.get("video_id"):
            rec = {"video_id": entry["video_id"], "kind": kind, "title": entry.get("title"),
                   "published": entry["publish_at"] if entry["publish_at"] != "now" else now.isoformat(), **extra}
            videos.append(rec)
            brain.spend(state, 1600)
            if starter:
                try:
                    from upload import post_comment
                    post_comment(entry["video_id"], "Which country did you pick? 👇 Comment it before level 1 ends!"
                                 if extra.get("format") == "factory" else
                                 "Which color did you pick? 👇 Comment it before the race ends!")
                    brain.spend(state, 50)
                except Exception as e:
                    print("starter comment failed:", str(e)[:150])

    def publish(path, title, desc, tags, publish_at, thumb=None):
        if not do_upload:
            return {}
        from upload import set_thumbnail, upload
        vid = upload(path, title, desc, tags, publish_at)
        res = {"video_id": vid, "url": f"https://youtube.com/watch?v={vid}"}
        if thumb:
            try:
                set_thumbnail(vid, thumb)
            except Exception as e:                       # custom thumbnails need a phone-verified channel
                res["thumbnail_error"] = str(e)[:200]
        return res

    jobs = []           # rendered videos waiting for upload: (priority, entry, upload args, kind, memory extra)

    # ---- render the Shorts
    for i, hhmm in enumerate(times):
        try:
            seed = int(today.strftime("%Y%m%d")) * 10 + i
            race_no = day * len(times) + i + 1
            rng = random.Random(seed)
            slot = day * len(times) + i
            # default = rotation (exploring); brain.choose = learned from analytics (exploiting what gets views)
            style = brain.choose(videos, "style", ["3d", "2d"], styles[(day + i) % len(styles)], rng,
                                 allowed=None if n3d < max_3d else ["2d"])
            world = brain.choose(videos, "world", WORLD_ORDER, WORLD_ORDER[slot % len(WORLD_ORDER)], rng)
            character = brain.choose(videos, "character", CHARACTER_ORDER, CHARACTER_ORDER[slot % len(CHARACTER_ORDER)], rng)
            who = CHARACTER_WORD[character]
            camera = None
            if style != "2d":
                print(f"-- short {i + 1}/{len(times)}: {style} {world} {character}", flush=True)
            else:
                print(f"-- short {i + 1}/{len(times)}: country race", flush=True)
            if style == "2d":                                       # 2D = the country race (Flag Factory)
                world = next_place(i, rng)
                character, who = "flags", "Countries"
                print(f"   -> country race in: {world}", flush=True)
                fseed = fresh_seed(seed, 32, "portrait", 35, 75, 12)      # pre-tested: flows smoothly, fresh winner
                path, meta = factory2d.render_video(fseed, out_dir, 32, "portrait", name=f"factory_short_{seed}", theme=world)
            else:
                camera = brain.choose(videos, "camera", ["behind", "cinematic"], "behind" if n3d % 2 == 0 else "cinematic", rng)
                n3d += 1
                path, meta = render.render_video(seed, out_dir, world=world, character=character, camera=camera)
            if style == "2d":
                fmt = dict(place=meta["place"], pit=meta["pit"].title(), e=PLACE_EMOJI.get(world, "🌍"))
                title = random.Random(seed).choice(FACTORY_TITLES).format(**fmt)
                desc, tags = FACTORY_DESCRIPTION.format(**fmt), FACTORY_TAGS + [meta["place"].lower()]
            else:
                title = random.Random(seed).choice(TITLES).format(n=race_no, who=who)
                desc, tags = DESCRIPTION.format(n_runners=len(meta["runners"]), place=world.upper(), who=who), TAGS
            entry = {"kind": "short", "race": race_no, "title": title, "description": desc,
                     "publish_at": at_time(today, hhmm, now) or "now", **meta}
            jobs.append((1 + i, entry, (path, title, desc, tags, at_time(today, hhmm, now), None), "short",
                         {"style": style, "world": world, "character": character, **({"camera": camera} if camera else {}),
                          "winner": meta["winner"], "eliminated": meta["eliminated"], "runners": meta["runners"],
                          **({"format": "factory"} if style == "2d" else {})}))
        except Exception as e:
            failed += 1
            traceback.print_exc()
            log.append({"kind": "short", "slot": hhmm, "error": str(e)[:300]})

    # ---- render the long videos (2-3 min): ALL countries in the Flag Factory
    for j, lt in enumerate(long_times):
        try:
            lseed = int(today.strftime("%Y%m%d")) * 10 + 5 + j
            print(f"-- long video {j + 1}/{len(long_times)}: {long_format}", flush=True)
            if long_format == "tournament":
                character = brain.best(videos, "character", CHARACTER_ORDER, CHARACTER_ORDER[day % len(CHARACTER_ORDER)])
                path, meta = tournament.make_tournament(lseed, out_dir, character, start_world=(day + j) % len(WORLD_ORDER),
                                                        race_no=day * len(long_times) + j + 1)
                extra = {"character": character, "champion": meta["champion"], "entrants": meta["entrants"], "winner": meta["champion"]}
                title, desc, tags = meta["title"], meta["description"], LONG_TAGS
            else:
                place = next_place(5 + j, random.Random(lseed))
                print(f"   -> all countries in: {place}", flush=True)
                fseed = fresh_seed(lseed, 999, "landscape", 120, 180, 20)        # pre-tested: 2-3 min, no jams
                path, meta = factory2d.render_video(fseed, out_dir, 999, "landscape", name=f"factory_long_{lseed}", theme=place)
                n_c = len(meta["countries"])
                fmt = dict(n=n_c, place=meta["place"], pit=meta["pit"].title(), e=PLACE_EMOJI.get(place, "🌍"))
                title = random.Random(lseed).choice(LONG_FACTORY_TITLES).format(**fmt)
                desc = LONG_FACTORY_DESCRIPTION.format(chapters=meta["chapters"], **fmt)
                tags = LONG_FACTORY_TAGS + [meta["place"].lower()]
                extra = {"format": "factory", "style": "factory-long", "world": place, "winner": meta["winner"],
                         "eliminated": meta["eliminated"], "runners": meta["runners"]}
            entry = {"kind": "long", "title": title, "description": desc, "publish_at": at_time(today, lt, now) or "now", **meta}
            jobs.append((0 + j * 0.1, entry, (path, title, desc, tags, at_time(today, lt, now), meta.get("thumbnail")), "long", extra))
        except Exception as e:
            failed += 1
            traceback.print_exc()
            log.append({"kind": "long", "slot": lt, "error": str(e)[:300]})

    # ---- YouTube's daily quota resets at midnight Pacific time. If the previous run already uploaded during
    # this Pacific day (e.g. it ran late), wait for the reset instead of hitting the quota after 2-3 uploads.
    if do_upload and jobs and state.get("uploads_done_pt") == brain.pt_today():
        nxt = dt.datetime.combine(dt.datetime.now(brain.PT).date() + dt.timedelta(days=1), dt.time(0, 3), tzinfo=brain.PT)
        wait = (nxt - dt.datetime.now(dt.timezone.utc)).total_seconds()
        if 0 < wait < 3 * 3600:
            print(f"== today's quota was already used by the previous run - waiting {wait / 60:.0f} min for the "
                  f"Pacific-midnight reset before uploading", flush=True)
            import time
            time.sleep(wait)

    # ---- upload: most valuable first (tournament, then Shorts in order); stop at YouTube's daily upload limit
    limit_hit, pending = False, []
    for _, entry, args, kind, extra in sorted(jobs, key=lambda j: j[0]):
        if limit_hit:
            entry["status"] = "NOT UPLOADED (daily upload limit) - upload by hand from the run's Artifacts"
            pending.append(entry)
        else:
            try:
                entry.update(publish(*args))
                remember(entry, kind, extra)
                if kind == "long" and entry.get("video_id") and not entry.get("thumbnail_error"):
                    brain.spend(state, 50)
            except Exception as e:
                if any(k in str(e) for k in ("uploadLimitExceeded", "exceeded the number of videos", "quotaExceeded")):
                    limit_hit = True
                    print("!! YouTube says this channel reached its upload limit for now - the rest are kept for manual upload")
                    print("   YouTube said:", str(e)[:300])
                    entry["status"] = "NOT UPLOADED (daily upload limit) - upload by hand from the run's Artifacts"
                    pending.append(entry)
                else:
                    failed += 1
                    traceback.print_exc()
                    entry["error"] = str(e)[:300]
        print(json.dumps({k: v for k, v in entry.items() if k not in ("description", "colors")}, indent=2, ensure_ascii=False), flush=True)
        log.append(entry)
    if pending:
        print("\n== Upload these by hand in YouTube Studio (files are in this run's Artifacts):")
        for e in pending:
            print(f"   {os.path.basename(e['file'])}  ->  title: {e['title']}  (publish at {e['publish_at']})")

    if do_upload:
        state["uploads_done_pt"] = brain.pt_today()
        if any(e.get("video_id") for e in log) or limit_hit:
            state["last_daily"] = today.isoformat()
    brain.save_videos(videos)
    brain.save_state(state)
    with open(os.path.join(out_dir, "log.json"), "w") as fh:
        json.dump(log, fh, indent=2, ensure_ascii=False)
    if failed:
        print(f"!! {failed} video(s) failed — see errors above")
        sys.exit(1)


if __name__ == "__main__":
    main()
