"""Uploads the videos a daily run rendered but could not upload (YouTube quota / upload limit).

The upload-pending workflow downloads that run's Artifacts into ./pending and runs this script.
Videos whose publish time already passed go public right away; the others are scheduled as planned.
Each file is uploaded only once, even if this is run again.
"""
import datetime as dt
import glob
import json
import os
import sys

import brain
import daily
from upload import set_thumbnail, upload

LIMIT_ERRORS = ("uploadLimitExceeded", "exceeded the number of videos", "quotaExceeded")


def main(root="pending"):
    now = dt.datetime.now(dt.timezone.utc)
    videos, state = brain.load_videos(), brain.load_state()
    done_files = {v.get("source_file") for v in videos}
    done_titles = {(v.get("title"), str(v.get("published", ""))[:10]) for v in videos}
    todo = []
    for log_path in glob.glob(os.path.join(root, "**", "log.json"), recursive=True):
        for e in json.load(open(log_path)):
            if str(e.get("status", "")).startswith("NOT UPLOADED"):
                e["_path"] = os.path.join(os.path.dirname(log_path), os.path.basename(e["file"]))
                todo.append(e)
    todo.sort(key=lambda e: (e["kind"] != "long", e.get("publish_at", "")))
    print(f"== {len(todo)} video(s) waiting for upload")
    uploaded = 0
    for e in todo:
        name = os.path.basename(e["file"])
        planned = e.get("publish_at") or "now"
        if name in done_files or (e["title"], planned[:10]) in done_titles:
            print(f"   {name}: already uploaded - skipping")
            continue
        if not os.path.exists(e["_path"]):
            print(f"   {name}: file missing in the Artifacts - skipping")
            continue
        publish_at = None
        if planned != "now" and dt.datetime.fromisoformat(planned.replace("Z", "+00:00")) > now + dt.timedelta(minutes=20):
            publish_at = planned
        factory = e.get("style") == "factory"
        if e["kind"] == "long":
            tags = daily.LONG_FACTORY_TAGS + ([e["place"].lower()] if e.get("place") else [])
        else:
            tags = (daily.FACTORY_TAGS + ([e["place"].lower()] if e.get("place") else [])) if factory else daily.TAGS
        try:
            vid = upload(e["_path"], e["title"], e.get("description", ""), tags, publish_at)
        except Exception as ex:
            if any(k in str(ex) for k in LIMIT_ERRORS):
                print(f"!! YouTube limit still reached ({str(ex)[:160]}) - try again later")
                break
            raise
        brain.spend(state, 1600)
        if e["kind"] == "long" and e.get("thumbnail"):
            thumb = os.path.join(os.path.dirname(e["_path"]), os.path.basename(e["thumbnail"]))
            try:
                set_thumbnail(vid, thumb)
                brain.spend(state, 50)
            except Exception as ex:
                print("   thumbnail failed:", str(ex)[:150])
        rec = {"video_id": vid, "kind": e["kind"], "title": e["title"], "source_file": name,
               "published": publish_at or now.isoformat()}
        for k in ("style", "world", "character", "camera", "winner", "eliminated", "runners"):
            if k in e:
                rec[k] = e[k]
        if factory:
            rec["format"] = "factory"
            rec["character"] = "flags"
        videos.append(rec)
        uploaded += 1
        print(f"   uploaded {name} -> https://youtube.com/watch?v={vid}  ({publish_at or 'public now'})  {e['title']}")
    if uploaded:
        state["uploads_done_pt"] = brain.pt_today()      # the next daily run waits for the quota reset if needed
    brain.save_videos(videos)
    brain.save_state(state)
    print(f"== uploaded {uploaded}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "pending")
