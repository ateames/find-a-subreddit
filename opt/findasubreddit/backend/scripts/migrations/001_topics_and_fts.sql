-- Migration 001: Topic tags per subreddit + FTS (tsvector) for hybrid search
-- Run with: psql $DATABASE_URL -f opt/findasubreddit/backend/scripts/migrations/001_topics_and_fts.sql
-- Idempotent: safe to run multiple times (IF NOT EXISTS / DO blocks).

-- 1) Add topics array to subreddit (nullable for backfill)
ALTER TABLE subreddit
  ADD COLUMN IF NOT EXISTS topics TEXT[];

COMMENT ON COLUMN subreddit.topics IS 'Topic tags from rule-based + optional LLM taxonomy';

-- 2) Add search text and tsvector to embedding (same combined text used for vector)
ALTER TABLE embedding
  ADD COLUMN IF NOT EXISTS search_text TEXT,
  ADD COLUMN IF NOT EXISTS search_tsv TSVECTOR;

COMMENT ON COLUMN embedding.search_text IS 'Combined text: description + rules + wiki + flair (source for embedding and FTS)';
COMMENT ON COLUMN embedding.search_tsv IS 'FTS tsvector over search_text for lexical search';

-- 3) GIN index for full-text search on search_tsv
CREATE INDEX IF NOT EXISTS embedding_search_tsv_gin
  ON embedding USING GIN (search_tsv);

-- 4) Optional: default text search config (english); used when updating search_tsv
-- No table change; application will use to_tsvector('english', search_text) when populating search_tsv.
