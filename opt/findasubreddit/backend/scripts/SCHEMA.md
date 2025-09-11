## Tables

### `subreddit`
Canonical row per subreddit. Primary key is the Reddit fullname `t5_xxx`.

| Column                  | Type         | Notes |
|-------------------------|--------------|------|
| `id` (PK)               | TEXT         | Fullname `t5_<id36>` |
| `id36` (UNIQUE)         | TEXT         | Base36 id |
| `name` (UNIQUE)         | TEXT         | Display name (e.g., `AskReddit`) |
| `title`                 | TEXT         | Subreddit title |
| `public_description`    | TEXT         | Public description |
| `description_md`        | TEXT         | Sidebar/body markdown |
| `description_hash`      | TEXT         | SHA-256 of `description_md` |
| `over18`                | BOOLEAN      | NSFW (never stored; NSFW are skipped upstream) |
| `quarantined`           | BOOLEAN      | Quarantine status |
| `subreddit_type`        | TEXT         | `public` / `restricted` / `private` |
| `submission_type`       | TEXT         | `self` or `any` |
| `allow_images`          | BOOLEAN      | Images allowed |
| `allow_videos`          | BOOLEAN      | Videos allowed |
| `allow_polls`           | BOOLEAN      | Polls allowed |
| `suggested_comment_sort`| TEXT         | Reddit’s suggested sort |
| `subscribers`           | INTEGER      | Subscriber count snapshot |
| `created_utc`           | TIMESTAMPTZ  | Sub creation time |
| `last_crawled_at`       | TIMESTAMPTZ  | Ingestion timestamp |
| `rules_hash`            | TEXT         | SHA-256 of concatenated rule descriptions |

---

### `rules`
All rules for a subreddit, replaced on each crawl.

| Column                  | Type        | Notes |
|-------------------------|-------------|------|
| `subreddit_id` (PK, FK) | TEXT        | → `subreddit(id)` ON DELETE CASCADE |
| `idx` (PK)              | INTEGER     | 0-based ordering |
| `short_name`            | TEXT        | Rule label/kind |
| `description`           | TEXT        | Rule body |

---

### `link_flair`
User-selectable link flairs (no mod context). Fully refreshed each run.

| Column                    | Type        | Notes |
|---------------------------|-------------|------|
| `subreddit_id` (PK, FK)   | TEXT        | → `subreddit(id)` ON DELETE CASCADE |
| `flair_id` (PK)           | TEXT        | Flair template id |
| `flair_text`              | TEXT        | Human label |
| `mod_only`                | BOOLEAN     | Mod-only template |
| `text_editable`           | BOOLEAN     | User can edit text |

---

### `vibe`
Heuristic + LLM characterization of posting vibe; one row per subreddit.

| Column             | Type        | Notes |
|--------------------|-------------|------|
| `subreddit_id` (PK, FK) | TEXT   | → `subreddit(id)` ON DELETE CASCADE |
| `strictness`       | SMALLINT    | 0–5 clamp |
| `beginner`         | SMALLINT    | 0–5 clamp |
| `meme_tolerance`   | SMALLINT    | 0–5 clamp |
| `self_promo`       | SMALLINT    | 0–5 clamp |
| `content_type`     | TEXT        | `text` \| `images/oc` \| `links/news` \| `mixed` |
| `seriousness`      | SMALLINT    | 0–5 clamp |
| `summary`          | TEXT        | ≤15-word vibe sentence |
| `scores_source`    | TEXT        | `heuristic+llm` or `heuristic_fallback` |
| `prompt_version`   | TEXT        | e.g., `llm_summary_v1` |
| `model_name`       | TEXT        | LLM used (or `none` on fallback) |
| `computed_at`      | TIMESTAMPTZ | When computed |

---

### `embedding` (pgvector)
Single vector per subreddit for similarity search.

| Column                   | Type               | Notes |
|--------------------------|--------------------|------|
| `subreddit_id` (PK, FK)  | TEXT               | → `subreddit(id)` ON DELETE CASCADE |
| `embedding`              | `vector(EMBED_DIM)`| `EMBED_DIM` from env (default 1536) |
| `input_hash`             | TEXT               | SHA-256 of composite input text |
| `model_name`             | TEXT               | Embedding model id (e.g., `text-embedding-3-small`) |
| `updated_at`             | TIMESTAMPTZ        | Last write |
