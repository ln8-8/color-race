"""Engagement agent (runs every few hours):
  1. refreshes views / likes / comments (+ retention from YouTube Analytics) for recent videos
  2. replies to new comments on recent videos, using that video's race results
  3. writes data/report.md
Stays inside the daily YouTube quota and always keeps enough for tomorrow's uploads.

Env: YT_CLIENT_ID / YT_CLIENT_SECRET / YT_REFRESH_TOKEN, QUOTA_UNITS (default 10000),
     MAX_REPLIES (per run, default 25), REPLY ("0" = don't reply, only read stats)
"""
import datetime as dt
import os
import random
import sys

import brain


def main():
    if not os.environ.get("YT_REFRESH_TOKEN"):
        print("no YouTube token configured - nothing to do")
        return
    import upload as yt

    videos, state = brain.load_videos(), brain.load_state()
    by_id = {v["video_id"]: v for v in videos if v.get("video_id")}
    now = dt.datetime.now(dt.timezone.utc)
    print(f"budget at start: {brain.engage_budget(state)} units")

    # --- discover uploads (also picks up videos made before the agent had memory)
    me, uploads_pl = yt.my_channel()
    brain.spend(state, 1)
    for vid, pub in yt.recent_uploads(uploads_pl, 50):
        if vid not in by_id:
            v = {"video_id": vid, "kind": "unknown", "published": pub or now.isoformat()}
            videos.append(v)
            by_id[vid] = v
    brain.spend(state, 1)

    # --- stats for videos from the last 30 days
    def age_days(v):
        try:
            return (now - dt.datetime.fromisoformat(v["published"].replace("Z", "+00:00"))).total_seconds() / 86400
        except Exception:
            return 999
    recent = [v for v in videos if age_days(v) <= 30]
    ids = [v["video_id"] for v in recent]
    stats = yt.video_stats(ids)
    brain.spend(state, max(1, (len(ids) + 49) // 50))
    for vid, s in stats.items():
        by_id[vid]["stats"] = {k: s[k] for k in ("views", "likes", "comments")}
        by_id[vid].setdefault("title", s["title"])
        if s.get("published"):
            by_id[vid]["published"] = s["published"]
        if by_id[vid].get("kind") == "unknown":
            by_id[vid]["kind"] = "short" if "#shorts" in s["title"].lower() else "long"
    for vid, r in yt.retention(ids).items():      # separate Analytics quota
        if vid in by_id:
            by_id[vid]["retention"] = r

    # --- reply to new comments (newest videos first)
    replied = set(state["replied"])
    n, max_replies = 0, int(os.environ.get("MAX_REPLIES", "25"))
    rng = random.Random(now.timestamp())
    if os.environ.get("REPLY", "1") != "0":
        for v in sorted([v for v in recent if age_days(v) <= 7 and (v.get("stats") or {}).get("comments", 1) > 0],
                        key=age_days):
            if brain.engage_budget(state) < 60 or n >= max_replies:
                break
            threads = yt.comment_threads(v["video_id"])
            brain.spend(state, 1)
            for th in threads:
                top = th["snippet"]["topLevelComment"]
                cid, sn = top["id"], top["snippet"]
                if cid in replied or sn.get("authorChannelId", {}).get("value") == me:
                    continue
                if any(c["snippet"].get("authorChannelId", {}).get("value") == me for c in th.get("replies", {}).get("comments", [])):
                    replied.add(cid)
                    continue
                text = brain.make_reply(sn.get("textDisplay", ""), v, rng)
                replied.add(cid)
                if not text:
                    continue
                if brain.engage_budget(state) < 60 or n >= max_replies:
                    break
                try:
                    yt.reply(cid, text)
                    brain.spend(state, 50)
                    n += 1
                    print(f"replied on {v['video_id']}: {text}")
                except Exception as e:
                    print("reply failed:", str(e)[:200])
    state["replied"] = list(replied)

    brain.save_videos(videos)
    brain.save_state(state)
    brain.write_report(videos)
    print(f"done: {len(stats)} videos updated, {n} replies, budget left {brain.engage_budget(state)} units")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("engage failed:", e)
        sys.exit(1)
