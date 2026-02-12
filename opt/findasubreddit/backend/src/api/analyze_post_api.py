# src/api/analyze_post_api.py
import os
import re
import base64
import logging
from typing import List, Dict, Any, Optional, Tuple

import numpy as np
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from fastapi.middleware.trustedhost import TrustedHostMiddleware

import psycopg
from psycopg.rows import dict_row
from pgvector.psycopg import register_vector

# OpenAI >= 1.0
from openai import OpenAI

# Auth router
from .auth.reddit_auth import router as reddit_auth_router

# Get URL metadata
import re, ssl, html as ihtml
from urllib.parse import urlparse
from urllib.request import Request, urlopen

# ---------------------- ENV & CONFIG ----------------------
load_dotenv()

# Safer env reads (don't crash at import time)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
DATABASE_URL = os.getenv("DATABASE_URL", "")

# Embeddings
EMBED_MODEL = os.getenv("EMBED_MODEL", "text-embedding-3-small")

# Vision / Chat model for captions & summaries
CHAT_MODEL = os.getenv("CHAT_MODEL", "gpt-4o-mini")
VISION_MODEL = os.getenv("VISION_MODEL", "gpt-4o")

# Pagination
PAGE_SIZE_DEFAULT = int(os.getenv("PAGE_SIZE", "8"))
MAX_CANDIDATE_SUBS = int(os.getenv("MAX_CANDIDATE_SUBS", "200"))

# Hybrid retrieval: combine lexical (FTS) + semantic (vector). Weights in [0, 1]; should sum to 1.
HYBRID_LEXICAL_WEIGHT = float(os.getenv("HYBRID_LEXICAL_WEIGHT", "0.35"))
HYBRID_SEMANTIC_WEIGHT = float(os.getenv("HYBRID_SEMANTIC_WEIGHT", "0.65"))
HYBRID_CANDIDATES_PER_BRANCH = int(os.getenv("HYBRID_CANDIDATES_PER_BRANCH", "300"))  # fetch more from each branch then merge

# Rule matching behavior
RULE_MATCH_THRESHOLD = float(os.getenv("RULE_MATCH_THRESHOLD", "0.55"))  # cosine similarity threshold
MAX_RULES_PER_SUB_FOR_CHECK = int(os.getenv("MAX_RULES_PER_SUB_FOR_CHECK", "20"))
MAX_WARNINGS_PER_SUB = int(os.getenv("MAX_WARNINGS_PER_SUB", "5"))
MAX_TOTAL_RULES_TO_EMBED = int(os.getenv("MAX_TOTAL_RULES_TO_EMBED", "300"))  # upper bound per request

# Rerank: after hybrid + topic filter, take this many candidates and rerank with constraints
RERANK_TOP_N = int(os.getenv("RERANK_TOP_N", "50"))

# CORS
FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN")

# Logging
logger = logging.getLogger("analyze_post_api")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

def _parse_list_env(value: Optional[str], default: str = "") -> List[str]:
    raw = value if (value and value.strip()) else default
    parts = [p.strip() for p in re.split(r"[, \t]+", raw) if p.strip()]
    return parts

# ---- Trusted hosts: prefer TRUSTED_HOSTS, fallback to ALLOWED_HOSTS, default '*' ----
_trusted_hosts_env = os.getenv("TRUSTED_HOSTS") or os.getenv("ALLOWED_HOSTS") or "*"
ALLOWED_HOSTS = _parse_list_env(
    _trusted_hosts_env,
    default="*"
)

# Ensure localhost helpers are present unless wildcard already present
if "*" not in ALLOWED_HOSTS:
    for _h in ("localhost", "127.0.0.1"):
        if _h not in ALLOWED_HOSTS:
            ALLOWED_HOSTS.append(_h)

app = FastAPI()

# ---------------------- APP SETUP ----------------------

# Trusted hosts (keep security, but allow DO probes & previews)
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=ALLOWED_HOSTS
)

# CORS setup (merge CORS_ORIGINS + FRONTEND_ORIGIN if provided)
cors_origins = _parse_list_env(
    os.getenv("CORS_ORIGINS"),
    default="https://YOUR_DOMAIN https://www.YOUR_DOMAIN"
)
if FRONTEND_ORIGIN and FRONTEND_ORIGIN not in cors_origins:
    cors_origins.append(FRONTEND_ORIGIN)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

