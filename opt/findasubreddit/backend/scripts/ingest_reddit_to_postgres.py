# scripts/ingest_reddit_to_postgres.py
"""
Creates Postgres (pgvector) tables, fetches subreddit data with PRAW (popular-only, NSFW excluded),
computes heuristic "vibe", generates a <=15-word LLM summary, embeds with OpenAI, and upserts into Postgres.
"""

import os, time, hashlib, re, json
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Set, Tuple

# --- .env from repo root (or nearest parent) ---
from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv(usecwd=True))

import psycopg
from psycopg.rows import dict_row

import praw
from prawcore.exceptions import Forbidden, NotFound, PrawcoreException

# Optional: token-aware clipping if tiktoken is installed
_TIKTOKEN_ENCODER = None
try:
    import tiktoken  # type: ignore
    _TIKTOKEN_ENCODER = tiktoken.get_encoding("cl100k_base")
except Exception:
    _TIKTOKEN_ENCODER = None

# OpenAI >= 1.0 (D: retries & timeout)
from openai import OpenAI
openai_client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    timeout=30.0,
    max_retries=5,
)

# -------- Config --------
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("Missing DATABASE_URL")

# Allow fallback to non-script creds if present
REDDIT_CLIENT_ID = os.getenv("REDDIT_SCRIPT_CLIENT_ID") or os.getenv("REDDIT_CLIENT_ID")
REDDIT_CLIENT_SECRET = os.getenv("REDDIT_SCRIPT_CLIENT_SECRET") or os.getenv("REDDIT_CLIENT_SECRET")
REDDIT_USERNAME = os.getenv("REDDIT_USERNAME")
REDDIT_PASSWORD = os.getenv("REDDIT_PASSWORD")
REDDIT_USER_AGENT = os.getenv("REDDIT_USER_AGENT", "sub_finder_ai/0.1 by SchmeedsMcSchmeeds")

TOP_N = int(os.getenv("TOP_N", "10"))
EMBED_MODEL = os.getenv("EMBED_MODEL", "text-embedding-3-small")  # 1536 dims
EMBED_DIM = int(os.getenv("EMBED_DIM", "1536"))
SUMMARY_MODEL = os.getenv("SUMMARY_MODEL", "gpt-4o-mini")

# Pre-embed clipping (keeps us under model limits)
# Char cap is conservative; token cap is applied if tiktoken is available.
EMBED_CLIP_CHARS = int(os.getenv("EMBED_CLIP_CHARS", "12000"))
EMBED_TOKEN_LIMIT = int(os.getenv("EMBED_TOKEN_LIMIT", "8000"))  # model max is 8191; keep buffer

# Known embedding model dimensions for startup validation
KNOWN_MODEL_DIMS: Dict[str, int] = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
}

# Reddit (script creds; user creds optional for post_requirements)
reddit = praw.Reddit(
    client_id=REDDIT_CLIENT_ID,
    client_secret=REDDIT_CLIENT_SECRET,
    user_agent=REDDIT_USER_AGENT,
    check_for_async=False,
)
USING_USER = False
reddit.read_only = True

# -------- SQL DDL --------
DDL = f"""
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS subreddit (
  id                 TEXT PRIMARY KEY,            -- fullname: t5_xxx
  id36               TEXT UNIQUE,                 -- base36 id
  name               TEXT UNIQUE NOT NULL,        -- display_name
  title              TEXT,
  public_description TEXT,
  description_md     TEXT,
  description_hash   TEXT,
  over18             BOOLEAN,
  quarantined        BOOLEAN,
  subreddit_type     TEXT,                        -- public/restricted/private
  submission_type    TEXT,                        -- 'self' or 'any'
  allow_images       BOOLEAN,
  allow_videos       BOOLEAN,
  allow_polls        BOOLEAN,
  suggested_comment_sort TEXT,
  subscribers        INTEGER,
  created_utc        TIMESTAMPTZ,
  last_crawled_at    TIMESTAMPTZ,
  rules_hash         TEXT
);

CREATE TABLE IF NOT EXISTS rules (
  subreddit_id TEXT REFERENCES subreddit(id) ON DELETE CASCADE,
  idx          INTEGER,
  short_name   TEXT,
  description  TEXT,
  PRIMARY KEY (subreddit_id, idx)
);

-- lightweight flair store (user-selectable link flairs only; no mod needed)
CREATE TABLE IF NOT EXISTS link_flair (
  subreddit_id TEXT REFERENCES subreddit(id) ON DELETE CASCADE,
  flair_id     TEXT,
  flair_text   TEXT,
  mod_only     BOOLEAN,
  text_editable BOOLEAN,
  PRIMARY KEY (subreddit_id, flair_id)
);

CREATE TABLE IF NOT EXISTS vibe (
  subreddit_id TEXT PRIMARY KEY REFERENCES subreddit(id) ON DELETE CASCADE,
  strictness SMALLINT,
  beginner  SMALLINT,
  meme_tolerance SMALLINT,
  self_promo SMALLINT,
  content_type TEXT,
  seriousness SMALLINT,
  summary TEXT,
  scores_source TEXT,
  prompt_version TEXT,
  model_name TEXT,
  computed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS embedding (
  subreddit_id TEXT PRIMARY KEY REFERENCES subreddit(id) ON DELETE CASCADE,
  embedding    vector({EMBED_DIM}),
  input_hash   TEXT,
  model_name   TEXT,
  updated_at   TIMESTAMPTZ
);
"""

