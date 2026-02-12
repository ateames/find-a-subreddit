"""
Stubs for hybrid retrieval and topic tags. Run with pytest if available:
  cd opt/findasubreddit/backend && python -m pytest src/api/tests/test_hybrid_search_and_topics.py -v
"""

import os
import sys


def test_topic_keywords_cover_taxonomy():
    """Topic taxonomy and keyword map are consistent."""
    _add_backend_path()
    from scripts.ingest_reddit_to_postgres import TOPIC_TAXONOMY, TOPIC_KEYWORDS
    for tag in TOPIC_TAXONOMY:
        assert tag in TOPIC_KEYWORDS, f"Topic {tag} missing from TOPIC_KEYWORDS"
    for tag in TOPIC_KEYWORDS:
        assert tag in TOPIC_TAXONOMY, f"TOPIC_KEYWORDS has extra tag {tag}"


def test_compute_topics_rule_based_returns_list():
    """Rule-based topic extraction returns a non-empty list."""
    _add_backend_path()
    from scripts.ingest_reddit_to_postgres import compute_topics_rule_based
    topics = compute_topics_rule_based(
        "Python",
        "A subreddit for discussion about the Python programming language.",
        "No spam.",
        ["Question", "Discussion"],
    )
    assert isinstance(topics, list)
    assert len(topics) >= 1
    assert "programming" in topics or "discussion" in topics


def test_build_composite_text_includes_flair_and_wiki():
    """Combined text includes wiki and flair sections."""
    _add_backend_path()
    from scripts.ingest_reddit_to_postgres import build_composite_text
    out = build_composite_text(
        "TestSub",
        "Description here",
        "Submit rules",
        "Rule one",
        wiki_text="Wiki content",
        flair_text="Flair1 Flair2",
    )
    assert "Wiki: Wiki content" in out
    assert "Flair: Flair1 Flair2" in out
    assert "Description: Description here" in out
    assert "Rules: Rule one" in out


def test_hybrid_weights_sane():
    """Default hybrid weights are in [0,1]."""
    _add_backend_path()
    from src.api.analyze_post_api import HYBRID_LEXICAL_WEIGHT, HYBRID_SEMANTIC_WEIGHT
    assert 0 <= HYBRID_LEXICAL_WEIGHT <= 1
    assert 0 <= HYBRID_SEMANTIC_WEIGHT <= 1


def _add_backend_path():
    backend = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    if backend not in sys.path:
        sys.path.insert(0, backend)