@app.get("/health")
def health():
    """
    Lightweight health endpoint: no external calls.
    Always returns quickly for DO readiness/liveness probes.
    """
    try:
        db_status = "connected" if _db_conn is not None else "not_connected"
        openai_configured = bool(OPENAI_API_KEY.strip())
        overall_status = "ok" if db_status == "connected" else "degraded"
        return {
            "status": overall_status,
            "database": db_status,
            "openai_configured": openai_configured,
            "message": "Service is running" if overall_status == "ok"
                       else "Service is running but DB not ready",
        }
    except Exception as e:
        logger.error(f"Health endpoint error: {e}")
        # Return 200 so probes don't flap; include context in body
        return {
            "status": "error",
            "database": "unknown",
            "openai_configured": False,
            "message": f"Health check error: {str(e)}",
        }

@app.get("/")
def root():
    return {"ok": True}

@app.get("/test")
def test():
    return {"message": "Test endpoint working", "timestamp": "now"}

@app.get("/healthz")
def healthz():
    """Simple health check endpoint that always returns 200"""
    try:
        return {"status": "ok", "message": "Service is running"}
    except Exception as e:
        logger.error(f"Healthz endpoint error: {e}")
        return {"status": "error", "message": f"Service error: {str(e)}"}

@app.get("/startup-status")
def startup_status():
    """Check startup status and environment variables (no secrets)"""
    return {
        "status": "ok",
        "database_url_set": bool(DATABASE_URL),
        "openai_api_key_set": bool(OPENAI_API_KEY),
        "database_connected": _db_conn is not None,
        "reddit_mounted": _reddit_mounted,
        "environment": {
            "database_url_length": len(DATABASE_URL) if DATABASE_URL else 0,
            "openai_key_length": len(OPENAI_API_KEY) if OPENAI_API_KEY else 0,
            "log_level": os.getenv("LOG_LEVEL", "NOT_SET"),
            "trusted_hosts": ALLOWED_HOSTS,
            "cors_origins": cors_origins,
        },
    }

# Include the Reddit OAuth router (handles login/callback/me/logout) under /api/auth
app.include_router(reddit_auth_router, prefix="/api/auth", tags=["auth"])

# OpenAI client (lazy initialization)
_openai_client: Optional[OpenAI] = None

def get_openai_client() -> Optional[OpenAI]:
    """Get OpenAI client, creating it if needed and possible"""
    global _openai_client
    if _openai_client is None and OPENAI_API_KEY and OPENAI_API_KEY.strip():
        try:
            # Keep defaults; avoid using this in /health
            _openai_client = OpenAI(api_key=OPENAI_API_KEY)
        except Exception as e:
            logger.error(f"Failed to create OpenAI client: {e}")
            return None
    return _openai_client

# DB connection (global)
_db_conn: Optional[psycopg.Connection] = None
_reddit_mounted = False

@app.on_event("startup")
def _startup():
    global _db_conn, _reddit_mounted
    logger.info("Starting application startup...")

    if not DATABASE_URL:
        logger.error("DATABASE_URL environment variable is not set")
        return

    try:
        logger.info("DATABASE_URL is set, attempting database connection...")
        _db_conn = psycopg.connect(DATABASE_URL, row_factory=dict_row, autocommit=True)
        register_vector(_db_conn)  # enable passing Python lists as pgvector
        logger.info("Database connected successfully")

        if not _reddit_mounted:
            logger.info("Attempting to mount reddit_post_app...")
            from .reddit_post_api import reddit_post_app
            app.mount("/api/reddit", reddit_post_app)
            _reddit_mounted = True
            logger.info("Reddit post API mounted successfully")

        logger.info("analyze_post_api started; DB connected and /reddit mounted")
        logger.info("Trusted hosts: %s", ALLOWED_HOSTS)
        logger.info("CORS allow_origins: %s", cors_origins)
    except Exception as e:
        logger.error(f"Startup failed: {e}")
        logger.error(f"Startup error type: {type(e)}")
        import traceback
        logger.error(f"Startup traceback: {traceback.format_exc()}")
        # Do not re-raise; app should still start and /health will show degraded

