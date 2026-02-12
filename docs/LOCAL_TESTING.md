# Local Testing Guide

Steps to run and test the **Find a Subreddit** project on your machine.

---

## Prerequisites

- **Docker** (for Postgres with pgvector)
- **Python 3.8+** (3.11 recommended)
- **Node.js 16+** and npm
- **Reddit API credentials** (create an app at [reddit.com/prefs/apps](https://www.reddit.com/prefs/apps))
- **OpenAI API key** (for embeddings and optional LLM features)

---

## 1. Clone and environment setup

```bash
cd /path/to/find-a-subreddit
```

Create your environment file from the sample:

```bash
cp sample.env .env
```

Edit `.env` and set at least:

| Variable | Description |
|----------|-------------|
| `REDDIT_CLIENT_ID` | From your Reddit app |
| `REDDIT_CLIENT_SECRET` | From your Reddit app |
| `REDDIT_USER_AGENT` | e.g. `YourApp/0.1 by your_reddit_username` |
| `REDDIT_USERNAME` | Your Reddit username |
| `REDDIT_PASSWORD` | Your Reddit password |
| `REDDIT_REDIRECT_URI` | `http://localhost:8001/api/auth/reddit/callback` for local |
| `OPENAI_API_KEY` | Your OpenAI API key |
| `JWT_SECRET` | Any secret string (e.g. `supersecret123`) |
| `DATABASE_URL` | See step 2 (must match Postgres from Docker) |

For local CORS and redirects, add (if not present):

```bash
FRONTEND_ORIGIN=http://localhost:5173
FRONTEND_DOMAIN=http://localhost:5173
```

---

## 2. Start Postgres (Docker)

From the **project root**:

```bash
docker compose up -d db
```

Wait until the DB is healthy (about 10–30 seconds). Default DB URL for the `db` service:

```text
postgresql://postgres:postgres@localhost:5432/reddit_vibes
```

Set this in your `.env`:

```bash
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/reddit_vibes
```

---

## 3. Run database migrations (optional but recommended)

If you use topic tags and hybrid search (FTS + vector):

```bash
cd opt/findasubreddit/backend
export $(grep -v '^#' ../../.env | xargs)   # load .env from repo root if you keep it there
# Or: copy .env into opt/findasubreddit/backend or set DATABASE_URL manually

psql "$DATABASE_URL" -f scripts/migrations/001_topics_and_fts.sql
```

Backfill existing rows (after first ingest):

```bash
python scripts/backfill_topics_and_fts.py --dry-run   # then without --dry-run
```

---

## 4. Ingest subreddits (one-off)

From the **backend** directory, with `.env` (or `DATABASE_URL` and Reddit/OpenAI vars) available:

```bash
cd opt/findasubreddit/backend
pip install -r requirements.txt
# Load env: export $(grep -v '^#' ../../.env | xargs)  if .env is at repo root
python scripts/ingest_reddit_to_postgres.py
```

Optional: set `TOP_N=100` (or another number) to limit how many subreddits are fetched.

---

## 5. Run the backend API

From the **backend** directory:

```bash
cd opt/findasubreddit/backend
# Ensure .env is loaded (e.g. export $(grep -v '^#' ../../.env | xargs))
uvicorn src.api.analyze_post_api:app --host 0.0.0.0 --port 8001 --reload
```

The API will be at **http://localhost:8001**.

Quick checks:

- **http://localhost:8001/health** – health check (database, OpenAI, etc.)
- **http://localhost:8001/test** – simple test route

---

## 6. Run the frontend

In a **new terminal**:

```bash
cd frontend
npm install
npm run dev
```

The app will be at **http://localhost:5173**. It uses `VITE_API_URL=http://localhost:8001` from `frontend/.env.development` by default.

---

## 7. Run backend tests

From the **backend** directory:

```bash
cd opt/findasubreddit/backend
pip install -r requirements.txt pytest
python -m pytest src/api/tests/ -v
```

Run specific test files:

```bash
python -m pytest src/api/tests/test_search_pipeline.py -v
python -m pytest src/api/tests/test_hybrid_search_and_topics.py -v
```

These tests focus on search pipeline logic (embed text, topic filter, rerank, params) and do not require a live database or OpenAI key.

---

## 8. Optional checks

- **Frontend build** (from `frontend/`): `npm run build`
- **Backend script test** (ingest-related):  
  `python scripts/test_top_sub_summaries.py` (requires Reddit env vars; see script docstring)

---

## Summary: minimal flow

```bash
# Terminal 1 – Postgres
docker compose up -d db

# Terminal 2 – Backend (after: cp sample.env .env and edit .env)
cd opt/findasubreddit/backend
pip install -r requirements.txt
# Optional: migrations, then ingest
uvicorn src.api.analyze_post_api:app --host 0.0.0.0 --port 8001 --reload

# Terminal 3 – Frontend
cd frontend && npm install && npm run dev
```

Then open **http://localhost:5173** and use the analyzer; API at **http://localhost:8001**.

---

## Troubleshooting

| Issue | What to check |
|-------|----------------|
| `DATABASE_URL` / connection errors | Postgres: `docker compose up -d db`; use `postgresql://postgres:postgres@localhost:5432/reddit_vibes`. |
| CORS or redirect errors | `FRONTEND_ORIGIN` and `FRONTEND_DOMAIN` set to `http://localhost:5173`; backend running on 8001. |
| Reddit OAuth redirect mismatch | In Reddit app settings, redirect URI must be exactly `http://localhost:8001/api/auth/reddit/callback`. |
| `VITE_API_URL` / frontend can’t reach API | In `frontend/.env.development`: `VITE_API_URL=http://localhost:8001`. |
| Import errors when running API or tests | Run commands from `opt/findasubreddit/backend` so `src.api` resolves. |

For production env vars and Reddit/OpenAI setup, see `opt/findasubreddit/backend/ENVIRONMENT_CONFIG.md` and the main `README.md`.
