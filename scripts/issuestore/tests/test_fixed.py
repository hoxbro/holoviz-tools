"""Tests for PR reference parsing and the already-fixed detection logic.

These exercise pure functions plus ``find_fixed`` against an in-memory fake
collection, so they need neither the GPU embedding model nor GitHub access.
"""

from __future__ import annotations

import os

# config.py resolves the target repo at import time and asserts it is a known
# holoviz repo; pin one before importing anything from the package.
os.environ.setdefault("ISSUE_REPO", "holoviz/holoviews")

import numpy as np
from issuestore.analysis.fixed import (
    build_reference_index,
    find_fixed,
    merge_candidates,
    semantic_candidates,
)
from issuestore.ingest.build_db import build_metadata, parse_closes


def test_parse_closes_splits_keywords_from_mentions():
    closes, mentions = parse_closes("Fixes #12, closes #34. Related to #56 and #12")
    assert closes == {12, 34}
    # #12 is a close, so it must not also appear as a weaker mention.
    assert mentions == {56}


def test_parse_closes_keyword_variants_and_empty():
    closes, mentions = parse_closes("resolved #1 fix #2 close #3 fixed #4")
    assert closes == {1, 2, 3, 4}
    assert mentions == set()
    assert parse_closes("") == (set(), set())
    assert parse_closes("no refs here") == (set(), set())


def test_build_metadata_marks_pr_merge_and_refs():
    pr = {
        "number": 100,
        "title": "Fix legend",
        "body": "Fixes #1. See #9.",
        "state": "closed",
        "pull_request": {"merged_at": "2024-01-02T00:00:00Z"},
    }
    meta = build_metadata(pr, n_comments=0, kind="pr")
    assert meta["kind"] == "pr"
    assert meta["merged"] is True
    assert meta["merged_at"] == "2024-01-02T00:00:00Z"
    assert meta["closes"] == "1"
    assert meta["mentions"] == "9"


def test_build_metadata_unmerged_pr():
    pr = {"number": 101, "title": "wip", "body": "", "pull_request": {"merged_at": None}}
    meta = build_metadata(pr, n_comments=0, kind="pr")
    assert meta["merged"] is False
    assert meta["merged_at"] == ""


def test_build_reference_index_groups_by_issue():
    pr_metas = [
        {"number": 100, "title": "a", "html_url": "u100", "closes": "1", "mentions": "2"},
        {"number": 101, "title": "b", "html_url": "u101", "closes": "", "mentions": "1"},
    ]
    index = build_reference_index(pr_metas)
    assert {c["pr"] for c in index[1]} == {100, 101}
    reasons = {c["pr"]: c["reason"] for c in index[1]}
    assert reasons == {100: "closes", 101: "mentions"}
    assert [c["pr"] for c in index[2]] == [100]


def test_semantic_candidates_threshold():
    issue_embs = np.array([[1.0, 0.0]], dtype=np.float32)
    pr_embs = np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
    pr_metas = [
        {"number": 100, "title": "match", "html_url": "u100"},
        {"number": 101, "title": "orthogonal", "html_url": "u101"},
    ]
    out = semantic_candidates(issue_embs, [1], pr_embs, pr_metas, threshold=0.5)
    assert [c["pr"] for c in out[1]] == [100]
    assert out[1][0]["reason"] == "semantic"
    assert out[1][0]["similarity"] == 1.0


def test_merge_candidates_prefers_strong_reason_and_keeps_similarity():
    ref = [
        {
            "pr": 100,
            "title": "a",
            "url": "u",
            "merged_at": "",
            "reason": "closes",
            "similarity": None,
        }
    ]
    sem = [
        {
            "pr": 100,
            "title": "a",
            "url": "u",
            "merged_at": "",
            "reason": "semantic",
            "similarity": 0.91,
        }
    ]
    merged = merge_candidates(ref, sem)
    assert len(merged) == 1
    assert merged[0]["reason"] == "closes"  # strong reason wins the dedupe
    assert merged[0]["similarity"] == 0.91  # ...but the score is carried over


class FakeCollection:
    """Minimal Chroma stand-in: records tagged with kind, is_open, merged."""

    def __init__(self, records):
        self._records = records

    def get(self, ids=None, where=None, include=None):
        recs = self._records
        if ids is not None:
            recs = [r for r in recs if str(r["meta"]["number"]) in set(ids)]
        elif where is not None:
            for clause in where.get("$and", [where]):
                ((key, val),) = clause.items()
                recs = [r for r in recs if r["meta"].get(key) == val]
        # ChromaDB returns embeddings as a numpy array (not a list); mirror that
        # so callers are exercised the same way the real client behaves.
        return {
            "ids": [str(r["meta"]["number"]) for r in recs],
            "embeddings": np.array([r["emb"] for r in recs], dtype=np.float32),
            "metadatas": [r["meta"] for r in recs],
        }


def _rec(number, emb, **meta):
    base = {"number": number, "title": f"#{number}", "html_url": f"u{number}"}
    base.update(meta)
    return {"emb": emb, "meta": base}


def test_find_fixed_combines_reference_and_semantic():
    records = [
        # open issues
        _rec(1, [1.0, 0.0], is_open=True, kind="issue"),
        _rec(2, [0.0, 1.0], is_open=True, kind="issue"),
        _rec(3, [0.7, 0.7], is_open=True, kind="issue"),  # no PR -> excluded
        # merged PRs
        _rec(
            100, [0.2, 0.0], is_open=False, kind="pr", merged=True, closes="1", mentions=""
        ),  # reference to #1
        _rec(
            101, [0.0, 1.0], is_open=False, kind="pr", merged=True, closes="", mentions=""
        ),  # semantic match to #2
    ]
    results = find_fixed(FakeCollection(records), threshold=0.9)

    by_num = {r["number"]: r for r in results}
    assert set(by_num) == {1, 2}  # #3 has no candidate

    # #1 linked by a closing keyword despite low embedding similarity.
    assert by_num[1]["candidates"][0]["reason"] == "closes"
    assert by_num[1]["candidates"][0]["pr"] == 100

    # #2 surfaced purely semantically.
    assert by_num[2]["candidates"][0]["reason"] == "semantic"
    assert by_num[2]["candidates"][0]["pr"] == 101

    # A confirmed "closes" link ranks ahead of a semantic-only one.
    assert results[0]["number"] == 1


def test_find_fixed_single_issue():
    records = [
        _rec(1, [1.0, 0.0], is_open=True, kind="issue"),
        _rec(2, [0.0, 1.0], is_open=True, kind="issue"),
        _rec(100, [0.0, 0.0], is_open=False, kind="pr", merged=True, closes="1", mentions=""),
    ]
    results = find_fixed(FakeCollection(records), threshold=0.9, issue_number=1)
    assert [r["number"] for r in results] == [1]
