# AI Reddit Post Analyzer

This project is an AI-powered Reddit post analyzer that helps users identify the best subreddits for their posts. It uses OpenAI for natural language processing, ChromaDB for data storage, and a FastAPI backend to serve the analysis. The frontend is built with React and TailwindCSS.

---

## Features

- Analyze Reddit post titles and bodies to find the most relevant subreddits.
- Analyze uploaded images to determine image information to find the most relevant subreddits.
- Display subreddit rules and potential AI-generated content warnings.
- Backend powered by FastAPI, Postgres with pgvector to store embeddings 
- Frontend built with React and TailwindCSS.
- PRAW (Python Reddit API Wrapper) to fetch subreddit rules and metadata. 

---

## Prerequisites

Before starting, ensure you have the following installed:

- Docker 
- Python 3.8+
- Node.js 16+
- npm or yarn
- Edit `sample.env` file and `opt/findasubreddit/deploy/sample.backend.env` with the required keys and values. TO-DO: 

---

## Running the Project

**For step-by-step local setup and testing**, see **[docs/LOCAL_TESTING.md](docs/LOCAL_TESTING.md)**.

### 1 Use Docker to create the database and ingest subreddits 
Build images (only needed after changing Dockerfile/requirements)
```
docker compose build
```

Start Postgres (pgvector) in the background
```
docker compose up -d
```
Run the ingestion (one-off job)
```
docker compose run --rm ingest
```

#### Stop Docker services
Stop containers but keep data:
```
docker compose stop
```

Stop and remove containers (keep the database volume):
```
docker compose down
```

Nuke everything (containers + data volume):
```
docker compose down -v
```

---

## Project Structure

```
ai_reddit_prototype/
├── .env                     # Environment variables
├── package.json             # Node.js dependencies
├── scripts/                 # Scripts for managing subreddit data
│   └── ingest_reddit_to_postgres.py # Script to fetch subreddit data, analyze using OpenAI and store in Postgres
├── src/                     # Source code
│   ├── api/                 # FastAPI backend
│   │   ├── analyze_post_api.py # API for analyzing Reddit posts
│   │   ├── reddit_post_api.py  # API for Reddit post interactions
│   │   └── auth/            # Reddit auth services - To-Do: Add files for Reddit Auth
│   │       └── reddit_auth.py  # User authentication for OAuth sign-in  
│   ├── components/          # React components
│   │   └─ ui/               # Front-end Reach components 
│   │      ├── accordion.tsx # Expands card sections
│   │      ├── button.tsx    # Card buttons 
│   │      ├── card.tsx      # Card info and layout 
│   │      ├── input.tsx     # Accept input on cards 
│   │      └── textarea.tsx  # Display text on cards 
│   ├── lib/                 # Utility functions
│   ├── styles/              # TailwindCSS styles
│   ├── App.tsx              # Main React app
│   ├── RedditAnalyzer.tsx   # Reddit post analyzer component
│   └── main.tsx             # Application entry point
├── tailwind.config.js       # TailwindCSS configuration
├── tsconfig.json            # TypeScript configuration
├── vite.config.ts           # Vite configuration
├── index.css                # Global CSS styles
└── index.html 
```

---

## Scripts

### Fetch Subreddits to Postgres
This script defaults to fetch the top 1000 subreddits or, you can use the `TOP_N` environment variable to override. 
Run the script to fetch subreddit data and store it in Postgres.
```bash
python scripts/ingest_reddit_to_postgres.py
```

---

## Topic tags and hybrid search

- **Topic tags**: Each subreddit gets a `topics` array (rule-based + optional LLM). Set `USE_LLM_TOPICS=true` to enrich with LLM.
- **Hybrid retrieval**: Search combines **lexical** (Postgres FTS on `embedding.search_tsv`) and **semantic** (pgvector on `embedding.embedding`). Combined text indexed is description + rules + wiki + flair (subreddit name is in the text but can be downweighted via config).

### Tuning hybrid weights

Weights are env vars; they should sum to 1:

- `HYBRID_LEXICAL_WEIGHT` (default `0.35`) – weight for FTS score
- `HYBRID_SEMANTIC_WEIGHT` (default `0.65`) – weight for vector similarity

Example: more keyword-heavy search (exact phrases matter):

```bash
export HYBRID_LEXICAL_WEIGHT=0.5
export HYBRID_SEMANTIC_WEIGHT=0.5
```

More semantic (meaning over exact words):

```bash
export HYBRID_LEXICAL_WEIGHT=0.25
export HYBRID_SEMANTIC_WEIGHT=0.75
```

### Example SQL for hybrid ranking

You can run a hybrid-style query directly in SQL (e.g. in `psql`) like this:

```sql
-- Replace :query_text and :query_vec (as string) with your values
WITH q AS (
  SELECT plainto_tsquery('english', 'python programming help') AS fts_q
),
lex AS (
  SELECT e.subreddit_id,
         ts_rank_cd(e.search_tsv, (SELECT fts_q FROM q)) AS score
  FROM embedding e, q
  WHERE e.search_tsv IS NOT NULL AND e.search_tsv @@ (SELECT fts_q FROM q)
  ORDER BY score DESC
  LIMIT 100
),
sem AS (
  SELECT e.subreddit_id,
         1 - (e.embedding <=> '[0.1, -0.02, ...]'::vector) AS score
  FROM embedding e
  ORDER BY e.embedding <=> '[0.1, -0.02, ...]'::vector
  LIMIT 100
)
SELECT s.name,
       0.35 * COALESCE(l.score / NULLIF((SELECT max(score) FROM lex), 0), 0) +
       0.65 * COALESCE(ss.score, 0) AS combined
FROM subreddit s
LEFT JOIN lex l ON l.subreddit_id = s.id
LEFT JOIN sem ss ON ss.subreddit_id = s.id
WHERE l.subreddit_id IS NOT NULL OR ss.subreddit_id IS NOT NULL
ORDER BY combined DESC NULLS LAST, s.name
LIMIT 20;
```

The API does the same merge in Python (normalize FTS by max rank, then `lex_weight * fts_norm + sem_weight * vec_sim`) with deterministic tie-break by `s.name`.

---

## Migrations and backfill

After adding topic tags and FTS columns:

1. **Run migration** (adds `subreddit.topics`, `embedding.search_text`, `embedding.search_tsv`, GIN index):

   ```bash
   psql "$DATABASE_URL" -f opt/findasubreddit/backend/scripts/migrations/001_topics_and_fts.sql
   ```

2. **Backfill existing rows** (from backend directory):

   ```bash
   cd opt/findasubreddit/backend
   python scripts/backfill_topics_and_fts.py [--dry-run] [--reembed]
   ```

See `opt/findasubreddit/backend/scripts/migrations/README.md` for full commands (local and production).

---

## License

This project is licensed under the MIT License.