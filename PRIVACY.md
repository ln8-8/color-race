# Privacy Policy — Color Race Uploader

_Last updated: November 24, 2026_

**Color Race Uploader uses YouTube API Services.**
By using it you also agree to the [YouTube Terms of Service](https://www.youtube.com/t/terms).
Google's privacy practices are described in the [Google Privacy Policy](http://www.google.com/policies/privacy).

## 1. What the app is
Color Race Uploader is a private automation tool. It generates original animated race videos with its own code and
uploads them to the owner's own YouTube channel through the YouTube Data API v3. It has no other users.

## 2. What data it accesses (YouTube API Services)
- It uses OAuth 2.0 to sign in **only with the channel owner's own Google account**.
- Scopes used: `youtube.upload` (to upload videos) and `youtube.force-ssl` (to set a video thumbnail).
- API methods used: `videos.insert` and `thumbnails.set`. **Nothing else.**
- It does **not** read, collect or analyse any YouTube data: no comments, viewers, subscribers or analytics, and no data about other users.

## 3. How data is stored
- The only stored item is the OAuth refresh token. It is kept as an **encrypted secret** in the owner's GitHub Actions settings and is never written to files or logs.
- The app uses no database, cookies or tracking, and no analytics.

## 4. Sharing
No data is shared with, sold to, or disclosed to any third party.

## 5. Deleting data / revoking access
- Access can be revoked at any time at **https://security.google.com/settings/security/permissions** (Google Account → Security → Third-party access → "Color Race Uploader" → Remove access).
- Deleting the GitHub secret removes the stored token immediately.
- Videos uploaded by the tool can be deleted in YouTube Studio like any other video.
- Any stored authorization data is deleted within 7 days of revocation or on request.

## 6. Contact
Questions about this policy can be sent through the contact details on the Color Race YouTube channel's "About" page.