@app.on_event("shutdown")
def _shutdown():
    global _db_conn
    if _db_conn:
        _db_conn.close()
        _db_conn = None

# ---------------------- MODELS ----------------------
class SubredditMatch(BaseModel):
    subreddit: str
    score: float
    subscribers: int
    description: str
    rules: List[str]
    ai_warning: List[str] = []
    beginner_friendly_score: Optional[int] = Field(None, ge=0, le=5)
    seriousness_score: Optional[int] = Field(None, ge=0, le=5)
    content_types_not_allowed: List[str] = []
    summary: Optional[str] = None
    topics: List[str] = []  # topic tags from ingestion (optional, non-breaking)

class AnalyzePostResponse(BaseModel):
    results: List[SubredditMatch]
    has_more: bool
    image_captions: Optional[List[str]] = None
    ai_summary: Optional[str] = None  # concise summary of the user's post

# ---------------------- OPENAI HELPERS ----------------------
def get_embedding(text: str) -> List[float]:
    client = get_openai_client()
    if not client:
        raise HTTPException(status_code=500, detail="OpenAI client not available")
    resp = client.embeddings.create(model=EMBED_MODEL, input=text)
    return resp.data[0].embedding  # type: ignore[no-any-return]

def get_batch_embeddings(texts: List[str]) -> List[List[float]]:
    if not texts:
        return []
    client = get_openai_client()
    if not client:
        raise HTTPException(status_code=500, detail="OpenAI client not available")
    resp = client.embeddings.create(model=EMBED_MODEL, input=texts)
    return [d.embedding for d in resp.data]  # type: ignore[no-any-return]

def cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    denom = (np.linalg.norm(a) * np.linalg.norm(b)) or 1e-9
    return float(np.dot(a, b) / denom)

