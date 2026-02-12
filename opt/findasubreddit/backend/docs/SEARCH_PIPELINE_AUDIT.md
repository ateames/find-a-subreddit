# Search pipeline audit – requirements vs implementation

## Deliverables – relevant files and functions

- **1) Hard topic filtering before final ranking**
  - **File:** `opt/findasubreddit/backend/src/api/analyze_post_api.py`
  - **Functions/lines:** `_apply_topic_filter(candidates, must_topics, exclude_topics)` — implements AND/overlap for must_topics and NOT for exclude_topics. In `analyze_post`: after `_query_hybrid(...)` → `filtered = _apply_topic_filter(candidates, ...)` → `top50 = filtered[:RERANK_TOP_N]` → `_rerank_with_constraints(...)`. Filtering happens before score combine (combine is inside _query_hybrid) and before truncating to top N for rerank.
- **2) Never embed negative terms**
  - **File:** `opt/findasubreddit/backend/src/api/analyze_post_api.py`
  - **Embed construction:** `build_embed_text_positive_only(title, body, context, link, include_terms, exclude_terms, exclude_topics)` — only this output is passed to `get_embedding(embed_text)`. Exclude terms/topics are stripped (case-insensitive) from the string before embedding.
  - **Test:** `src/api/tests/test_search_pipeline.py::test_embed_text_contains_no_exclude_terms` — fails if any exclude term or exclude_topic appears in embed text.
- **3) Rerank top 50 with constraints**
  - **File:** `opt/findasubreddit/backend/src/api/analyze_post_api.py`
  - **Function:** `_rerank_with_constraints(candidates, must_topics, exclude_topics, include_terms, exclude_terms)` — inputs: list of candidate dicts; output: same list re-ordered. Used as: `top50 = filtered[:RERANK_TOP_N]`; `reranked = _rerank_with_constraints(top50, ...)`; `all_results = reranked + filtered[RERANK_TOP_N:]`. Rerank cannot resurrect filtered-out items (it only reorders the given list).
  - **Tests:** `test_rerank_same_items_no_resurrection`, `test_rerank_ordering_constraint_aware`.

---

## 1) Hard topic filtering BEFORE final ranking

**Requirement:** `must_topics` AND/overlap; `exclude_topics` hard NOT; filtering before combining lexical+vector and before top N.

**Relevant files and functions:**
- `opt/findasubreddit/backend/src/api/analyze_post_api.py`
  - **Lines:** `_apply_topic_filter()` (implementation); in `analyze_post()`: parse Form params → `_query_hybrid()` → **`_apply_topic_filter(candidates, must_topics_list, exclude_topics_list)`** → `filtered[:RERANK_TOP_N]` → `_rerank_with_constraints(...)`.

**Filter logic (AND/overlap and NOT):**
- **must_topics:** Keep row iff `not must_topics_list` or `(set(subreddit.topics) & set(must_topics_list))` (at least one overlap).
- **exclude_topics:** Keep row iff `not exclude_topics_list` or `not (set(subreddit.topics) & set(exclude_topics_list))` (no overlap).

**Equivalent SQL (if we pushed filter into Postgres):**
```sql
WHERE (cardinality(%(must_topics)s) = 0 OR (s.topics && %(must_topics)s))
  AND (cardinality(%(exclude_topics)s) = 0 OR NOT (s.topics && %(exclude_topics)s))
```
Current implementation applies this in Python over the hybrid result set (`_apply_topic_filter`), so filtering happens **after** retrieval but **before** taking top 50 and **before** rerank.

---

## 2) Never embed negative terms

**Requirement:** Embedding input only from positive signals; exclude terms and exclude_topics must NOT appear in embedded text; test that fails if any exclude appears.

**Relevant files and functions:**
- `opt/findasubreddit/backend/src/api/analyze_post_api.py`
  - **Embed string construction:** `build_embed_text_positive_only(title, body, context, link, include_terms, exclude_terms, exclude_topics)`. Builds from: `title`, `body`, `context`, `link`, `include_terms` only. Then strips (case-insensitive) every string in `exclude_terms` and `exclude_topics` from that text. No other variables are used for the embedding input.
  - **Single embedding call:** `post_embedding = get_embedding(embed_text)` — the only argument is `embed_text` from the function above.
- **FTS:** `_query_hybrid(..., query_text=embed_text, ...)` so lexical branch also uses the same positive-only string.

**Proof (variables used for embed input):** Only `embed_text` is passed to `get_embedding()`. `embed_text` is computed solely from `title`, `body`, `context`, `link`, `include_terms`, with `exclude_terms` and `exclude_topics` removed (so they never appear in the string).

**Test:** `src/api/tests/test_search_pipeline.py::test_embed_text_contains_no_exclude_terms` — asserts that for non-empty `exclude_terms` and `exclude_topics`, the returned string does not contain any of them (substring, case-insensitive). Fails if any exclude appears.

---

## 3) Rerank top 50 with constraints

**Requirement:** After hybrid + topic filter, take top 50; rerank with constraint-aware scoring; rerank cannot resurrect filtered-out items.

**Relevant files and functions:**
- `opt/findasubreddit/backend/src/api/analyze_post_api.py`
  - **Top 50:** `top50 = filtered[:RERANK_TOP_N]` (default 50). `filtered` is the result of `_apply_topic_filter`; order is hybrid score desc, then name asc.
  - **Rerank function:** `_rerank_with_constraints(candidates, must_topics, exclude_topics, include_terms, exclude_terms)`. **Inputs:** list of candidate dicts (each with `id`, `name`, `topics`, `similarity`, `public_description`). **Output:** same list, re-ordered. Scoring: `base = similarity`; +0.05 per must_topic in sub topics; −0.2 per exclude_topic in sub topics (defensive; should be 0 after filter); +0.02 if any include term in name/desc; −0.1 if any exclude term in name/desc. Sort by (−score, name).
  - **Final ordering:** `all_results = reranked + filtered[RERANK_TOP_N:]`; pagination is over `all_results`. Rerank only reorders the first 50; it does not add items, so filtered-out items cannot reappear.

**Tests:** `test_search_pipeline.py::test_rerank_same_items_no_resurrection`, `test_rerank_ordering_constraint_aware`.

---

## Pipeline sequence (post-patch)

1. **Parse SearchSpec:** Form params → must_topics, exclude_topics, include_terms, exclude_terms (lists).
2. **Build embed text:** embed_text = build_embed_text_positive_only(title, body, context, link, include_terms, exclude_terms, exclude_topics).
3. **Retrieve candidates:** post_embedding = get_embedding(embed_text); candidates = _query_hybrid(conn, embed_text, post_embedding, limit=MAX_CANDIDATE_SUBS).
4. **Hard filter:** filtered = _apply_topic_filter(candidates, must_topics, exclude_topics).
5. **Score combine:** Already done inside _query_hybrid (lexical + semantic combined).
6. **Top 50:** top50 = filtered[:RERANK_TOP_N].
7. **Rerank:** reranked = _rerank_with_constraints(top50, must_topics, exclude_topics, include_terms, exclude_terms).
8. **Final list:** all_results = reranked + filtered[RERANK_TOP_N:].
9. **Top N response:** Paginate all_results; return page slice, has_more, same response shape.

---

## API response shape

Unchanged. `AnalyzePostResponse` and `SubredditMatch` are the same. New optional Form fields: `must_topics`, `exclude_topics`, `include`, `exclude` (all optional; backward compatible).