UPSERT_SUBREDDIT = """
INSERT INTO subreddit (
  id, id36, name, title, public_description, description_md, description_hash,
  over18, quarantined, subreddit_type, submission_type,
  allow_images, allow_videos, allow_polls, suggested_comment_sort,
  subscribers, created_utc, last_crawled_at, rules_hash
) VALUES (
  %(id)s, %(id36)s, %(name)s, %(title)s, %(public_description)s, %(description_md)s, %(description_hash)s,
  %(over18)s, %(quarantined)s, %(subreddit_type)s, %(submission_type)s,
  %(allow_images)s, %(allow_videos)s, %(allow_polls)s, %(suggested_comment_sort)s,
  %(subscribers)s, %(created_utc)s, %(last_crawled_at)s, %(rules_hash)s
)
ON CONFLICT (id) DO UPDATE SET
  title=EXCLUDED.title,
  public_description=EXCLUDED.public_description,
  description_md=EXCLUDED.description_md,
  description_hash=EXCLUDED.description_hash,
  over18=EXCLUDED.over18,
  quarantined=EXCLUDED.quarantined,
  subreddit_type=EXCLUDED.subreddit_type,
  submission_type=EXCLUDED.submission_type,
  allow_images=EXCLUDED.allow_images,
  allow_videos=EXCLUDED.allow_videos,
  allow_polls=EXCLUDED.allow_polls,
  suggested_comment_sort=EXCLUDED.suggested_comment_sort,
  subscribers=EXCLUDED.subscribers,
  created_utc=EXCLUDED.created_utc,
  last_crawled_at=EXCLUDED.last_crawled_at,
  rules_hash=EXCLUDED.rules_hash;
"""

DELETE_RULES = "DELETE FROM rules WHERE subreddit_id=%s;"
INSERT_RULE = "INSERT INTO rules (subreddit_id, idx, short_name, description) VALUES (%s, %s, %s, %s);"

DELETE_LINK_FLAIR = "DELETE FROM link_flair WHERE subreddit_id=%s;"
INSERT_LINK_FLAIR = """
INSERT INTO link_flair (subreddit_id, flair_id, flair_text, mod_only, text_editable)
VALUES (%s, %s, %s, %s, %s)
ON CONFLICT (subreddit_id, flair_id) DO UPDATE SET
  flair_text=EXCLUDED.flair_text, mod_only=EXCLUDED.mod_only, text_editable=EXCLUDED.text_editable;
"""

UPSERT_EMBED = """
INSERT INTO embedding (subreddit_id, embedding, input_hash, model_name, updated_at)
VALUES (%s, %s::vector, %s, %s, %s)
ON CONFLICT (subreddit_id) DO UPDATE SET
  embedding=EXCLUDED.embedding,
  input_hash=EXCLUDED.input_hash,
  model_name=EXCLUDED.model_name,
  updated_at=EXCLUDED.updated_at;
"""

UPSERT_VIBE = """
INSERT INTO vibe (
  subreddit_id, strictness, beginner, meme_tolerance, self_promo, content_type, seriousness,
  summary, scores_source, prompt_version, model_name, computed_at
) VALUES (
  %(subreddit_id)s, %(strictness)s, %(beginner)s, %(meme_tolerance)s, %(self_promo)s, %(content_type)s, %(seriousness)s,
  %(summary)s, %(scores_source)s, %(prompt_version)s, %(model_name)s, %(computed_at)s
)
ON CONFLICT (subreddit_id) DO UPDATE SET
  strictness=EXCLUDED.strictness,
  beginner=EXCLUDED.beginner,
  meme_tolerance=EXCLUDED.meme_tolerance,
  self_promo=EXCLUDED.self_promo,
  content_type=EXCLUDED.content_type,
  seriousness=EXCLUDED.seriousness,
  summary=EXCLUDED.summary,
  scores_source=EXCLUDED.scores_source,
  prompt_version=EXCLUDED.prompt_version,
  model_name=EXCLUDED.model_name,
  computed_at=EXCLUDED.computed_at;
"""

# -------- Helpers --------

