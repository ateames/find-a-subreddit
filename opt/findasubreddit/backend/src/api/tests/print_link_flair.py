#!/usr/bin/env python3
import argparse
import json
import os
import sys
from typing import Any, Dict, List

from dotenv import load_dotenv
import praw

# Load .env next to your project root
# Adjust path if your .env is elsewhere
load_dotenv()

# Primary app creds
REDDIT_CLIENT_ID = os.getenv("REDDIT_CLIENT_ID")
REDDIT_CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET")
REDDIT_USER_AGENT = os.getenv("REDDIT_USER_AGENT", "ai-reddit-prototype/0.1")

# Optional: script creds (can be same as above)
REDDIT_SCRIPT_CLIENT_ID = os.getenv("REDDIT_SCRIPT_CLIENT_ID", REDDIT_CLIENT_ID)
REDDIT_SCRIPT_CLIENT_SECRET = os.getenv("REDDIT_SCRIPT_CLIENT_SECRET", REDDIT_CLIENT_SECRET)
REDDIT_USERNAME = os.getenv("REDDIT_USERNAME")
REDDIT_PASSWORD = os.getenv("REDDIT_PASSWORD")

# Optional: an OAuth refresh token (if you saved one)
REDDIT_REFRESH_TOKEN = os.getenv("REDDIT_REFRESH_TOKEN")

def build_reddit():
    """
    Build a PRAW client. Preference:
    1) refresh token
    2) script (username/password)
    3) read-only app
    """
    if REDDIT_REFRESH_TOKEN:
        print("[auth] Using refresh_token", file=sys.stderr)
        return praw.Reddit(
            client_id=REDDIT_CLIENT_ID,
            client_secret=REDDIT_CLIENT_SECRET,
            refresh_token=REDDIT_REFRESH_TOKEN,
            user_agent=REDDIT_USER_AGENT,
        )

    if REDDIT_USERNAME and REDDIT_PASSWORD and REDDIT_SCRIPT_CLIENT_ID and REDDIT_SCRIPT_CLIENT_SECRET:
        print("[auth] Using script (password) grant", file=sys.stderr)
        return praw.Reddit(
            client_id=REDDIT_SCRIPT_CLIENT_ID,
            client_secret=REDDIT_SCRIPT_CLIENT_SECRET,
            username=REDDIT_USERNAME,
            password=REDDIT_PASSWORD,
            user_agent=REDDIT_USER_AGENT,
        )

    print("[auth] Using read-only app (limited)", file=sys.stderr)
    r = praw.Reddit(
        client_id=REDDIT_CLIENT_ID,
        client_secret=REDDIT_CLIENT_SECRET,
        user_agent=REDDIT_USER_AGENT,
    )
    r.read_only = True
    return r

def flair_label_from_template(t: Dict[str, Any]) -> str:
    """Human-ish label from subreddit template dict."""
    text = (t.get("text") or "").strip()
    if text:
        return text
    # Build from richtext parts if present
    parts = []
    for r in (t.get("richtext") or []):
        if r.get("e") == "text":
            parts.append(r.get("t") or "")
        elif r.get("e") == "emoji":
            parts.append(r.get("a") or "🔹")
    label = "".join(parts).strip()
    if label:
        return label
    css_class = (t.get("css_class") or "").strip()
    if css_class:
        return f"[{css_class}]"
    tid = (t.get("id") or t.get("flair_template_id") or "")
    return f"Template {tid[:8]}" if tid else "Template"

def print_user_selectable(reddit, sub_name: str, include_all: bool = False):
    sub = reddit.subreddit(sub_name)
    # Force a quick check to surface 403/404 early
    _ = sub.id

    if include_all:
        # All link templates (then filter by user_selectable)
        templates = list(sub.flair.link_templates)
        user_templates = [t for t in templates if t.get("user_selectable")]
    else:
        # Only user-selectable (recommended)
        user_templates = list(sub.flair.link_templates.user_selectable())

    out = []
    for t in user_templates:
        tid = t.get("id") or t.get("flair_template_id")
        item = {
            "label": flair_label_from_template(t),
            "id": tid,
            "text": t.get("text") or "",
            "editable": bool(t.get("editable", t.get("allow_user_edit", False))),
            "text_color": t.get("text_color", ""),
            "background_color": t.get("background_color", ""),
            "css_class": t.get("css_class", ""),
            "richtext": t.get("richtext") or [],
            "raw": t,  # keep raw in case you want to inspect fields
        }
        out.append(item)

    print(json.dumps(out, indent=2, ensure_ascii=False))

def print_submission_choices(reddit, submission_id: str):
    subm = reddit.submission(id=submission_id)
    # choices() returns list of dicts with flair_template_id, flair_text, flair_text_editable, etc.
    choices: List[Dict[str, Any]] = subm.flair.choices()
    out = []
    for c in choices:
        item = {
            "label": (c.get("flair_text") or "").strip() or f"Template {str(c.get('flair_template_id') or '')[:8]}",
            "flair_template_id": c.get("flair_template_id"),
            "flair_text": c.get("flair_text"),
            "flair_text_editable": c.get("flair_text_editable"),
            "raw": c,
        }
        out.append(item)
    print(json.dumps(out, indent=2, ensure_ascii=False))

def main():
    parser = argparse.ArgumentParser(description="Print subreddit link flair templates or submission flair choices.")
    parser.add_argument("--sub", help="Subreddit name (no r/)", default="test")
    parser.add_argument("--mode", choices=["subreddit", "submission"], default="subreddit",
                        help="subreddit=user_selectable link templates; submission=flair.choices()")
    parser.add_argument("--submission-id", help="Required for --mode submission", default=None)
    parser.add_argument("--include-all", action="store_true",
                        help="(subreddit mode) show all link templates then filter by user_selectable")
    args = parser.parse_args()

    try:
        reddit = build_reddit()
        # Print who we are (helps verify auth mode)
        try:
            me = reddit.user.me()
            if me:
                print(f"[auth] Logged in as: u/{me.name}", file=sys.stderr)
            else:
                print("[auth] Read-only (no user)", file=sys.stderr)
        except Exception as _:
            print("[auth] Could not determine user (likely read-only)", file=sys.stderr)

        if args.mode == "subreddit":
            print_user_selectable(reddit, args.sub.strip().replace("r/", ""), include_all=args.include_all)
        else:
            if not args.submission_id:
                print("ERROR: --submission-id is required for --mode submission", file=sys.stderr)
                sys.exit(2)
            print_submission_choices(reddit, args.submission_id)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
