"""YouTube API helpers: upload, thumbnails, stats, analytics, comments.

Env vars required: YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN
Scopes requested by get_token.py: youtube.upload, youtube.force-ssl, yt-analytics.readonly
"""
import datetime as dt
import os

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
          "https://www.googleapis.com/auth/youtube.force-ssl",
          "https://www.googleapis.com/auth/yt-analytics.readonly"]

# YouTube Data API quota cost per call
COST = {"insert": 1600, "thumbnail": 50, "comment": 50, "list": 1}
_cache = {}


def _creds():
    # scopes=None: use whatever the owner granted (so an older token without analytics still works)
    return Credentials(None, refresh_token=os.environ["YT_REFRESH_TOKEN"], token_uri="https://oauth2.googleapis.com/token",
                       client_id=os.environ["YT_CLIENT_ID"], client_secret=os.environ["YT_CLIENT_SECRET"])


def youtube():
    if "yt" not in _cache:
        _cache["yt"] = build("youtube", "v3", credentials=_creds(), cache_discovery=False)
    return _cache["yt"]


def analytics():
    if "ya" not in _cache:
        _cache["ya"] = build("youtubeAnalytics", "v2", credentials=_creds(), cache_discovery=False)
    return _cache["ya"]


# ---------------------------------------------------------------- uploading
def upload(path, title, description, tags, publish_at=None):
    """publish_at: RFC3339 UTC string (e.g. 2026-11-24T14:00:00Z) to schedule, or None to publish now."""
    status = {"privacyStatus": "private" if publish_at else os.environ.get("YT_PRIVACY", "public"),
              "selfDeclaredMadeForKids": False}
    if publish_at:
        status["publishAt"] = publish_at
    body = {"snippet": {"title": title[:100], "description": description, "tags": tags, "categoryId": "24"}, "status": status}
    req = youtube().videos().insert(part="snippet,status", body=body,
                                    media_body=MediaFileUpload(path, mimetype="video/mp4", chunksize=-1, resumable=True))
    resp = None
    while resp is None:
        _, resp = req.next_chunk()
    return resp["id"]


def set_thumbnail(video_id, path):
    """Custom thumbnail (works once the channel is phone-verified)."""
    youtube().thumbnails().set(videoId=video_id, media_body=MediaFileUpload(path, mimetype="image/jpeg")).execute()


# ---------------------------------------------------------------- reading
def my_channel():
    r = youtube().channels().list(part="id,contentDetails", mine=True).execute()["items"][0]
    return r["id"], r["contentDetails"]["relatedPlaylists"]["uploads"]


def recent_uploads(playlist_id, n=50):
    r = youtube().playlistItems().list(part="contentDetails", playlistId=playlist_id, maxResults=min(50, n)).execute()
    return [(it["contentDetails"]["videoId"], it["contentDetails"].get("videoPublishedAt")) for it in r.get("items", [])]


def video_stats(ids):
    """{video_id: {views, likes, comments, published}} — 1 quota unit per 50 videos."""
    out = {}
    for k in range(0, len(ids), 50):
        r = youtube().videos().list(part="statistics,snippet", id=",".join(ids[k:k + 50])).execute()
        for it in r.get("items", []):
            s = it.get("statistics", {})
            out[it["id"]] = {"views": int(s.get("viewCount", 0)), "likes": int(s.get("likeCount", 0)),
                             "comments": int(s.get("commentCount", 0)), "published": it["snippet"].get("publishedAt"),
                             "title": it["snippet"].get("title", "")}
    return out


def retention(ids, start="2026-01-01"):
    """{video_id: averageViewPercentage} from YouTube Analytics (needs yt-analytics.readonly). Empty dict if unavailable."""
    if not ids:
        return {}
    try:
        r = analytics().reports().query(ids="channel==MINE", startDate=start, endDate=dt.date.today().isoformat(),
                                        metrics="views,averageViewPercentage,averageViewDuration", dimensions="video",
                                        filters="video==" + ",".join(ids[:200]), maxResults=200).execute()
        return {row[0]: {"avg_pct": float(row[2]), "avg_sec": float(row[3])} for row in r.get("rows", [])}
    except Exception as e:  # no analytics scope yet, or API not enabled
        print("analytics unavailable:", str(e)[:150])
        return {}


def comment_threads(video_id, max_results=50):
    r = youtube().commentThreads().list(part="snippet,replies", videoId=video_id, maxResults=max_results,
                                        order="time", textFormat="plainText").execute()
    return r.get("items", [])


# ---------------------------------------------------------------- writing comments
def reply(parent_id, text):
    youtube().comments().insert(part="snippet", body={"snippet": {"parentId": parent_id, "textOriginal": text}}).execute()


def post_comment(video_id, text):
    youtube().commentThreads().insert(part="snippet", body={"snippet": {"videoId": video_id, "topLevelComment": {
        "snippet": {"textOriginal": text}}}}).execute()