def iter_popular_sfw_subreddits(reddit_client: praw.Reddit, limit: Optional[int] = None):
    """
    Yield subreddits from r/popular, skipping NSFW communities.
    If limit is None, stream until source exhausts. Stops when TOP_N stored.
    """
    for sub in reddit_client.subreddits.popular(limit=limit):
        try:
            if getattr(sub, "over18", False):
                continue
            yield sub
        except Exception:
            continue

def clamp(x: float, lo: int = 0, hi: int = 5) -> int:
    return max(lo, min(hi, int(round(x))))

WORD_RX = re.compile(r"[A-Za-z']+")

def count_keywords(text: str, weights: Dict[str, float]) -> float:
    """Case-insensitive weighted count for whole words."""
    if not text:
        return 0.0
    words = WORD_RX.findall(text.lower())
    tally = 0.0
    for w, wt in weights.items():
        tally += wt * sum(1 for token in words if token == w.lower())
    return tally

def sha256_str(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def vec_to_pg(vec: List[float]) -> str:
    # pgvector expects: '[v1, v2, ...]'
    return "[" + ",".join(f"{x:.8f}" for x in vec) + "]"

def get_embedding(text: str) -> List[float]:
    resp = openai_client.embeddings.create(
        model=EMBED_MODEL,
        input=text,
    )
    return resp.data[0].embedding

def safe_user_link_flairs(sub) -> List[Dict[str, Any]]:
    """
    Fetch user-selectable link flairs (no mod perms). Be resilient to
    missing keys and ensure we always have a non-empty unique flair_id.
    """
    flairs = []
    try:
        for idx, tpl in enumerate(sub.flair.link_templates.user_selectable()):
            # PRAW may expose text as "text" (new) or "flair_text" (legacy)
            text = (tpl.get("text") or tpl.get("flair_text") or "").strip()
            flair_id = (tpl.get("id") or tpl.get("flair_template_id") or "").strip()

            if not flair_id:
                # synthesize a stable id from text+position to avoid PK collisions
                base = f"{text}|{idx}"
                flair_id = "syn_" + hashlib.sha1(base.encode("utf-8")).hexdigest()[:12]

            flairs.append({
                "id": flair_id,
                "text": text,
                "mod_only": bool(tpl.get("mod_only")),
                "text_editable": bool(tpl.get("text_editable")),
            })
    except (Forbidden, NotFound, PrawcoreException):
        pass
    return flairs

def build_composite_text(name: str, public_desc: str, submit_text: str, rules_text: str) -> str:
    return (
        f"Subreddit: {name}\n"
        f"Description: {public_desc}\n"
        f"Submit Rules: {submit_text}\n"
        f"Rules: {rules_text}"
    )

def _soft_clip_at_boundary(s: str, max_chars: int) -> str:
    """
    Clip at or below max_chars, preferring a natural boundary (paragraph/sentence/space).
    """
    if len(s) <= max_chars:
        return s
    snippet = s[:max_chars]
    # Prefer paragraph, then sentence end, then whitespace boundary
    cut = max(
        snippet.rfind("\n\n"),
        snippet.rfind("\n"),
        snippet.rfind(". "),
        snippet.rfind("! "),
        snippet.rfind("? "),
        snippet.rfind(" ")
    )
    if cut >= int(max_chars * 0.6):
        snippet = snippet[:cut]
    return snippet.rstrip()

# A: safer clipping (no suffix text added to the embedded payload)
def clip_for_embedding(text: str, max_chars: int, token_limit: int) -> str:
    """
    Enforce a conservative char cap first; if tiktoken is available,
    also enforce a hard token cap (<= token_limit).
    """
    s = (text or "").strip()
    # 1) Char cap (conservative so we rarely hit token limit)
    if max_chars and len(s) > max_chars:
        s = _soft_clip_at_boundary(s, max_chars)
    # 2) Token cap (only if tiktoken available)
    if _TIKTOKEN_ENCODER is not None and token_limit:
        toks = _TIKTOKEN_ENCODER.encode(s)
        if len(toks) > token_limit:
            s = _TIKTOKEN_ENCODER.decode(toks[:token_limit]).rstrip()
    return s

def compute_content_type(submission_type: Optional[str], allow_images: Optional[bool],
                         allow_videos: Optional[bool], allow_polls: Optional[bool],
                         flair_texts: List[str]) -> str:
    """Very light heuristic label: 'text', 'images/oc', 'links/news', or 'mixed'."""
    s = (submission_type or "").lower()
    img = bool(allow_images)
    vid = bool(allow_videos)
    pol = bool(allow_polls)
    flair_hint = " ".join(flair_texts).lower()
    if s == "self" and not (img or vid or pol):
        return "text"
    if ("photo" in flair_hint or "show & tell" in flair_hint or "build log" in flair_hint) and (img or vid):
        return "images/oc"
    if "news" in flair_hint or "discussion" in flair_hint:
        return "links/news" if s != "self" else "mixed"
    if img or vid:
        return "images/oc"
    return "mixed" if s != "self" else "text"

def compute_vibe_heuristics(rules_joined: str, desc_all: str, flair_texts: List[str]) -> Dict[str, Any]:
    text = f"{rules_joined}\n{desc_all}".lower()
    flairs = " ".join(flair_texts).lower()

    # Strictness
    strict = count_keywords(text, {
        "ban": 2, "zero": 0, "tolerance": 0,
        "must": 1, "require": 1, "removed": 2, "please": -0.5, "encouraged": -0.5
    })
    if "zero tolerance" in text:
        strict += 2
    strict = clamp(strict)

    # Beginner-friendliness
    beginner = 0
    if any(k in flairs for k in ["beginner", "help", "question"]):
        beginner += 2
    if "weekly help thread" in text or "help megathread" in text:
        beginner += 2
    if "read the faq before posting" in text or "no basic questions" in text:
        beginner -= 2
    beginner = clamp(beginner + 2)

    # Meme tolerance
    meme = 0
    if "no memes" in text or "low effort" in text:
        meme -= 3
    if "meme" in flairs or "humor" in flairs:
        meme += 2
    meme = clamp(meme + 2)

    # Self-promo
    sp = 0
    if "no self-promotion" in text or "no self promotion" in text:
        sp -= 3
    if "1:10" in text or "one in ten" in text or "on sundays" in text:
        sp += 1
    sp = clamp(sp + 2)

    # Seriousness
    serious = 0
    if "peer-reviewed" in text or "sources only" in text or "evidence-based" in text:
        serious += 3
    if "dumb questions welcome" in text or "just for fun" in text or "shitpost" in text:
        serious -= 2
    serious = clamp(serious + 2)

    return {
        "strictness": strict,
        "beginner": beginner,
        "meme_tolerance": meme,
        "self_promo": sp,
        "seriousness": serious,
    }

# --- Summary style cleaner (regex flags fixed) ---
_LEADIN_PATTERN = r'^\s*(?:this\s+(?:community|subreddit)|welcome\s+to|a\s+community|the\s+community)\s*[:,\-–—]*\s*'

def _clean_summary_style(s: str) -> str:
    # Remove lead-ins like "This community...", "This subreddit...", "Welcome to..."
    s = s.strip().strip('"\'`')
    s = re.sub(_LEADIN_PATTERN, '', s, flags=re.I).strip()
    # Collapse whitespace
    s = re.sub(r'\s+', ' ', s)
    return s

def ensure_15_words_or_less(sentence: str) -> str:
    # Strip newlines/quotes, enforce <=15 words, end with a period.
    s = (sentence or "").strip().replace("\n", " ").strip(" \"'`")
    s = _clean_summary_style(s)
    words = re.findall(r"\b[\w'-]+\b", s)
    if len(words) > 15:
        s = " ".join(words[:15])
    s = s.rstrip(".!?") + "."
    return s

# --- PRAW helpers mirroring the test script ---

def fetch_rules_text(sr) -> str:
    """Iterator-safe rules (avoid deprecated sr.rules())."""
    items = []
    try:
        for r in sr.rules:  # iterator, not sr.rules()
            short = getattr(r, "short_name", "") or getattr(r, "violation_reason", "") or ""
            desc  = getattr(r, "description", "") or ""
            kind  = getattr(r, "kind", "") or ""  # "all", "comment", "post"
            line  = " ".join(p for p in [f"[{kind}]" if kind else "", (short + ":").strip(), desc] if p).strip()
            if line:
                items.append(line)
    except Exception:
        pass
    return "\n".join(items)

def fetch_post_requirements_text(sr, allow: bool) -> str:
    """
    Only call if you have user auth (REDDIT_USERNAME/REDDIT_PASSWORD).
    Otherwise return "" and skip cleanly.
    """
    if not allow:
        return ""
    try:
        req = sr.post_requirements()  # requires user context
    except Exception:
        return ""
    if not isinstance(req, dict):
        return ""
    lines = []
    def add_bool(k, label):
        v = req.get(k)
        if isinstance(v, bool) and v:
            lines.append(label)
    def add_range(lo_key, hi_key, label):
        lo, hi = req.get(lo_key), req.get(hi_key)
        lo_ok, hi_ok = isinstance(lo, int), isinstance(hi, int)
        if lo_ok or hi_ok:
            if lo_ok and hi_ok: lines.append(f"{label}: {lo}–{hi}")
            elif lo_ok:         lines.append(f"{label} ≥ {lo}")
            else:               lines.append(f"{label} ≤ {hi}")
    add_bool("is_flair_required", "User flair required to post")
    add_bool("is_text_required", "Post body required")
    add_bool("is_domain_whitelisted", "Links must be from approved domains")
    add_range("title_text_min_length", "title_text_max_length", "Title length")
    add_range("body_text_min_length", "body_text_max_length", "Body length")
    return "\n".join(lines) if lines else json.dumps(req, ensure_ascii=False)

def fetch_submit_text(sr) -> str:
    try:
        return getattr(sr, "submit_text", "") or ""
    except Exception:
        return ""

# --- LLM summary (JSON-mode with fallback) ---

def generate_llm_summary_and_restrictions(
    name: str,
    public_desc: str,
    rules_joined: str,
    content_type: str,
    vibe_scores: Dict[str, int],
    model: str = SUMMARY_MODEL
) -> Tuple[str, Dict[str, Any]]:
    rules_snip = (rules_joined[:2000] + "...") if len(rules_joined) > 2000 else rules_joined

    system_msg = (
        "You summarize subreddit vibes for first-time posters and extract hard posting restrictions.\n"
        "STYLE for summary:\n"
        "≤15 words. Start with a plain noun phrase (no subject like 'This community').\n"
        "Neutral, useful, concrete. No emojis. Avoid fluff.\n\n"
        "RESTRICTIONS extraction:\n"
        "Read rules/description and infer only if explicitly stated. Do NOT guess.\n"
        "Capture: min_account_age_days, min_combined_karma, min_comment_karma, min_post_karma,\n"
        "require_verified_email, require_approved_submitter, require_user_flair_to_post.\n"
        "Use integers for numbers, booleans for flags, and null if not specified.\n"
        "Consider phrasing like 'no brand-new accounts', 'account must be X days old', '≥10 comment karma'.\n\n"
        "OUTPUT strictly as a single JSON object with keys 'summary' and 'restrictions'."
    )

    user_msg = (
        f"Subreddit: r/{name}\n"
        f"Content-type hint: {content_type}\n"
        f"Signals (0–5): strictness {vibe_scores.get('strictness', 0)}, "
        f"beginner {vibe_scores.get('beginner', 0)}, meme_tolerance {vibe_scores.get('meme_tolerance', 0)}, "
        f"self_promo {vibe_scores.get('self_promo', 0)}, seriousness {vibe_scores.get('seriousness', 0)}.\n\n"
        f"Public description:\n{public_desc or ''}\n\n"
        f"Rules:\n{rules_snip or ''}\n\n"
        "Return JSON only. Examples:\n"
        "{\n"
        '  "summary": "Beginner Q&A; practical help, low meme tolerance.",\n'
        '  "restrictions": {\n'
        '    "min_account_age_days": 1,\n'
        '    "min_combined_karma": null,\n'
        '    "min_comment_karma": 10,\n'
        '    "min_post_karma": null,\n'
        '    "require_verified_email": false,\n'
        '    "require_approved_submitter": false,\n'
        '    "require_user_flair_to_post": false\n'
        "  }\n"
        "}\n"
        "If nothing is stated for a field, set it to null or false (no inference)."
    )

    # Try JSON-mode first; gracefully fall back if the model doesn't support response_format
    try:
        resp = openai_client.chat.completions.create(
            model=model,
            temperature=0.2,
            max_tokens=250,
            response_format={"type": "json_object"},  # some models support this
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
        )
        raw = resp.choices[0].message.content.strip()
        data = json.loads(raw)
    except Exception:
        # Fallback: no response_format; still expect JSON in content.
        resp = openai_client.chat.completions.create(
            model=model,
            temperature=0.2,
            max_tokens=250,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
        )
        raw = resp.choices[0].message.content.strip()
        # Try to extract JSON block if the model added text
        match = re.search(r'\{.*\}\s*$', raw, re.DOTALL)
        raw_json = match.group(0) if match else raw
        try:
            data = json.loads(raw_json)
        except Exception:
            # Last-resort minimal object
            data = {"summary": raw, "restrictions": {}}

    # Normalize/validate fields
    summary = ensure_15_words_or_less(str(data.get("summary", "")))

    r = data.get("restrictions", {}) or {}
    def _to_int_or_null(v: Any) -> Optional[int]:
        try:
            if v is None: return None
            if isinstance(v, bool): return None
            return int(v)
        except Exception:
            return None

    restrictions = {
        "min_account_age_days": _to_int_or_null(r.get("min_account_age_days")),
        "min_combined_karma":  _to_int_or_null(r.get("min_combined_karma")),
        "min_comment_karma":   _to_int_or_null(r.get("min_comment_karma")),
        "min_post_karma":      _to_int_or_null(r.get("min_post_karma")),
        "require_verified_email": bool(r.get("require_verified_email", False)),
        "require_approved_submitter": bool(r.get("require_approved_submitter", False)),
        "require_user_flair_to_post": bool(r.get("require_user_flair_to_post", False)),
    }

    return summary, restrictions

# Backward-compatible wrapper: keeps your old function name/signature
def generate_llm_summary(
    name: str,
    public_desc: str,
    rules_joined: str,
    content_type: str,
    vibe_scores: Dict[str, int],
    model: str = SUMMARY_MODEL
) -> str:
    summary, _ = generate_llm_summary_and_restrictions(
        name, public_desc, rules_joined, content_type, vibe_scores, model
    )
    return summary

def summarize_vibe_fallback(v: Dict[str, int], content_type: str) -> str:
    # Heuristic fallback if OpenAI fails
    parts = []
    parts.append("Supportive" if v["beginner"] >= 3 else ("Neutral" if v["beginner"] == 2 else "Experienced-leaning"))
    parts.append("Q&A" if content_type == "text" else ("Image-heavy" if content_type == "images/oc" else ("News/discussion" if content_type == "links/news" else "Mixed")))
    if v["strictness"] >= 4:
        parts.append("strict on rules")
    if v["meme_tolerance"] <= 1:
        parts.append("no memes")
    out = f"{parts[0]} {parts[1]} community."
    if len(parts) > 2:
        out += " " + ", ".join(p.capitalize() if i==0 else p for i,p in enumerate(parts[2:])) + "."
    return ensure_15_words_or_less(out)

# -------- DB ops & validation --------

def create_schema(conn: psycopg.Connection):
    # Create tables / extension
    try:
        with conn.cursor() as cur:
            cur.execute(DDL)
        conn.commit()
    except Exception as e:
        raise RuntimeError("Failed to create schema or enable pgvector. "
                           "Ensure the 'vector' extension is installed and you have sufficient privileges.") from e

    # Try HNSW, fall back to IVFFlat (B: simpler IVFFlat creation)
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE INDEX IF NOT EXISTS embedding_hnsw_cosine
                ON embedding USING hnsw (embedding vector_cosine_ops);
            """)
        conn.commit()
    except Exception:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE INDEX IF NOT EXISTS embedding_ivfflat_cosine
                ON embedding USING ivfflat (embedding vector_cosine_ops);
            """)
        conn.commit()