def summarize_post_for_preview(title: str, body: str, context: Optional[str]) -> str:
    prompt = (
        "Summarize the following Reddit post draft in one short, clear sentence. "
        "Audience is subreddit mods and regulars. Avoid hype; be specific.\n\n"
        f"Title: {title.strip()}\n"
        f"Body: {body.strip()}\n"
        f"Context (optional): {context.strip() if context else ''}\n"
    )
    try:
        client = get_openai_client()
        if not client:
            logger.warning("OpenAI client not available for summary")
            return ""
        chat = client.chat.completions.create(
            model=CHAT_MODEL,
            messages=[
                {"role": "system", "content": "You write concise summaries for Reddit posts."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=64,
            temperature=0.2,
        )
        return (chat.choices[0].message.content or "").strip()
    except Exception as ex:
        logger.warning("AI summary failed: %s", ex)
        return ""

# ---------------------- SEARCH SPEC & POSITIVE-ONLY EMBED ----------------------
def _parse_list_param(value: Optional[str]) -> List[str]:
    """Parse comma/whitespace-separated string to list of non-empty, stripped, lowercased strings."""
    if not value or not value.strip():
        return []
    return [p.strip().lower() for p in re.split(r"[, \t]+", value) if p.strip()]


def build_embed_text_positive_only(
    title: str,
    body: str,
    context: str,
    link: Optional[str],
    include_terms: List[str],
    exclude_terms: List[str],
    exclude_topics: List[str],
) -> str:
    """
    Build the ONLY text that may be sent to the embedding model.
    Uses only positive signals: title, body, context, link, include_terms.
    exclude_terms and exclude_topics must NOT appear in the returned string
    (stripped case-insensitively so embedding never sees negative intent).
    """
    parts = [title.strip(), body.strip()]
    if context:
        parts.append(f"Context: {context.strip()}")
    if link and link.strip():
        parts.append(f"Link: {link.strip()}")
    text = "\n\n".join(p for p in parts if p)
    if include_terms:
        text = (text + "\n\n" + " ".join(include_terms)).strip()
    # Remove any occurrence of exclude terms and exclude_topics (case-insensitive)
    to_remove = list(exclude_terms) + list(exclude_topics)
    for term in to_remove:
        if not term:
            continue
        # Remove the phrase everywhere (case-insensitive)
        pattern = re.compile(re.escape(term), re.IGNORECASE)
        text = pattern.sub("", text)
    # Collapse repeated whitespace and trim
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _apply_topic_filter(
    candidates: List[Dict[str, Any]],
    must_topics: List[str],
    exclude_topics: List[str],
) -> List[Dict[str, Any]]:
    """
    Hard topic filter BEFORE combining scores / top N.
    - must_topics: AND/overlap — keep only if subreddit.topics overlaps must_topics (or must_topics is empty).
    - exclude_topics: NOT — keep only if subreddit.topics has no overlap with exclude_topics.
    """
    if not must_topics and not exclude_topics:
        return candidates
    must_set = set(t.lower() for t in must_topics)
    exclude_set = set(t.lower() for t in exclude_topics)
    out: List[Dict[str, Any]] = []
    for row in candidates:
        sub_topics = row.get("topics") or []
        sub_set = set((t or "").lower() for t in sub_topics)
        if must_set and not (sub_set & must_set):
            continue
        if exclude_set and (sub_set & exclude_set):
            continue
        out.append(row)
    return out


def _rerank_with_constraints(
    candidates: List[Dict[str, Any]],
    must_topics: List[str],
    exclude_topics: List[str],
    include_terms: List[str],
    exclude_terms: List[str],
) -> List[Dict[str, Any]]:
    """
    Rerank top-N candidates (already topic-filtered) with constraint-aware scoring.
    Does not add/remove items; only reorders. Filtered-out items cannot be resurrected.
    """
    if not candidates:
        return []
    must_set = set(t.lower() for t in must_topics)
    exclude_set = set(t.lower() for t in exclude_topics)
    include_set = set(t.lower() for t in include_terms)
    exclude_terms_set = set(t.lower() for t in exclude_terms)

    def score(row: Dict[str, Any]) -> Tuple[float, str]:
        base = float(row.get("similarity") or 0)
        sub_topics = set((t or "").lower() for t in (row.get("topics") or []))
        name = (row.get("name") or "").lower()
        desc = (row.get("public_description") or "").lower()
        # Boost for must_topics overlap (meaningful so one match can overcome small score gaps)
        if must_set:
            base += 0.15 * len(sub_topics & must_set)
        # Penalty for exclude_topics (should be 0 after filter; defensive)
        base -= 0.2 * len(sub_topics & exclude_set)
        # Small boost for include term in name/desc
        for w in include_set:
            if w in name or w in desc:
                base += 0.02
                break
        # Penalty for exclude term in name/desc
        for w in exclude_terms_set:
            if w in name or w in desc:
                base -= 0.1
                break
        return (base, name)

    return sorted(candidates, key=lambda row: (-score(row)[0], (row.get("name") or "").lower()))


# ---------------------- DB HELPERS ----------------------
def _query_lexical_candidates(
    conn: psycopg.Connection, query_tsquery: str, limit: int
) -> List[Dict[str, Any]]:
    """
    Get candidate subreddits by full-text search (ts_rank over search_tsv).
    query_tsquery must be a valid tsquery string (e.g. from plainto_tsquery); use '' to skip FTS.
    """
    if not (query_tsquery and query_tsquery.strip()):
        return []
    sql = """
        SELECT
            s.id,
            s.name,
            s.public_description,
            s.subscribers,
            s.submission_type,
            s.allow_images,
            s.allow_videos,
            s.allow_polls,
            s.topics,
            v.beginner,
            v.seriousness,
            v.summary AS vibe_summary,
            ts_rank_cd(e.search_tsv, plainto_tsquery('english', %(qt)s)) AS fts_rank
        FROM embedding e
        JOIN subreddit s ON s.id = e.subreddit_id
        LEFT JOIN vibe v ON v.subreddit_id = s.id
        WHERE e.search_tsv IS NOT NULL AND e.search_tsv @@ plainto_tsquery('english', %(qt)s)
        ORDER BY fts_rank DESC, s.name ASC
        LIMIT %(lim)s
    """
    try:
        with conn.cursor() as cur:
            cur.execute(sql, {"qt": query_tsquery, "lim": limit})
            return cur.fetchall()
    except Exception as ex:
        logger.error("Postgres FTS query failed: %s", ex)
        return []


def _query_semantic_candidates(
    conn: psycopg.Connection, query_vec: List[float], limit: int
) -> List[Dict[str, Any]]:
    """
    Get candidate subreddits by vector similarity (cosine).
    similarity = 1 - distance.
    """
    sql = """
        SELECT
            s.id,
            s.name,
            s.public_description,
            s.subscribers,
            s.submission_type,
            s.allow_images,
            s.allow_videos,
            s.allow_polls,
            s.topics,
            v.beginner,
            v.seriousness,
            v.summary AS vibe_summary,
            1 - (e.embedding <=> %(qv)s::vector) AS similarity
        FROM embedding e
        JOIN subreddit s ON s.id = e.subreddit_id
        LEFT JOIN vibe v ON v.subreddit_id = s.id
        ORDER BY e.embedding <=> %(qv)s::vector
        LIMIT %(lim)s
    """
    try:
        with conn.cursor() as cur:
            cur.execute(sql, {"qv": query_vec, "lim": limit})
            return cur.fetchall()
    except Exception as ex:
        logger.error("Postgres similarity query failed: %s", ex)
        raise


def _query_hybrid(
    conn: psycopg.Connection,
    query_text: str,
    query_vec: List[float],
    limit: int,
) -> List[Dict[str, Any]]:
    """
    Hybrid retrieval: combine lexical (FTS ts_rank) and semantic (pgvector) scores
    with configurable weights. Downweight subreddit name by using combined search_tsv
    (description + rules + wiki + flair). Returns top `limit` rows with deterministic
    ordering (combined score DESC, then s.name ASC).
    """
    k = min(limit * 3, HYBRID_CANDIDATES_PER_BRANCH)
    # Sanitize query for plainto_tsquery: use first 500 chars, strip
    q_clean = (query_text or "")[:500].strip().replace("'", " ")
    lexical_rows = _query_lexical_candidates(conn, q_clean, k) if q_clean else []
    semantic_rows = _query_semantic_candidates(conn, query_vec, k)

    # Key by subreddit id; keep one row with merged scores
    by_id: Dict[str, Dict[str, Any]] = {}
    for r in semantic_rows:
        sid = r["id"]
        by_id[sid] = dict(r)
        by_id[sid]["semantic_score"] = float(r.get("similarity") or 0)
        by_id[sid]["lexical_rank"] = None

    fts_max = 0.0
    for r in lexical_rows:
        sid = r["id"]
        rank = float(r.get("fts_rank") or 0)
        if rank > fts_max:
            fts_max = rank
        if sid not in by_id:
            by_id[sid] = dict(r)
            by_id[sid]["semantic_score"] = 0.0
            by_id[sid]["lexical_rank"] = rank
        else:
            by_id[sid]["lexical_rank"] = rank

    # Normalize FTS to [0, 1] and compute combined score
    for sid, row in by_id.items():
        lr = row.get("lexical_rank")
        ls = (lr / fts_max) if (fts_max and lr is not None) else 0.0
        ss = row.get("semantic_score", 0.0)
        row["similarity"] = HYBRID_LEXICAL_WEIGHT * ls + HYBRID_SEMANTIC_WEIGHT * ss
        row["fts_norm"] = ls
        row["sem_norm"] = ss

    # Deterministic sort: combined score DESC, then name ASC
    ordered = sorted(
        by_id.values(),
        key=lambda x: (-(x["similarity"] or 0), (x.get("name") or "").lower()),
    )
    return ordered[:limit]


def _query_similar_subreddits(conn: psycopg.Connection, query_vec: List[float], limit: int) -> List[Dict[str, Any]]:
    """
    Get candidate subreddits by hybrid retrieval (lexical + semantic).
    Kept for backwards compatibility; delegates to _query_hybrid with empty query text
    when only vector is available (caller should pass query_text for full hybrid).
    """
    return _query_hybrid(conn, "", query_vec, limit)

def _fetch_rules_for_subs(conn: psycopg.Connection, sub_ids: List[str], per_sub_cap: int) -> Dict[str, List[Dict[str, Any]]]:
    if not sub_ids:
        return {}
    sql = """
        SELECT subreddit_id, idx, short_name, description
        FROM rules
        WHERE subreddit_id = ANY(%(ids)s)
        ORDER BY subreddit_id, idx
    """
    out: Dict[str, List[Dict[str, Any]]] = {}
    try:
        with conn.cursor() as cur:
            cur.execute(sql, {"ids": sub_ids})
            for row in cur:
                sid = row["subreddit_id"]
                out.setdefault(sid, [])
                if len(out[sid]) < per_sub_cap:
                    out[sid].append({
                        "idx": row["idx"],
                        "short_name": row["short_name"],
                        "description": row["description"] or "",
                    })
        return out
    except Exception as ex:
        logger.error("Postgres rules fetch failed: %s", ex)
        raise

def _content_types_not_allowed(sub: Dict[str, Any]) -> List[str]:
    not_allowed: List[str] = []
    submission_type_raw = (sub.get("submission_type") or "").strip().lower()
    submission_type = submission_type_raw if submission_type_raw in ("any", "self", "link") else "any"
    allow_images = bool(sub.get("allow_images"))
    allow_videos = bool(sub.get("allow_videos"))
    allow_polls = bool(sub.get("allow_polls"))

    # Only add 'links' as not allowed for text-only subs
    if submission_type == "self":
        not_allowed.append("links")
    if not allow_images:
        not_allowed.append("images")
    if not allow_videos:
        not_allowed.append("videos")
    if not allow_polls:
        not_allowed.append("polls")
    return not_allowed

# --- helper: tiny, dependency-free HTML meta extract ---
_META_TAG = re.compile(r"<meta\\b[^>]*>", re.I)
_ATTR = re.compile(r'(\\w+)\\s*=\\s*([\"\\\'])(.*?)\\2', re.I | re.S)
_TITLE_TAG = re.compile(r"<title\\b[^>]*>(.*?)</title>", re.I | re.S)

def _extract_meta(content: str, key: str, attr_name: str = "property") -> str:
    for m in _META_TAG.finditer(content):
        tag = m.group(0)
        attrs = {a.group(1).lower(): a.group(3) for a in _ATTR.finditer(tag)}
        if attrs.get(attr_name, "").lower() == key.lower():
            return ihtml.unescape(attrs.get("content", "").strip())
    return ""

def _safe_fetch(url: str, timeout: float = 6.0, max_bytes: int = 600_000) -> str:
    # basic SSRF guard
    pu = urlparse(url)
    if pu.scheme not in ("http", "https"):
        raise ValueError("Unsupported scheme")
    if pu.hostname in {"localhost", "127.0.0.1"}:
        raise ValueError("Blocked host")

    req = Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; FindASubreddit/1.0)",
        "Accept": "text/html,application/xhtml+xml"
    })
    ctx = ssl.create_default_context()
    with urlopen(req, context=ctx, timeout=timeout) as resp:
        data = resp.read(max_bytes)
    return data.decode("utf-8", errors="replace")

