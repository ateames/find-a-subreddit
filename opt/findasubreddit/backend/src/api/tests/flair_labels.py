#!/usr/bin/env python3
import os
import sys
import argparse
from dotenv import load_dotenv

import praw
import prawcore

def die(msg, code=1):
    sys.stderr.write(msg.strip() + "\n")
    sys.exit(code)

def load_env():
    load_dotenv()
    cfg = {
        "client_id": os.getenv("REDDIT_SCRIPT_CLIENT_ID"),
        "client_secret": os.getenv("REDDIT_SCRIPT_CLIENT_SECRET"),
        "username": os.getenv("REDDIT_USERNAME"),
        "password": os.getenv("REDDIT_PASSWORD"),
        "user_agent": os.getenv("REDDIT_USER_AGENT") or "sub_finder_ai/0.1 by SchmeedsMcSchmeeds",
    }
    missing = [k for k, v in cfg.items() if k in ("client_id","client_secret","username","password") and not v]
    if missing:
        die(f"Missing required env var(s): {', '.join(missing)}")
    return cfg

def make_reddit(cfg):
    return praw.Reddit(
        client_id=cfg["client_id"],
        client_secret=cfg["client_secret"],
        username=cfg["username"],
        password=cfg["password"],
        user_agent=cfg["user_agent"],
    )

def fetch_link_flair_labels(reddit, subreddit_name):
    # PRAW exposes user-selectable link flair templates here:
    # reddit.subreddit(name).flair.link_templates.user_selectable()
    # Each item is a dict; the visible label is under "text".
    labels = []
    for tpl in reddit.subreddit(subreddit_name).flair.link_templates.user_selectable():
        label = tpl.get("text") or tpl.get("flair_text")  # be tolerant of variations
        if label:
            labels.append(label.strip())
    # Deduplicate while preserving order
    seen = set()
    out = []
    for l in labels:
        if l not in seen:
            seen.add(l)
            out.append(l)
    return out

def main():
    parser = argparse.ArgumentParser(description="Print link flair labels for a subreddit")
    parser.add_argument("subreddit", help="subreddit name, e.g. askreddit")
    args = parser.parse_args()

    cfg = load_env()
    reddit = make_reddit(cfg)

    try:
        # Touch the API once to ensure the token is valid (optional)
        _ = reddit.user.me()

        labels = fetch_link_flair_labels(reddit, args.subreddit)
        # Print JUST the labels, one per line
        for l in labels:
            print(l)
        # If nothing printed, still exit 0—some subs simply have no user-selectable post flairs.
    except prawcore.exceptions.Forbidden:
        die("403 Forbidden: this subreddit may restrict flair visibility to certain users/mods.")
    except prawcore.exceptions.InsufficientScope as e:
        die(f"Insufficient scope: {e}")
    except prawcore.exceptions.ResponseException as e:
        die(f"API error: {e}")
    except Exception as e:
        die(f"Unexpected error: {e}")

if __name__ == "__main__":
    main()
