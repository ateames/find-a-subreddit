#!/usr/bin/env python3
"""
Backfill topic tags and FTS (search_text, search_tsv) + re-embed combined text for existing subreddits.

Run after migration 001_topics_and_fts.sql. Uses same combined text as ingestion:
  description + rules + wiki (not available in DB, so omitted) + flair.

Usage:
  Local:   python -m scripts.backfill_topics_and_fts [--dry-run] [--limit N]
  Prod:    same, with DATABASE_URL and OPENAI_API_KEY set.

Requires: DATABASE_URL, OPENAI_API_KEY (for re-embedding).
"""

import os
import sys
import argparse
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv(usecwd=True))

import psycopg
from psycopg.rows import dict_row

# Reuse ingestion helpers (topic taxonomy, composite text, embedding, clip)
_scripts_dir = os.path.dirname(os.path.abspath(__file__))
_backend_dir = os.path.dirname(_scripts_dir)
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)
# Import by path so it works when run as python scripts/backfill_topics_and_fts.py
import importlib.util
_spec = importlib.util.spec_from_file_location("ingest_reddit_to_postgres", os.path.join(_scripts_dir, "ingest_reddit_to_postgres.py"))
_ingest = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_ingest)

build_composite_text = _ingest.build_composite_text
compute_topics_rule_based = _ingest.compute_topics_rule_based
enrich_topics_llm = _ingest.enrich_topics_llm
clip_for_embedding = _ingest.clip_for_embedding
get_embedding = _ingest.get_embedding
vec_to_pg = _ingest.vec_to_pg
sha256_str = _ingest.sha256_str
EMBED_MODEL = _ingest.EMBED_MODEL
EMBED_DIM = _ingest.EMBED_DIM
EMBED_CLIP_CHARS = _ingest.EMBED_CLIP_CHARS
EMBED_TOKEN_LIMIT = _ingest.EMBED_TOKEN_LIMIT
USE_LLM_TOPICS = _ingest.USE_LLM_TOPICS
ensure_migration_001_columns = _ingest.ensure_migration_001_columns

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("backfill_topics_fts")

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is required")

# SQL: upsert subreddit topics only
UPDATE_SUBREDDIT_TOPICS = """
UPDATE subreddit SET topics = %s WHERE id = %s;
"""

# SQL: update only search_text and search_tsv (no re-embed)
UPDATE_EMBED_FTS_ONLY = """
UPDATE embedding SET search_text = %s, search_tsv = to_tsvector('english', coalesce(%s, '')), updated_at = %s
WHERE subreddit_id = %s;
"""

# SQL: full upsert when re-embedding
UPSERT_EMBED_FULL = """
INSERT INTO embedding (subreddit_id, embedding, input_hash, model_name, updated_at, search_text, search_tsv)
VALUES (%s, %s::vector, %s, %s, %s, %s, to_tsvector('english', coalesce(%s, '')))
ON CONFLICT (subreddit_id) DO UPDATE SET
  embedding = EXCLUDED.embedding,
  input_hash = EXCLUDED.input_hash,
  model_name = EXCLUDED.model_name,
  updated_at = EXCLUDED.updated_at,
  search_text = EXCLUDED.search_text,
  search_tsv = EXCLUDED.search_tsv;
"""


