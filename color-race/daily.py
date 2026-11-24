"""The daily agent: renders today's Shorts + one long tournament video and uploads/schedules them on YouTube.

Env vars (all optional):
  SHORT_TIMES_UTC  HH:MM list, one Short per time   (default "08:00,11:00,14:00,17:00,20:00")
  LONG_TIME_UTC    HH:MM for the long video, or "off" (default "16:00")
  STYLES           styles cycled over the Shorts     (default "3d,2d,2d,3d,2d" -> 2x 3D + 3x 2D)
  UPLOAD           "0" = only render, don't upload
  YT_CLIENT_ID / YT_CLIENT_SECRET / YT_REFRESH_TOKEN  for uploading
"""
import datetime as dt
import json
import os
import random
import sys
import traceback

import render
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
    long_time = os.environ.get("LONG_TIME_UTC", "16:00").strip()
    styles = [x.strip() for x in os.environ.get("STYLES", "3d,2d,2d,3d,2d").split(",") if x.strip()]
    do_upload = os.environ.get("UPLOAD", "1") != "0" and bool(os.environ.get("YT_REFRESH_TOKEN"))
    out_dir = os.path.join("out", today.isoformat())
    os.makedirs(out_dir, exist_ok=True)
    character = CHARACTER_ORDER[day % len(CHARACTER_ORDER)]          # one character type per day
    who = CHARACTER_WORD[character]
    print(f"== {today}: character={character}, {len(times)} shorts + {'no' if long_time == 'off' else '1'} long video, upload={do_upload}")
    log, failed = [], 0
    n3d = 0                                                          # 1st 3D Short = behind-cam, 2nd = cinematic

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

    # ---- Shorts
    for i, hhmm in enumerate(times):
        try:
            seed = int(today.strftime("%Y%m%d")) * 10 + i
            race_no = day * len(times) + i + 1
            style = styles[(day + i) % len(styles)]
            world = WORLD_ORDER[(day * len(times) + i) % len(WORLD_ORDER)]
            print(f"-- short {i + 1}/{len(times)}: {style} {world} {character}", flush=True)
            if style == "2d":
                path, meta = render2d.render_video(seed, out_dir, world=world, character=character)
            else:
                camera = "behind" if n3d % 2 == 0 else "cinematic"
                n3d += 1
                path, meta = render.render_video(seed, out_dir, world=world, character=character, camera=camera)
            title = random.Random(seed).choice(TITLES).format(n=race_no, who=who)
            desc = DESCRIPTION.format(n_runners=len(meta["runners"]), place=world.upper(), who=who)
            entry = {"kind": "short", "race": race_no, "title": title, "publish_at": at_time(today, hhmm, now) or "now", **meta}
            entry.update(publish(path, title, desc, TAGS, at_time(today, hhmm, now)))
        except Exception as e:
            failed += 1
            traceback.print_exc()
            entry = {"kind": "short", "slot": hhmm, "error": str(e)[:300]}
        print(json.dumps(entry, indent=2, ensure_ascii=False), flush=True)
        log.append(entry)

    # ---- Long video: the daily tournament
    if long_time != "off":
        try:
            print("-- long video: tournament", flush=True)
            path, meta = tournament.make_tournament(int(today.strftime("%Y%m%d")) * 10 + 9, out_dir, character,
                                                    start_world=day % len(WORLD_ORDER), race_no=day + 1)
            entry = {"kind": "long", "publish_at": at_time(today, long_time, now) or "now", **meta}
            entry.update(publish(path, meta["title"], meta["description"], LONG_TAGS, at_time(today, long_time, now), meta["thumbnail"]))
        except Exception as e:
            failed += 1
            traceback.print_exc()
            entry = {"kind": "long", "error": str(e)[:300]}
        print(json.dumps({k: v for k, v in entry.items() if k != "description"}, indent=2, ensure_ascii=False), flush=True)
        log.append(entry)

    with open(os.path.join(out_dir, "log.json"), "w") as fh:
        json.dump(log, fh, indent=2, ensure_ascii=False)
    if failed:
        print(f"!! {failed} video(s) failed — see errors above")
        sys.exit(1)


if __name__ == "__main__":
    main()
