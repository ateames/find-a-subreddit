#!/usr/bin/env python3
"""
scripts/test_top_sub_summaries.py

Fetch TOP_N popular (SFW) subreddits and print one ≤15-word vibe summary per line.
Default output is *just the text* (summary only). Use --with-name to include subreddit names.

Env required (read-only):
  REDDIT_SCRIPT_CLIENT_ID
  REDDIT_SCRIPT_CLIENT_SECRET
  REDDIT_USER_AGENT   (e.g., "ai-subreddit-finder-test/0.1 by yourname")

Optional (to call OpenAI):
  OPENAI_API_KEY
  SUMMARY_MODEL  (defaults to "gpt-4o-mini")

Optional (to call post_requirements):
  REDDIT_USERNAME
  REDDIT_PASSWORD
"""

import os, re, json, sys, time, argparse
from typing import Dict, Any, Tuple

# .env from repo root (or nearest parent)
try:
    from dotenv import load_dotenv, find_dotenv
    load_dotenv(find_dotenv(usecwd=True))
except Exception:
    pass

# OpenAI (>=1.0)
from openai import OpenAI

# PRAW
import praw
from prawcore.exceptions import PrawcoreException


# ---------------- Logging ----------------
def eprint(msg: str):
    print(msg, file=sys.stderr)


# ---------------- Helpers ----------------
_LEADIN_PATTERN = r'^\s*(?:this\s+(?:community|subreddit)|welcome\s+to|a\s+community|the\s+community)\s*[:,\-–—]*\s*'

def _clean_summary_style(s: str) -> str:
    s = s.strip().strip('"\'`')
    s = re.sub(_LEADIN_PATTERN, '', s, flags=re.I).strip()
    s = re.sub(r'\s+', ' ', s)
    return s

def ensure_15_words_or_less(sentence: str) -> str:
    s = (sentence or "").strip().replace("\n", " ").strip(" \"'`")
    s = _clean_summary_style(s)
    words = re.findall(r"\b[\w'-]+\b", s)
    if len(words) > 15:
        s = " ".join(words[:15])
    s = s.rstrip(".!?") + "."
    return s

def local_fallback_summary(name: str, public_desc: str, submit_text: str) -> str:
    base = (public_desc or submit_text or f"{name} discussions and Q&A").strip()
    base = _clean_summary_style(base)
    base = re.sub(r"(?i)\br/\s*", "", base)
    words = re.findall(r"\b[\w'-]+\b", base)
    return ensure_15_words_or_less(" ".join(words[:15] if words else ["General", "discussion", "and", "Q&A"]))

def generate_llm_summary_and_restrictions(
    openai_client: OpenAI,
    model: str,
    name: str,
    public_desc: str,
    rules_joined: str,
    content_type: str,
    vibe_scores: Dict[str, int],
    debug: bool = False,
) -> Tuple[str, Dict[str, Any]]:
    rules_snip = (rules_joined[:2000] + "...") if len(rules_joined) > 2000 else rules_joined

    system_msg = (
        "You summarize subreddit vibes for first-time posters and extract hard posting restrictions.\n"
        "STYLE for summary:\n"
        "• ≤15 words. • Start with a plain noun phrase (no subject like 'This community').\n"
        "• Neutral, useful, concrete. • No emojis. • Avoid fluff.\n\n"
        "RESTRICTIONS extraction:\n"
        "• Read rules/description and infer only if explicitly stated. Do NOT guess.\n"
        "• Capture: min_account_age_days, min_combined_karma, min_comment_karma, min_post_karma,\n"
        "  require_verified_email, require_approved_submitter, require_user_flair_to_post.\n"
        "• Use integers for numbers, booleans for flags, and null if not specified.\n"
        "OUTPUT strictly as a single JSON object with keys 'summary' and 'restrictions'."
    )

    user_msg = (
        f"Subreddit: r/{name}\n"
        f"Content-type hint: {content_type}\n"
        f"Signals (0–5): strictness {vibe_scores.get('strictness', 0)}, "
        f"beginner {vibe_scores.get('beginner', 0)}, meme_tolerance {vibe_scores.get('meme_tolerance', 0)}, "
        f"self_promo {vibe_scores.get('self_promo', 0)}, seriousness {vibe_scores.get('seriousness', 0)}.\n\n"
        f"Public description:\n{public_desc or ''}\n\n"
        f"Rules + requirements + submit guidance:\n{rules_snip or ''}\n\n"
        "Return JSON only."
    )

    # Try JSON-mode first; fall back gracefully
    try:
        resp = openai_client.chat.completions.create(
            model=model,
            temperature=0.2,
            max_tokens=250,
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content": system_msg}, {"role": "user", "content": user_msg}],
        )
        raw = resp.choices[0].message.content.strip()
        data = json.loads(raw)
    except Exception as e:
        if debug: eprint(f"[LLM] JSON-mode failed for r/{name}: {e!r}. Falling back.")
        resp = openai_client.chat.completions.create(
            model=model, temperature=0.2, max_tokens=250,
            messages=[{"role": "system", "content": system_msg}, {"role": "user", "content": user_msg}],
        )
        raw = resp.choices[0].message.content.strip()
        m = re.search(r'\{.*\}\s*$', raw, re.DOTALL)
        data = json.loads(m.group(0) if m else raw)

    summary = ensure_15_words_or_less(str(data.get("summary", "")))
    return summary, (data.get("restrictions") or {})