def fetch_subreddits_with_rules_and_flairs(conn: psycopg.Connection) -> List[Dict[str, Any]]:
    """Load all subreddits and attach rules + flair text per id."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("""
            SELECT id, name, title, public_description, description_md
            FROM subreddit
            ORDER BY id
        """)
        subs = cur.fetchall()

    if not subs:
        return []

    ids = [s["id"] for s in subs]
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT subreddit_id, description FROM rules WHERE subreddit_id = ANY(%s) ORDER BY subreddit_id, idx",
            (ids,),
        )
        rules_by_id: Dict[str, List[str]] = {}
        for row in cur.fetchall():
            rules_by_id.setdefault(row["subreddit_id"], []).append(row["description"] or "")
        cur.execute(
            "SELECT subreddit_id, flair_text FROM link_flair WHERE subreddit_id = ANY(%s)",
            (ids,),
        )
        flair_by_id: Dict[str, List[str]] = {}
        for row in cur.fetchall():
            flair_by_id.setdefault(row["subreddit_id"], []).append(row["flair_text"] or "")

    for s in subs:
        sid = s["id"]
        rules_text = " | ".join(rules_by_id.get(sid, []))
        flair_texts = flair_by_id.get(sid, [])
        s["rules_text"] = rules_text
        s["flair_texts"] = flair_texts
    return subs


def backfill_one(
    conn: psycopg.Connection,
    sub: Dict[str, Any],
    dry_run: bool,
    reembed: bool,
) -> None:
    name = sub["name"]
    public_desc = sub.get("public_description") or ""
    rules_text = sub.get("rules_text") or ""
    flair_texts = sub.get("flair_texts") or []
    flair_joined = " ".join(flair_texts)
    submit_text = ""  # not stored per-sub in backfill; use empty

    composite = build_composite_text(
        name,
        public_desc,
        submit_text,
        rules_text,
        wiki_text="",
        flair_text=flair_joined,
    )
    composite_clipped = clip_for_embedding(composite, EMBED_CLIP_CHARS, EMBED_TOKEN_LIMIT)

    # Topics
    topics_rule = compute_topics_rule_based(name, public_desc, rules_text, flair_texts)
    if USE_LLM_TOPICS:
        topics_list = enrich_topics_llm(name, public_desc, rules_text[:1500], topics_rule)
    else:
        topics_list = topics_rule

    if not dry_run:
        with conn.cursor() as cur:
            cur.execute(UPDATE_SUBREDDIT_TOPICS, (topics_list, sub["id"]))

    # Embedding + search_text + search_tsv
    now = datetime.now(timezone.utc)
    input_hash = sha256_str(composite_clipped)

    if reembed:
        try:
            emb = get_embedding(composite_clipped)
            if len(emb) != EMBED_DIM:
                logger.warning("r/%s: embedding dim %s != %s, skip embed update", name, len(emb), EMBED_DIM)
                vec_pg = None
            else:
                vec_pg = vec_to_pg(emb)
        except Exception as e:
            logger.warning("r/%s: embedding failed %s", name, e)
            vec_pg = None
    else:
        vec_pg = None  # keep existing vector

    if not dry_run:
        with conn.cursor() as cur:
            if reembed and vec_pg:
                cur.execute(
                    UPSERT_EMBED_FULL,
                    (
                        sub["id"],
                        vec_pg,
                        input_hash,
                        EMBED_MODEL,
                        now,
                        composite_clipped,
                        composite_clipped,
                    ),
                )
            else:
                cur.execute(
                    UPDATE_EMBED_FTS_ONLY,
                    (composite_clipped, composite_clipped, now, sub["id"]),
                )

    logger.info("r/%s topics=%s search_text_len=%s reembed=%s", name, topics_list, len(composite_clipped), reembed)


def main():
    ap = argparse.ArgumentParser(description="Backfill topics and FTS (and optionally re-embed) for existing subreddits")
    ap.add_argument("--dry-run", action="store_true", help="Do not write to DB")
    ap.add_argument("--limit", type=int, default=0, help="Max subreddits to process (0 = all)")
    ap.add_argument("--reembed", action="store_true", help="Re-compute embeddings from combined text (uses OpenAI)")
    args = ap.parse_args()

    with psycopg.connect(DATABASE_URL, row_factory=dict_row, autocommit=False) as conn:
        ensure_migration_001_columns(conn)
        subs = fetch_subreddits_with_rules_and_flairs(conn)
        if args.limit:
            subs = subs[: args.limit]
        logger.info("Processing %s subreddits (dry_run=%s, reembed=%s)", len(subs), args.dry_run, args.reembed)
        for i, sub in enumerate(subs):
            try:
                backfill_one(conn, sub, dry_run=args.dry_run, reembed=args.reembed)
            except Exception as e:
                logger.exception("r/%s failed: %s", sub.get("name"), e)
            if not args.dry_run and (i + 1) % 50 == 0:
                conn.commit()
        if not args.dry_run:
            conn.commit()
    logger.info("Done.")


if __name__ == "__main__":
    main()
