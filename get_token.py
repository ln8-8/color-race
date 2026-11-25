"""Run ONCE on your own computer to get a YouTube refresh token.

1. Put the OAuth client file you downloaded from Google Cloud next to this script as client_secret.json
2. pip install google-auth-oauthlib
3. python get_token.py  -> a browser opens, log in with the account that owns the channel
4. Copy the printed values into your GitHub repo secrets.
"""
from google_auth_oauthlib.flow import InstalledAppFlow

flow = InstalledAppFlow.from_client_secrets_file(
    "client_secret.json", ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.force-ssl",
     "https://www.googleapis.com/auth/yt-analytics.readonly"]
)
creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
print("\nYT_CLIENT_ID     =", creds.client_id)
print("YT_CLIENT_SECRET =", creds.client_secret)
print("YT_REFRESH_TOKEN =", creds.refresh_token)