def build_content_type_hint(sr) -> str:
    try:
        allows_media = bool(getattr(sr, "allow_images", False) or getattr(sr, "allow_videos", False))
        return "mixed" if allows_media else "text-only"
    except Exception:
        return "text-only"

def fetch_rules_text(sr, debug: bool = False) -> str:
    lines = []
    try:
        for r in sr.rules:  # iterator (no parentheses)
            short = getattr(r, "short_name", "") or getattr(r, "violation_reason", "") or ""
            desc = getattr(r, "description", "") or ""
            kind = getattr(r, "kind", "") or ""  # "all", "comment", or "post"
            line = " ".join(p for p in [f"[{kind}]" if kind else "", (short + ":").strip(), desc] if p).strip()
            if line: lines.append(line)
    except Exception as e:
        if debug: eprint(f"[RULES] r/{getattr(sr,'display_name','?')}: {e!r}")
    return "\n".join(lines)

def fetch_post_requirements_text(sr, allow: bool, debug: bool = False) -> str:
    """Call only if logged-in username/password were provided; else skip cleanly."""
    if not allow:
        return ""
    try:
        req = sr.post_requirements()  # dict (requires user context)
    except Exception as e:
        if debug: eprint(f"[POST REQ] r/{getattr(sr,'display_name','?')}: {e!r}")
        return ""
    if not isinstance(req, dict):
        return ""

    lines = []
    def add_bool(k, label):
        v = req.get(k)
        if isinstance(v, bool) and v: lines.append(label)
    def add_range(lo_key, hi_key, label):
        lo, hi = req.get(lo_key), req.get(hi_key)
        lo_ok, hi_ok = isinstance(lo, int), isinstance(hi, int)
        if lo_ok or hi_ok:
            lines.append(f"{label}: {lo}–{hi}" if (lo_ok and hi_ok)
                        else (f"{label} ≥ {lo}" if lo_ok else f"{label} ≤ {hi}"))

    add_bool("is_flair_required", "User flair required to post")
    add_bool("is_text_required", "Post body required")
    add_bool("is_domain_whitelisted", "Links must be from approved domains")
    add_range("title_text_min_length", "title_text_max_length", "Title length")
    add_range("body_text_min_length", "body_text_max_length", "Body length")

    return "\n".join(lines) if lines else json.dumps(req, ensure_ascii=False)

def fetch_submit_text(sr, debug: bool = False) -> str:
    try:
        return getattr(sr, "submit_text", "") or ""
    except Exception as e:
        if debug: eprint(f"[SUBMIT TEXT] r/{getattr(sr,'display_name','?')}: {e!r}")
        return ""