def _get_existing_embedding_vector_type(conn: psycopg.Connection) -> Optional[str]:
    sql = """
    SELECT pg_catalog.format_type(a.atttypid, a.atttypmod) AS type
    FROM pg_attribute a
    JOIN pg_class c ON a.attrelid = c.oid
    JOIN pg_namespace n ON c.relnamespace = n.oid
    WHERE n.nspname = current_schema()
      AND c.relname = 'embedding'
      AND a.attname = 'embedding'
      AND a.attnum > 0
      AND NOT a.attisdropped;
    """
    with conn.cursor() as cur:
        cur.execute(sql)
        row = cur.fetchone()
    return row[0] if row else None

def _parse_vector_dim(type_str: str) -> Optional[int]:
    # Expect "vector(1536)" or just "vector"
    if not type_str or not type_str.startswith("vector"):
        return None
    if "(" in type_str and ")" in type_str:
        try:
            return int(type_str.split("(", 1)[1].split(")", 1)[0])
        except Exception:
            return None
    return None  # unknown

def validate_embedding_config(conn: psycopg.Connection):
    """
    Startup validator that checks:
      1) EMBED_MODEL ↔ EMBED_DIM against a known mapping
      2) Existing table's vector dimension matches EMBED_DIM (if table/column already exist)
    """
    # 1) Model ↔ dim mapping
    expected = KNOWN_MODEL_DIMS.get(EMBED_MODEL)
    if expected is not None and expected != EMBED_DIM:
        raise RuntimeError(
            f"EMBED_DIM={EMBED_DIM} does not match EMBED_MODEL={EMBED_MODEL} (expected {expected}). "
            f"Fix your environment or choose a matching model/dimension."
        )

    # 2) Existing table's vector dimension (if present)
    type_str = _get_existing_embedding_vector_type(conn)
    if type_str:
        existing_dim = _parse_vector_dim(type_str)
        if existing_dim is not None and existing_dim != EMBED_DIM:
            raise RuntimeError(
                f"Existing table 'embedding.embedding' has dimension {existing_dim}, "
                f"but EMBED_DIM={EMBED_DIM}. Migrate the table or update EMBED_DIM/EMBED_MODEL to match."
            )