@app.get("/api/link_metadata")
def link_metadata(url: str):
    try:
        html = _safe_fetch(url)
    except Exception as e:
        return {"title": "", "description": "", "site_name": "", "error": str(e)}

    # prefer og:title, then twitter:title, then <title>
    title = (
        _extract_meta(html, "og:title")
        or _extract_meta(html, "twitter:title", attr_name="name")
        or ihtml.unescape(_TITLE_TAG.search(html).group(1).strip()) if _TITLE_TAG.search(html) else ""
    )

    desc = (
        _extract_meta(html, "og:description")
        or _extract_meta(html, "description", attr_name="name")
    )
    site = _extract_meta(html, "og:site_name") or ""

    return {"title": title, "description": desc, "site_name": site}


# ---------------------- IMAGE CAPTIONING ----------------------
async def caption_images(files: Optional[List[UploadFile]]) -> List[str]:
    captions: List[str] = []
    if not files:
        return captions

    for file in files:
        if not (file.content_type and file.content_type.startswith("image/")):
            continue
        img_bytes = await file.read()
        img_base64 = base64.b64encode(img_bytes).decode("utf-8")
        try:
            client = get_openai_client()
            if not client:
                logger.warning("OpenAI client not available for image captioning")
                captions.append("[Image analysis not available]")
                continue
            result = client.chat.completions.create(
                model=VISION_MODEL,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "Describe this image for subreddit search context. Be specific and concise."},
                            {"type": "image_url", "image_url": {"url": f"data:{file.content_type};base64,{img_base64}"}}
                        ]
                    }
                ],
                max_tokens=128,
                temperature=0.2,
            )
            desc = (result.choices[0].message.content or "").strip()
            if desc:
                captions.append(desc)
        except Exception as ex:
            logger.warning("Vision captioning failed: %s", ex)
            captions.append("[Image could not be analyzed]")
    return captions