# ---------------- Main ----------------
def main():
    ap = argparse.ArgumentParser(description="Print ≤15-word summaries for top subreddits.")
    ap.add_argument("--top-n", type=int, default=10, help="How many popular subreddits to summarize (default: 10)")
    ap.add_argument("--with-name", action="store_true", help="Include subreddit name before the summary")
    ap.add_argument("--names-only", action="store_true", help="Print only subreddit names (skip OpenAI)")
    ap.add_argument("--delay", type=float, default=0.6, help="Sleep seconds between calls to be polite")
    ap.add_argument("--model", type=str, default=os.getenv("SUMMARY_MODEL", "gpt-4o-mini"),
                    help="OpenAI model (default from SUMMARY_MODEL env or gpt-4o-mini)")
    ap.add_argument("--debug", action="store_true", help="Log progress/errors to stderr")
    args = ap.parse_args()

    if args.debug:
        eprint(f"[INIT] top_n={args.top_n} with_name={args.with_name} names_only={args.names_only} model={args.model}")

    # Reddit auth (read-only app credentials are required)
    cid  = os.getenv("REDDIT_SCRIPT_CLIENT_ID") or os.getenv("REDDIT_CLIENT_ID")
    csec = os.getenv("REDDIT_SCRIPT_CLIENT_SECRET") or os.getenv("REDDIT_CLIENT_SECRET")
    ua   = os.getenv("REDDIT_USER_AGENT") or "ai-subreddit-finder-test/0.1 by yourname"
    if not (cid and csec and ua):
        raise RuntimeError("Missing Reddit env: REDDIT_SCRIPT_CLIENT_ID/SECRET and REDDIT_USER_AGENT")

    username = os.getenv("REDDIT_USERNAME")
    password = os.getenv("REDDIT_PASSWORD")
    using_user = bool(username and password)

    if using_user:
        reddit = praw.Reddit(
            client_id=cid, client_secret=csec, user_agent=ua,
            username=username, password=password, check_for_async=False
        )
        if args.debug: eprint("[AUTH] Using user auth (password grant) for post_requirements")
    else:
        reddit = praw.Reddit(client_id=cid, client_secret=csec, user_agent=ua, check_for_async=False)
        reddit.read_only = True
        if args.debug: eprint("[AUTH] Using read-only app auth (skipping post_requirements)")

    # OpenAI (optional)
    openai_key = os.getenv("OPENAI_API_KEY")
    use_llm = bool(openai_key) and not args.names_only
    openai_client = OpenAI(api_key=openai_key) if use_llm else None
    if args.debug:
        eprint(f"[OPENAI] use_llm={use_llm}")

    collected = 0
    for sr in reddit.subreddits.popular(limit=max(args.top_n * 5, args.top_n)):
        try:
            if getattr(sr, "over18", False):
                if args.debug: eprint(f"[SKIP] NSFW r/{sr.display_name}")
                continue

            name = sr.display_name
            if args.debug: eprint(f"[SUB] r/{name} – fetching metadata")

            public_desc = getattr(sr, "public_description", "") or getattr(sr, "description", "") or ""
            rules_text  = fetch_rules_text(sr, debug=args.debug)
            post_req    = fetch_post_requirements_text(sr, allow=using_user, debug=args.debug)
            submit_text = fetch_submit_text(sr, debug=args.debug)
            content_type = build_content_type_hint(sr)

            combined_rules = rules_text
            if post_req:    combined_rules += ("\n\nPost requirements:\n" + post_req)
            if submit_text: combined_rules += ("\n\nSubmit text:\n" + submit_text)

            if args.names_only:
                out = f"r/{name}" if args.with_name else name
                print(out)
            else:
                # Seed vibes (static hints)
                vibes = {"strictness": 3, "beginner": 3, "meme_tolerance": 2, "self_promo": 1, "seriousness": 3}

                if use_llm:
                    try:
                        summary, _restr = generate_llm_summary_and_restrictions(
                            openai_client=openai_client, model=args.model, name=name,
                            public_desc=public_desc, rules_joined=combined_rules,
                            content_type=content_type, vibe_scores=vibes, debug=args.debug,
                        )
                    except Exception as e:
                        if args.debug: eprint(f"[FALLBACK] LLM failed for r/{name}: {e!r}")
                        summary = local_fallback_summary(name, public_desc, submit_text)
                else:
                    summary = local_fallback_summary(name, public_desc, submit_text)

                print(f"r/{name}: {summary}" if args.with_name else summary)

            collected += 1
            if collected >= args.top_n:
                break
            time.sleep(args.delay)

        except KeyboardInterrupt:
            break
        except Exception as e:
            if args.debug: eprint(f"[ERROR] Skipping r/{getattr(sr,'display_name','?')}: {e!r}")
            continue

    if args.debug:
        eprint(f"[DONE] Printed {collected} lines")


if __name__ == "__main__":
    main()