def upsert_subreddit(conn: psycopg.Connection, sub, rules_list: List[Dict[str, str]], flairs: List[Dict[str, Any]]):
    now = datetime.now(timezone.utc)

    # Join rules into plain text (for hashing / storage)
    rules_joined = " | ".join([r.get("description") or "" for r in rules_list]).strip()
    rules_hash = sha256_str(rules_joined) if rules_joined else None

    # Fetch extra posting guidance (optional user auth for post_requirements)
    post_req_text = fetch_post_requirements_text(sub, allow=USING_USER)
    submit_text = fetch_submit_text(sub)

    # --- For the LLM prompt, combine rules + requirements + submit guidance (mirrors test script) ---
    combined_rules_for_llm = rules_joined
    if post_req_text:
        combined_rules_for_llm += ("\n\nPost requirements:\n" + post_req_text)
    if submit_text:
        combined_rules_for_llm += ("\n\nSubmit text:\n" + submit_text)

    # --- For embeddings, include post requirements alongside rules; submit_text is passed separately ---
    rules_for_embed = rules_joined
    if post_req_text:
        rules_for_embed += ("\n\nPost requirements:\n" + post_req_text)

    desc_md = getattr(sub, "description", None) or ""
    desc_hash = sha256_str(desc_md) if desc_md else None

    # composite for embeddings & summary (raw, un-clipped)
    composite_text = build_composite_text(
        sub.display_name,
        sub.public_description or "",
        submit_text or "",
        rules_for_embed
    )

    # Pre-embed clipping to avoid model token limits (A)
    composite_text_for_embed = clip_for_embedding(
        composite_text,
        max_chars=EMBED_CLIP_CHARS,
        token_limit=EMBED_TOKEN_LIMIT
    )
    # Hash the ACTUAL text we embed to keep "input changed?" checks consistent
    input_hash = sha256_str(composite_text_for_embed)

    # flair texts
    flair_texts = [f["text"] for f in flairs if f.get("text")]

    # content type heuristic
    content_type = compute_content_type(
        getattr(sub, "submission_type", None),
        getattr(sub, "allow_images", None),
        getattr(sub, "allow_videos", None),
        getattr(sub, "allow_polls", None),
        flair_texts
    )

    vibe_scores = compute_vibe_heuristics(rules_joined, f"{sub.public_description}\n{desc_md}", flair_texts)

    # Upsert subreddit row first
    data = {
        "id": getattr(sub, "fullname", None) or f"t5_{sub.id}",
        "id36": sub.id,
        "name": sub.display_name,
        "title": sub.title or "",
        "public_description": sub.public_description or "",
        "description_md": desc_md,
        "description_hash": desc_hash,
        "over18": bool(getattr(sub, "over18", False)),
        "quarantined": bool(getattr(sub, "quarantine", False)) or bool(getattr(sub, "quarantined", False)),
        "subreddit_type": getattr(sub, "subreddit_type", None),
        "submission_type": getattr(sub, "submission_type", None),
        "allow_images": getattr(sub, "allow_images", None),
        "allow_videos": getattr(sub, "allow_videos", None),
        "allow_polls": getattr(sub, "allow_polls", None),
        "suggested_comment_sort": getattr(sub, "suggested_comment_sort", None),
        "subscribers": getattr(sub, "subscribers", None),
        "created_utc": datetime.fromtimestamp(getattr(sub, "created_utc", 0), tz=timezone.utc) if getattr(sub, "created_utc", None) else None,
        "last_crawled_at": now,
        "rules_hash": rules_hash
    }
    with conn.cursor() as cur:
        cur.execute(UPSERT_SUBREDDIT, data)

    # Replace rules
    with conn.cursor() as cur:
        cur.execute(DELETE_RULES, (data["id"],))
        for i, r in enumerate(rules_list):
            cur.execute(INSERT_RULE, (data["id"], i, r.get("short_name") or "", r.get("description") or ""))
    # Replace link flairs
    with conn.cursor() as cur:
        cur.execute(DELETE_LINK_FLAIR, (data["id"],))
        for f in flairs:
            cur.execute(INSERT_LINK_FLAIR, (
                data["id"],
                f["id"],
                f.get("text") or "",
                bool(f.get("mod_only")),
                bool(f.get("text_editable"))))

    # Embedding: only if inputs changed (based on clipped text)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT input_hash FROM embedding WHERE subreddit_id=%s", (data["id"],))
        emb_row = cur.fetchone()
    embedding_changed = (emb_row is None) or (emb_row["input_hash"] != input_hash)

    if embedding_changed:
        try:
            emb = get_embedding(composite_text_for_embed)
            # A: Dimension check after receiving embedding
            if len(emb) != EMBED_DIM:
                raise ValueError(
                    f"Embedding dimension mismatch: got {len(emb)}, expected {EMBED_DIM}. "
                    f"Check EMBED_MODEL={EMBED_MODEL} vs EMBED_DIM={EMBED_DIM}."
                )
            with conn.cursor() as cur:
                cur.execute(UPSERT_EMBED, (
                    data["id"],
                    vec_to_pg(emb),
                    input_hash,
                    EMBED_MODEL,
                    now
                ))
        except Exception as e:
            print(f"[embed] {data['name']}: {e}")

    # LLM summary: only if input changed or vibe missing / model changed
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT summary, model_name, prompt_version FROM vibe WHERE subreddit_id=%s", (data["id"],))
        vibe_existing = cur.fetchone()

    need_summary = embedding_changed or (vibe_existing is None) \
        or (vibe_existing.get("model_name") != SUMMARY_MODEL) \
        or (vibe_existing.get("prompt_version") != "llm_summary_v1")

    if need_summary:
        try:
            llm_summary = generate_llm_summary(
                name=data["name"],
                public_desc=data["public_description"],
                rules_joined=combined_rules_for_llm,  # <-- includes post requirements + submit text
                content_type=compute_content_type(
                    data["submission_type"], data["allow_images"], data["allow_videos"], data["allow_polls"], flair_texts
                ),
                vibe_scores=vibe_scores,
                model=SUMMARY_MODEL
            )
            scores_source = "heuristic+llm"
            model_name_field = SUMMARY_MODEL
            prompt_version_field = "llm_summary_v1"
        except Exception as e:
            # fallback to heuristic summary if LLM fails
            llm_summary = summarize_vibe_fallback(vibe_scores, content_type)
            scores_source = "heuristic_fallback"
            model_name_field = "none"
            prompt_version_field = "heuristic_v1"
    else:
        llm_summary = vibe_existing["summary"]
        scores_source = "heuristic+llm"
        model_name_field = vibe_existing.get("model_name") or SUMMARY_MODEL
        prompt_version_field = vibe_existing.get("prompt_version") or "llm_summary_v1"

    # Upsert vibe
    vibe_row = {
        "subreddit_id": data["id"],
        "strictness": vibe_scores["strictness"],
        "beginner": vibe_scores["beginner"],
        "meme_tolerance": vibe_scores["meme_tolerance"],
        "self_promo": vibe_scores["self_promo"],
        "content_type": content_type,
        "seriousness": vibe_scores["seriousness"],
        "summary": llm_summary,
        "scores_source": scores_source,
        "prompt_version": prompt_version_field,
        "model_name": model_name_field,
        "computed_at": now,
    }
    with conn.cursor() as cur:
        cur.execute(UPSERT_VIBE, vibe_row)

    conn.commit()
    return data["name"]

