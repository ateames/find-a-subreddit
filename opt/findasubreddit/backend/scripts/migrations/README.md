# Migrations and backfill

## Migration 001: Topics and FTS

Adds `subreddit.topics`, `embedding.search_text`, `embedding.search_tsv`, and GIN index for hybrid search.

### Local

```bash
cd opt/findasubreddit/backend
export DATABASE_URL="postgresql://user:pass@localhost:5432/dbname"
psql "$DATABASE_URL" -f scripts/migrations/001_topics_and_fts.sql
```

### Production

```bash
# From repo root or backend, with DATABASE_URL set (e.g. in env or .env)
psql "$DATABASE_URL" -f opt/findasubreddit/backend/scripts/migrations/001_topics_and_fts.sql
```

Or from the backend container:

```bash
psql "$DATABASE_URL" -f /app/scripts/migrations/001_topics_and_fts.sql
```

---

## Backfill (existing rows)

After running migration 001, backfill topics and FTS (and optionally re-embed) for subreddits already in the DB.

### Local

```bash
cd opt/findasubreddit/backend
export DATABASE_URL="postgresql://..."
export OPENAI_API_KEY="sk-..."   # required only if using --reembed
python scripts/backfill_topics_and_fts.py [--dry-run] [--limit N] [--reembed]
```

- `--dry-run`: no DB writes
- `--limit N`: process only first N subreddits
- `--reembed`: re-compute embeddings from combined text (uses OpenAI)

### Production

```bash
cd /path/to/find-a-subreddit/opt/findasubreddit/backend
# Or from container with DATABASE_URL and OPENAI_API_KEY set
python scripts/backfill_topics_and_fts.py --reembed
```

Without `--reembed`, only `topics`, `search_text`, and `search_tsv` are updated (no API calls).