# ---------------------- RULE VIOLATION CHECK ----------------------
def compute_rule_violations(
    post_embedding: List[float],
    rules_by_sub: Dict[str, List[Dict[str, Any]]],
    threshold: float,
    max_warnings_per_sub: int
) -> Dict[str, List[str]]:
    flat: List[Tuple[str, int, str, str]] = []  # (subreddit_id, idx, short_name, description)
    total = 0
    for sid, rules in rules_by_sub.items():
        for r in rules:
            if total >= MAX_TOTAL_RULES_TO_EMBED:
                break
            txt = (r.get("description") or "").strip()
            if not txt:
                continue
            flat.append((sid, r.get("idx", 0), r.get("short_name") or "", txt))
            total += 1
        if total >= MAX_TOTAL_RULES_TO_EMBED:
            break

    if not flat:
        return {}

    try:
        rule_texts = [t[3] for t in flat]
        rule_embs = get_batch_embeddings(rule_texts)
    except Exception as ex:
        logger.error("Embedding rules failed: %s", ex)
        return {}

    post_vec = np.array(post_embedding, dtype=np.float32)
    out: Dict[str, List[Tuple[float, str]]] = {}

    for (sid, idx, short_name, desc), remb in zip(flat, rule_embs):
        rvec = np.array(remb, dtype=np.float32)
        sim = cosine_sim(post_vec, rvec)
        if sim >= threshold:
            label = short_name.strip() or f"Rule {idx}"
            full = f"{label}: {desc.strip()}"
            out.setdefault(sid, []).append((sim, full))

    final: Dict[str, List[str]] = {}
    for sid, pairs in out.items():
        pairs.sort(key=lambda x: x[0], reverse=True)
        final[sid] = [p[1] for p in pairs[:max_warnings_per_sub]]
    return final

