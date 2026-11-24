"""Upload a video to YouTube using a stored OAuth refresh token.

Env vars required: YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN
"""
import os

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.force-ssl"]


def youtube():
    creds = Credentials(
        None,
        refresh_token=os.environ["YT_REFRESH_TOKEN"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["YT_CLIENT_ID"],
        client_secret=os.environ["YT_CLIENT_SECRET"],
        scopes=SCOPES,
    )
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def upload(path, title, description, tags, publish_at=None):
    """publish_at: RFC3339 UTC string (e.g. 2026-11-24T14:00:00Z) to schedule, or None to publish now."""
    status = {
        "privacyStatus": "private" if publish_at else os.environ.get("YT_PRIVACY", "public"),
        "selfDeclaredMadeForKids": False,
    }
    if publish_at:
        status["publishAt"] = publish_at
    body = {
        "snippet": {"title": title[:100], "description": description, "tags": tags, "categoryId": "24"},
        "status": status,
    }
    req = youtube().videos().insert(
        part="snippet,status",
        body=body,
        media_body=MediaFileUpload(path, mimetype="video/mp4", chunksize=-1, resumable=True),
    )
    resp = None
    while resp is None:
        _, resp = req.next_chunk()
    return resp["id"]


def set_thumbnail(video_id, path):
    """Custom thumbnail (works once the channel is phone-verified)."""
    youtube().thumbnails().set(videoId=video_id, media_body=MediaFileUpload(path, mimetype="image/jpeg")).execute()
