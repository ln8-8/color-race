# Color Race — automatic daily YouTube channel

Every day, with no work from you, the agent makes and schedules:

| What | Format | Length | Default publish time (UTC) |
|---|---|---|---|
| 5 × Short (2 in 3D, 3 in 2D) | vertical 1080×1920 | ~40–50 s | 08:00, 11:00, 14:00, 17:00, 20:00 |

The 2 daily 3D Shorts use different cameras: the 1st uses the **behind-the-runner** chase camera (like an endless-runner game), and the 2nd uses the **cinematic** camera (front, side, drone and chase views). To try one: `python render.py --camera behind|cinematic`.
| 1 × long video, the **Color Race Tournament** | horizontal 1920×1080 | ~2:40 | 16:00 |

**Every race:** "PICK YOUR COLOR!", a countdown, then hazards (meteor, lightning, landmine, trapdoor, boulder) eliminate racers, with slow-motion kill-cams, close calls and boosts, until one winner is left.

**Variety:**
- **Character:** one type per day, rotating through Jelly Blobs → People → Ducks → Tiny Cars → Marbles.
- **Place:** each video is in a different place: Stadium, Desert, Snow, City (night), Forest, Volcano.
- **Lighting:** day, sunset or night.
- **Each race is new:** the colors, events, camera cuts and winner are different every time.

**Tournament:** 12 colors race in 3 heats of 4, each heat in a different place. The heat winners plus 1 lucky loser race in the FINAL, and one becomes CHAMPION. The upload includes YouTube chapters and a custom thumbnail.

## Files
| File | Purpose |
|---|---|
| `daily.py` | **The agent**: renders today's 5 Shorts and the tournament, writes titles, descriptions and chapters, uploads and schedules |
| `render.py` + `web/` | 3D renderer: Python plans the race, three.js in headless Chromium draws it (`web/race.js`, `web/chars.js`) |
| `render2d.py` + `chars2d.py`, `jelly2d.py`, `toon2d.py` | 2D renderer and the 2D characters |
| `tournament.py` | The daily long video |
| `upload.py` | YouTube upload and thumbnail |
| `get_token.py` | Run once on your PC to get your YouTube login token |
| `.github/workflows/daily.yml` | Runs the agent every day on GitHub (free) |

## Setup (one time, about 1 hour)

### 1. YouTube channel
Create the channel and add a name, logo and banner. Then **verify it with your phone** at https://www.youtube.com/verify. Verification is needed for custom thumbnails and longer videos.

### 2. Google Cloud (YouTube API access)
1. Go to https://console.cloud.google.com and create a **New Project**.
2. Open **APIs & Services → Library → "YouTube Data API v3" → Enable**.
3. Open the **OAuth consent screen**:
   - Choose External, enter an app name and your email.
   - Add the scope `.../auth/youtube.upload`.
   - Add the scope `.../auth/youtube.force-ssl`. Thumbnails need it.
   - Click **Publish app** so it says *In production*. If you leave it in Testing mode, the login stops working after 7 days.
4. Go to **Credentials → Create credentials → OAuth client ID → Desktop app**. Download the JSON and rename it `client_secret.json`.

### 3. Get your token (on your own computer)
```
pip install google-auth-oauthlib
python get_token.py
```
A browser opens. Log in with the channel's Google account. When it says "unverified app", click Advanced → Continue. The script prints 3 values: `YT_CLIENT_ID`, `YT_CLIENT_SECRET` and `YT_REFRESH_TOKEN`.

### 4. Ask YouTube to unlock public uploads (and more quota)
Until YouTube audits your API project, uploads from new API projects stay **private**. Fill in this form:
https://support.google.com/youtube/contact/yt_api_form

- Describe it as: "Personal tool that uploads my own original animated videos to my own channel."
- **Also ask for 20,000 units/day of quota.** 6 uploads a day use about 9,650 of the default 10,000, which leaves no room for a retry.

Approval takes days to weeks. Until then the videos still upload, but as private.

### 5. Put it on GitHub
1. Create a repository and upload this folder.
   - A **public** repo gets unlimited free Action minutes.
   - A **private** repo gets 2,000 free minutes a month, and this needs about 1,600.
2. Go to **Settings → Secrets and variables → Actions → Secrets** and add the 3 values from step 3.
3. Go to **Actions → daily-shorts → Run workflow** to test it. A run takes about 50–60 minutes.
4. Check YouTube Studio → Content: you should see 6 scheduled videos.

From then on it runs **every day at 04:17 UTC** by itself.

### Optional settings (Settings → Secrets and variables → Actions → **Variables**)
| Variable | Default | Meaning |
|---|---|---|
| `SHORT_TIMES_UTC` | `08:00,11:00,14:00,17:00,20:00` | one Short per time |
| `LONG_TIME_UTC` | `16:00` | the tournament time (`off` = no long video) |
| `STYLES` | `3d,2d,2d,3d,2d` | 3D/2D mix of the Shorts |

## Try locally
```
pip install -r requirements.txt                       # plus ffmpeg and Node.js 18+
cd web && npm install && npx playwright install chromium && cd ..
python render2d.py --seed 1 --character duck --world snow          # 2D Short, ~30 s
python render.py --seed 1 --character car --world city --preview   # 3D quick check, ~2 min
python tournament.py --seed 1 --character marble                   # long video, ~3 min
UPLOAD=0 python daily.py                                           # the full day, no upload
```

## Notes
- GitHub pauses scheduled workflows in repos with no commits for 60 days. Make any small commit to re-enable it.
- YouTube can refuse to monetize channels whose videos look mass-produced. The rotation of characters, places, 3D/2D and the tournament helps. Adding new characters or places over time helps more.
- To add a character: one class in `chars2d.py` (2D) and one builder in `web/chars.js` (3D).