# ---------------------- ENDPOINT ----------------------
@app.post("/api/analyze_post", response_model=AnalyzePostResponse)
async def analyze_post(
    title: str = Form(""),
    body: str = Form(""),
    context: Optional[str] = Form(None),
    page: int = Form(1),
    limit: Optional[int] = Form(None),
    files: Optional[List[UploadFile]] = File(None),
    link: Optional[str] = Form(None),  # accept link from UI (optional)
    must_topics: Optional[str] = Form(None),   # comma-separated; AND/overlap
    exclude_topics: Optional[str] = Form(None),  # comma-separated; hard NOT
    include: Optional[str] = Form(None),   # comma-separated positive terms
    exclude: Optional[str] = Form(None),  # comma-separated; must NOT appear in embed text
):
    """
    Analyze a drafted Reddit post and return similar subreddits using Postgres (pgvector),
    plus rule-violation hints, vibe scores, and content-type constraints.
    Pipeline: Parse SearchSpec → build embedText (positive-only) → retrieve → hard topic filter → top 50 → rerank → top N.
    """
    if _db_conn is None:
        raise HTTPException(status_code=500, detail="Database not initialized")

    # Parse search constraints (optional; backward compatible)
    must_topics_list = _parse_list_param(must_topics)
    exclude_topics_list = _parse_list_param(exclude_topics)
    include_terms = _parse_list_param(include)
    exclude_terms = _parse_list_param(exclude)

    # 1) Optional: AI captions for any uploaded images
    ai_image_captions = await caption_images(files)

    # 2) Build context (with captions) and POSITIVE-ONLY embed text (exclude/exclude_topics must NOT be embedded)
    enhanced_context = (context or "").strip()
    if ai_image_captions:
        enhanced_context = (enhanced_context + "\n\n" + "\n\n".join(ai_image_captions)).strip()

    embed_text = build_embed_text_positive_only(
        title=title.strip(),
        body=body.strip(),
        context=enhanced_context,
        link=link.strip() if link else None,
        include_terms=include_terms,
        exclude_terms=exclude_terms,
        exclude_topics=exclude_topics_list,
    )

    if not embed_text.strip():
        raise HTTPException(status_code=400, detail="Please provide a title, body, image, link, or context.")

    # 3) Embedding ONLY from positive-only text (never embed exclude terms or exclude_topics)
    try:
        post_embedding = get_embedding(embed_text)
    except Exception as e:
        logger.error("Embedding error: %s", e)
        raise HTTPException(status_code=500, detail="Embedding error. Check OPENAI_API_KEY and EMBED_MODEL.")

    # 4) Hybrid retrieval (FTS + pgvector) using same positive-only text for lexical
    try:
        candidates = _query_hybrid(
            _db_conn,
            query_text=embed_text,
            query_vec=post_embedding,
            limit=MAX_CANDIDATE_SUBS,
        )
    except Exception as e:
        msg = (
            "Postgres vector search failed. "
            "Likely causes: pgvector not installed, parameter not cast (::vector), or dimension mismatch. "
            "Check API logs for the exact error."
        )
        raise HTTPException(status_code=500, detail=msg)

    if not candidates:
        return AnalyzePostResponse(results=[], has_more=False, image_captions=ai_image_captions, ai_summary="")

    # 5) Hard topic filter BEFORE combining scores / top N (must_topics overlap, exclude_topics NOT)
    filtered = _apply_topic_filter(candidates, must_topics_list, exclude_topics_list)

    # 6) Top 50 then rerank with constraints (rerank cannot resurrect filtered-out items)
    top50 = filtered[:RERANK_TOP_N]
    reranked = _rerank_with_constraints(
        top50, must_topics_list, exclude_topics_list, include_terms, exclude_terms
    )
    all_results = reranked + filtered[RERANK_TOP_N:]

    # 7) Fetch rules for these candidates (cap per subreddit)
    sub_ids = [row["id"] for row in all_results]
    try:
        rules_by_sub = _fetch_rules_for_subs(_db_conn, sub_ids, MAX_RULES_PER_SUB_FOR_CHECK)
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to fetch subreddit rules from Postgres.")

    # 6) Compute rule violation suggestions (embeddings vs rules)
    rule_violations = compute_rule_violations(
        post_embedding=post_embedding,
        rules_by_sub=rules_by_sub,
        threshold=RULE_MATCH_THRESHOLD,
        max_warnings_per_sub=MAX_WARNINGS_PER_SUB,
    )

    # 8) Build match objects from final ordered list (reranked top 50 + rest)
    matches: List[SubredditMatch] = []
    for row in all_results:
        sid = row["id"]
        rules = rules_by_sub.get(sid, [])
        rules_list = [(r.get("description") or "").strip() for r in rules if (r.get("description") or "").strip()]
        ai_warning = rule_violations.get(sid, [])

        topics_raw = row.get("topics")
        topics_list = list(topics_raw) if topics_raw else []

        match = SubredditMatch(
            subreddit=row["name"],
            score=float(row["similarity"]),
            subscribers=int(row.get("subscribers") or 0),
            description=row.get("public_description") or "",
            rules=rules_list,
            ai_warning=ai_warning,
            beginner_friendly_score=int(row["beginner"]) if row.get("beginner") is not None else None,
            seriousness_score=int(row["seriousness"]) if row.get("seriousness") is not None else None,
            content_types_not_allowed=_content_types_not_allowed(row),
            summary=(row.get("vibe_summary") or None),
            topics=topics_list,
        )
        matches.append(match)

    # 10) Paginate (order already fixed: reranked top 50 then filtered tail)
    page = max(1, page)
    page_size = limit if (isinstance(limit, int) and limit > 0) else PAGE_SIZE_DEFAULT
    start = (page - 1) * page_size
    end = start + page_size
    paginated_matches = matches[start:end]
    has_more = len(matches) > end

    # 11) AI summary of the user's post (short, 1 sentence)
    ai_summary = summarize_post_for_preview(title, body, enhanced_context)

    return AnalyzePostResponse(
        results=paginated_matches,
        has_more=has_more,
        image_captions=ai_image_captions if ai_image_captions else None,
        ai_summary=ai_summary or None,
    )
