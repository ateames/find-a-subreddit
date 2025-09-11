#!/usr/bin/env python3
import os
import sys
import json
from urllib.parse import urlparse, parse_qs

import praw
from dotenv import load_dotenv, find_dotenv

# Load .env from project root (searches upward)
load_dotenv(find_dotenv())

CLIENT_ID = os.getenv("REDDIT_CLIENT_ID")
CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET")
USER_AGENT = os.getenv("REDDIT_USER_AGENT", "ai-reddit-prototype/0.1 by u/yourname")

# Use your existing env if set; otherwise fallback to a common localhost URI.
# NOTE: This *must* be added to your Reddit app's redirect URIs exactly.
REDIRECT_URI = os.getenv("REDDIT_REDIRECT_URI", "http://127.0.0.1:65010/authorize_callback")

SCOPES = ["identity", "read", "submit"]

def die(msg: str):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)

def check_creds():
    missing = []
    if not CLIENT_ID:
        missing.append("REDDIT_CLIENT_ID")
    if CLIENT_SECRET is None:
        # Installed apps have no secret; for web apps it is required.
        # We'll still allow empty, but warn loudly if it's empty.
        pass
    if not USER_AGENT:
        missing.append("REDDIT_USER_AGENT")
    if not REDIRECT_URI:
        missing.append("REDDIT_REDIRECT_URI")
    if missing:
        die(
            "Missing required env vars: "
            + ", ".join(missing)
            + "\nMake sure your project root .env has entries like:\n"
            "  REDDIT_CLIENT_ID=...\n"
            "  REDDIT_CLIENT_SECRET=...   # empty only if Installed App\n"
            "  REDDIT_USER_AGENT=yourapp/0.1 by u/you\n"
            "  REDDIT_REDIRECT_URI=http://127.0.0.1:65010/authorize_callback\n"
            "\nAlso ensure the exact REDDIT_REDIRECT_URI is whitelisted in your Reddit app settings."
        )

def main():
    check_creds()

    print("[info] Using:", file=sys.stderr)
    print(f"  CLIENT_ID={CLIENT_ID}", file=sys.stderr)
    print(f"  CLIENT_SECRET={'<set>' if CLIENT_SECRET else '<empty>'}", file=sys.stderr)
    print(f"  USER_AGENT={USER_AGENT}", file=sys.stderr)
    print(f"  REDIRECT_URI={REDIRECT_URI}", file=sys.stderr)

    reddit = praw.Reddit(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        redirect_uri=REDIRECT_URI,
        user_agent=USER_AGENT,
    )

    auth_url = reddit.auth.url(SCOPES, state="state", duration="permanent")
    print("\n1) Open this URL in your browser, authorize the app, and allow the redirect:\n")
    print(auth_url)
    print("\n2) Paste the FULL redirected URL here and press Enter:")
    redirected = input().strip()
    if not redirected:
        die("No URL provided.")

    try:
        code = parse_qs(urlparse(redirected).query)["code"][0]
    except Exception:
        die("Could not extract 'code' from the URL. Did you paste the full redirected URL?")

    try:
        refresh_token = reddit.auth.authorize(code)
    except Exception as e:
        die(f"Authorization failed: {e}")

    print("\nSUCCESS! Save this refresh token in your .env as REDDIT_REFRESH_TOKEN:\n")
    print(refresh_token)

    # Optional: quick sanity check
    try:
        me = reddit.user.me()
        print(f"\nSanity check: authenticated as u/{me.name}")
    except Exception as _:
        print("\n(Warning) Could not confirm user; token may still be valid.", file=sys.stderr)

if __name__ == "__main__":
    main()
