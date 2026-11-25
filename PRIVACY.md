# Privacy Policy — Color Race Uploader

_Last updated: November 25, 2026_

**Color Race Uploader uses YouTube API Services.**
By using it you also agree to the [YouTube Terms of Service](https://www.youtube.com/t/terms).
Google's privacy practices are described in the [Google Privacy Policy](http://www.google.com/policies/privacy).

## 1. What the app is
Color Race Uploader is a private automation tool. It generates original animated race videos with its own code and
uploads them to the owner's own YouTube channel through the YouTube Data API v3. It has no other users.

## 2. What data it accesses (YouTube API Services)
- It uses OAuth 2.0 to sign in **only with the channel owner's own Google account**.
- Scopes used: `youtube.upload` (to upload videos), `youtube.force-ssl` (to set thumbnails and to read and reply to
  comments on the owner's own videos) and `yt-analytics.readonly` (to read the owner's own channel statistics).
- API methods used: `videos.insert`, `thumbnails.set`, `videos.list`, `channels.list`, `playlistItems.list`,
  `commentThreads.list`, `comments.insert` (replies), `commentThreads.insert`, and YouTube Analytics `reports.query`.
- **Comments:** the tool reads public comments on the owner's own videos only, so it can post a short reply as the channel.
  The comment text is used once to write the reply and is **not stored**. Only the comment ID is kept, to avoid replying twice.
  No commenter names, profiles or other personal data are stored.
- **Statistics:** it reads views, likes, comment counts and average view percentage of the owner's own videos. It uses
  them to decide which kinds of videos to make next.

## 3. How data is stored
- The OAuth refresh token is kept as an **encrypted secret** in the owner's GitHub Actions settings and is never written to files or logs.
- The tool's memory (`data/` folder) contains only the owner's own video IDs, their statistics and replied comment IDs.
  It contains no personal data about viewers. Data older than 30 days is no longer refreshed.
- The tool uses no cookies, tracking or third-party analytics.

## 4. Sharing
No data is shared with, sold to, or disclosed to any third party.

## 5. Deleting data / revoking access
- Access can be revoked at any time at **https://security.google.com/settings/security/permissions** (Google Account → Security → Third-party access → "Color Race Uploader" → Remove access).
- Deleting the GitHub secret removes the stored token immediately.
- Videos uploaded by the tool can be deleted in YouTube Studio like any other video.
- Any stored authorization data is deleted within 7 days of revocation or on request.

## 6. Contact
Questions about this policy can be sent through the contact details on the Color Race YouTube channel's "About" page.
