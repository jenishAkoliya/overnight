"""One-time Google OAuth consent -> writes GOOGLE_REFRESH_TOKEN to .env (never printed).
Scopes: gmail.modify, calendar, drive.readonly (least privilege for Drive). Run: .venv/bin/python scripts/google_oauth.py"""
import os
import re
from pathlib import Path
from dotenv import load_dotenv
from google_auth_oauthlib.flow import InstalledAppFlow

ENV = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(ENV)
SCOPES = ["https://www.googleapis.com/auth/gmail.modify", "https://www.googleapis.com/auth/calendar", "https://www.googleapis.com/auth/drive.readonly"]
cfg = {"installed": {"client_id": os.environ["GOOGLE_CLIENT_ID"], "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
                     "auth_uri": "https://accounts.google.com/o/oauth2/auth", "token_uri": "https://oauth2.googleapis.com/token",
                     "redirect_uris": ["http://localhost"]}}
creds = InstalledAppFlow.from_client_config(cfg, SCOPES).run_local_server(port=0, access_type="offline", prompt="consent",
        authorization_prompt_message="Opening browser for Google consent...", success_message="Overnight is connected. You can close this tab.")
assert creds.refresh_token, "no refresh token returned"
s = ENV.read_text()
s = re.sub(r"^GOOGLE_REFRESH_TOKEN=.*\n?", "", s, flags=re.M).rstrip("\n") + f"\nGOOGLE_REFRESH_TOKEN={creds.refresh_token}\n"
ENV.write_text(s)
print("refresh token saved to .env")
