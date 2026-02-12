"""
Tests for search pipeline: (1) hard topic filter before ranking,
(2) never embed negative terms, (3) rerank top 50 with constraints.
Run from backend: python -m pytest src/api/tests/test_search_pipeline.py -v
"""

import os
import sys


def _backend_path():
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def test_embed_text_contains_no_exclude_terms():
    """FAIL if any exclude term or exclude_topic appears in the text that is embedded."""
    backend = _backend_path()
    if backend not in sys.path:
        sys.path.insert(0, backend)
    from src.api.analyze_post_api import build_embed_text_positive_only

    # Positive content
    title = "Looking for cats and dogs"
    body = "I want advice about pets"
    context = "Include cats and dogs"
    link = None
    include_terms = ["kittens"]

    # Exclude terms and topics must NOT appear in output
    exclude_terms = ["dogs", "reptiles"]
    exclude_topics = ["humor", "news"]

    embed_text = build_embed_text_positive_only(
        title=title,
        body=body,
        context=context,
        link=link,
        include_terms=include_terms,
        exclude_terms=exclude_terms,
        exclude_topics=exclude_topics,
    )

    embed_lower = embed_text.lower()
    for bad in exclude_terms + exclude_topics:
        assert bad.lower() not in embed_lower, (
            f"Exclude term or topic '{bad}' must NOT appear in embed text. Got: {embed_text!r}"
        )


def test_embed_text_positive_only_uses_include():
    """Embed text should contain include_terms."""
    backend = _backend_path()
    if backend not in sys.path:
        sys.path.insert(0, backend)
    from src.api.analyze_post_api import build_embed_text_positive_only

    embed_text = build_embed_text_positive_only(
        title="Hi",
        body="",
        context="",
        link=None,
        include_terms=["python", "programming"],
        exclude_terms=[],
        exclude_topics=[],
    )
    assert "python" in embed_text.lower()
    assert "programming" in embed_text.lower()


def test_topic_filter_must_topics_overlap():
    """must_topics: keep only if subreddit.topics overlaps (AND)."""
    backend = _backend_path()
    if backend not in sys.path:
        sys.path.insert(0, backend)
    from src.api.analyze_post_api import _apply_topic_filter

    candidates = [
        {"id": "1", "name": "A", "topics": ["technology", "gaming"], "similarity": 0.9},
        {"id": "2", "name": "B", "topics": ["cooking"], "similarity": 0.8},
        {"id": "3", "name": "C", "topics": ["gaming", "humor"], "similarity": 0.7},
    ]
    filtered = _apply_topic_filter(candidates, must_topics=["gaming"], exclude_topics=[])
    assert len(filtered) == 2
    names = [r["name"] for r in filtered]
    assert "A" in names and "C" in names and "B" not in names


def test_topic_filter_exclude_topics_hard_not():
    """exclude_topics: drop any sub whose topics overlap exclude_topics."""
    backend = _backend_path()
    if backend not in sys.path:
        sys.path.insert(0, backend)
    from src.api.analyze_post_api import _apply_topic_filter

    candidates = [
        {"id": "1", "name": "A", "topics": ["technology"], "similarity": 0.9},
        {"id": "2", "name": "B", "topics": ["humor", "news"], "similarity": 0.8},
        {"id": "3", "name": "C", "topics": ["technology", "humor"], "similarity": 0.7},
    ]
    filtered = _apply_topic_filter(candidates, must_topics=[], exclude_topics=["humor"])
    assert len(filtered) == 1
    assert filtered[0]["name"] == "A"


def test_topic_filter_combined():
    """must_topics AND exclude_topics together."""
    backend = _backend_path()
    if backend not in sys.path:
        sys.path.insert(0, backend)
    from src.api.analyze_post_api import _apply_topic_filter

    candidates = [
        {"id": "1", "name": "A", "topics": ["gaming", "technology"], "similarity": 0.9},
        {"id": "2", "name": "B", "topics": ["gaming", "humor"], "similarity": 0.8},
        {"id": "3", "name": "C", "topics": ["gaming"], "similarity": 0.7},
    ]
    filtered = _apply_topic_filter(
        candidates, must_topics=["gaming"], exclude_topics=["humor"]
    )
    assert len(filtered) == 2
    names = [r["name"] for r in filtered]
    assert "A" in names and "C" in names and "B" not in names


def test_rerank_same_items_no_resurrection():
    """Rerank returns exactly the same set of items (no new ids)."""
    backend = _backend_path()
    if backend not in sys.path:
        sys.path.insert(0, backend)
    from src.api.analyze_post_api import _rerank_with_constraints

    candidates = [
        {"id": "1", "name": "SubA", "topics": ["technology"], "similarity": 0.7, "public_description": "tech"},
        {"id": "2", "name": "SubB", "topics": ["gaming"], "similarity": 0.9, "public_description": "games"},
    ]
    reranked = _rerank_with_constraints(
        candidates,
        must_topics=["technology"],
        exclude_topics=[],
        include_terms=[],
        exclude_terms=[],
    )
    assert len(reranked) == len(candidates)
    assert set(r["id"] for r in reranked) == set(r["id"] for r in candidates)


def test_rerank_ordering_constraint_aware():
    """Rerank boosts must_topics overlap (technology sub should come first)."""
    backend = _backend_path()
    if backend not in sys.path:
        sys.path.insert(0, backend)
    from src.api.analyze_post_api import _rerank_with_constraints

    candidates = [
        {"id": "1", "name": "Other", "topics": ["cooking"], "similarity": 0.9, "public_description": ""},
        {"id": "2", "name": "Tech", "topics": ["technology"], "similarity": 0.8, "public_description": ""},
    ]
    reranked = _rerank_with_constraints(
        candidates,
        must_topics=["technology"],
        exclude_topics=[],
        include_terms=[],
        exclude_terms=[],
    )
    # Tech should be boosted above Other despite lower base similarity
    assert reranked[0]["id"] == "2" and reranked[0]["name"] == "Tech"


def test_parse_list_param():
    """_parse_list_param normalizes to lower and splits on comma/space."""
    backend = _backend_path()
    if backend not in sys.path:
        sys.path.insert(0, backend)
    from src.api.analyze_post_api import _parse_list_param

    assert _parse_list_param("") == []
    assert _parse_list_param(None) == []
    assert _parse_list_param("  a , b  ") == ["a", "b"]
    assert _parse_list_param("Gaming, Technology") == ["gaming", "technology"]