# -------- Main --------

def create_reddit_rules_list(sub) -> List[Dict[str, str]]:
    """Helper to build rules list from PRAW (iterator-safe)."""
    out: List[Dict[str, str]] = []
    try:
        for rule in sub.rules:
            out.append({
                "short_name": getattr(rule, "short_name", "") or getattr(rule, "kind", "") or "",
                "description": getattr(rule, "description", "") or ""
            })
    except (Forbidden, NotFound):
        pass
    except Exception:
        pass
    return out

def create_schema_and_validate(conn: psycopg.Connection):
    create_schema(conn)
    validate_embedding_config(conn)

def main():
    with psycopg.connect(DATABASE_URL, autocommit=False) as conn:
        create_schema_and_validate(conn)

        stored = 0
        scanned = 0
        skipped = 0
        seen_ids: Set[str] = set()

        # Iterate popular with limit=None so we can continue until we truly store TOP_N
        for sub in iter_popular_sfw_subreddits(reddit, limit=None):
            if stored >= TOP_N:
                break

            scanned += 1

            # Skip duplicates within this run
            sub_id36 = getattr(sub, "id", None)
            if not sub_id36 or sub_id36 in seen_ids:
                skipped += 1
                continue
            seen_ids.add(sub_id36)

            # (Optional) also skip quarantined/private subs
            if getattr(sub, "quarantine", False) or getattr(sub, "quarantined", False) or getattr(sub, "subreddit_type", "") == "private":
                skipped += 1
                continue

            try:
                rules_list = create_reddit_rules_list(sub)
                flairs = safe_user_link_flairs(sub)

                name = upsert_subreddit(conn, sub, rules_list, flairs)
                stored += 1
                print(f"[{stored}] Stored: r/{name}")
            except PrawcoreException as e:
                skipped += 1
                print(f"[praw] error for r/{getattr(sub, 'display_name', '?')}: {e}")
            except Exception as e:
                skipped += 1
                print(f"[ingest] error for r/{getattr(sub, 'display_name', '?')}: {e}")

            time.sleep(1.0)  # considerate pacing

        if stored < TOP_N:
            print(f"Source exhausted before reaching TOP_N. Stored={stored}, scanned={scanned}, skipped={skipped}, target={TOP_N}")
        else:
            print(f"Finished. Stored {stored} subreddits (scanned={scanned}, skipped={skipped}).")

if __name__ == "__main__":
    main()
