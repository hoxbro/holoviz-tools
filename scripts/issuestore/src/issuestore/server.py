"""MCP server exposing the holoviews issue vector store as agent tools.

The embedding model and Chroma client are loaded once (lazily on first use) and
kept resident for the life of the process, so repeated tool calls are fast.

Tools:
    - find_similar_issues: issues similar to an existing issue (number/URL) or free text
    - search_issues:   full-text keyword search (every issue mentioning a term)
    - classify_issue:  zero-shot topic (codebase area) ranking for issue text
    - classify_kind:   zero-shot kind (docs, performance, packaging, ...) ranking
    - classify_type:   Bug / Feature / Enhancement, from labeled centroids
    - cluster_themes:  cluster the whole collection into themes
    - get_issue:       raw title/body/labels/comments straight from the local cache

Run standalone for a quick smoke test::

    python mcp_server.py --selftest
"""

from __future__ import annotations

import functools
import os

import numpy as np
from mcp.server.mcpserver import MCPServer

from issuestore.analysis.classify import (
    DEFAULT_TOPIC_CATEGORIES,
    DEFAULT_TYPE_CATEGORIES,
    type_centroids,
)
from issuestore.analysis.cluster import cluster as run_cluster, load_vectors, top_keywords
from issuestore.analysis.query import resolve_seed
from issuestore.analysis.show import _comment_list, issue_path, load_issue
from issuestore.config import REPO, get_collection, get_embedder

mcp = MCPServer(f"issuestore ({REPO})")


@functools.lru_cache(maxsize=1)
def _collection():
    return get_collection()


def _where(state: str):
    if state == "open":
        return {"is_open": True}
    if state == "closed":
        return {"is_open": False}
    return None


@mcp.tool()
def find_similar_issues(
    query: str, n: int = 10, state: str = "all", threshold: float = 0.85
) -> list[dict]:
    """Find issues similar to a query, for duplicate / 'already fixed?' detection.

    Args:
        query: an existing issue number, a GitHub issue URL, or free-text description.
        n: number of results to return.
        state: filter by issue state - "all", "open", or "closed".
        threshold: cosine similarity at/above which a match is flagged as a likely duplicate.

    Returns a list of matches with number, title, state, url, similarity, and
    likely_duplicate flag, sorted by similarity (most similar first).
    """
    coll = _collection()
    emb, seed = resolve_seed(coll, get_embedder(), query)
    res = coll.query(query_embeddings=[emb], n_results=n + 1, where=_where(state))

    out: list[dict] = []
    for meta, dist in zip(res["metadatas"][0], res["distances"][0], strict=False):
        if seed and str(meta["number"]) == seed:
            continue  # drop the seed matching itself
        sim = 1.0 - dist
        out.append(
            {
                "number": meta["number"],
                "title": meta["title"],
                "state": meta["state"],
                "url": meta["html_url"],
                "similarity": round(sim, 4),
                "likely_duplicate": sim >= threshold,
            }
        )
        if len(out) >= n:
            break
    return out


def _contains_where_document(keyword: str, case_insensitive: bool):
    """Build a Chroma `where_document` clause matching `keyword` as a substring.

    Chroma's `$contains` is case-sensitive, so when `case_insensitive` we OR a
    few common case variants (as-is, lower, upper, title) to catch e.g. "polars"
    written as "Polars" or "POLARS".
    """
    if not case_insensitive:
        return {"$contains": keyword}
    variants = {keyword, keyword.lower(), keyword.upper(), keyword.title()}
    clauses = [{"$contains": v} for v in variants]
    if len(clauses) == 1:
        return clauses[0]
    return {"$or": clauses}


@mcp.tool()
def search_issues(
    keyword: str,
    state: str = "all",
    limit: int = 0,
    case_insensitive: bool = True,
) -> list[dict]:
    """Full-text keyword search: list every issue that mentions `keyword`.

    Matches `keyword` as a substring anywhere in the issue's indexed text
    (title, body, and comments), unlike ``find_similar_issues`` which ranks by
    semantic similarity. Use it for concrete terms, e.g. "polars" to get all
    issues that reference Polars.

    Args:
        keyword: the substring to look for (e.g. "polars").
        state: filter by issue state - "all", "open", or "closed".
        limit: maximum number of issues to return; 0 (default) returns all.
        case_insensitive: match common case variants of the keyword (default True).

    Returns a list of matches with number, title, state, url, and labels,
    sorted by issue number (newest first).
    """
    coll = _collection()
    where = _where(state)
    got = coll.get(
        where=where,
        where_document=_contains_where_document(keyword, case_insensitive),
        include=["metadatas"],
    )

    out: list[dict] = []
    for meta in got["metadatas"]:
        out.append(
            {
                "number": meta["number"],
                "title": meta["title"],
                "state": meta["state"],
                "url": meta["html_url"],
                "labels": meta.get("labels", ""),
            }
        )
    out.sort(key=lambda m: m["number"], reverse=True)
    if limit > 0:
        out = out[:limit]
    return out


@mcp.tool()
def get_issue(number: int, include_comments: bool = True) -> dict:
    """Fetch one issue's raw content (title, body, labels, comments) from the cache.

    This reads the downloaded ``issue-<n>.json`` on disk, so it returns the full
    text the other tools omit (they only surface metadata) without any GitHub
    request. Use it to read an issue's actual description before triaging.

    Args:
        number: the issue number to fetch.
        include_comments: also return the (non-empty) comment bodies.

    Returns the raw fields, or ``{"error": ...}`` if the issue is not cached
    (run ``issuestore download`` first).
    """
    if not os.path.exists(issue_path(number)):
        return {"error": f"issue #{number} is not cached; run `issuestore download` first"}

    issue = load_issue(number)
    result = {
        "number": issue.get("number"),
        "title": issue.get("title") or "",
        "state": issue.get("state") or "",
        "labels": [l.get("name", "") for l in (issue.get("labels") or []) if isinstance(l, dict)],
        "author": (issue.get("user") or {}).get("login") or "",
        "created_at": issue.get("created_at") or "",
        "url": issue.get("html_url") or "",
        "body": (issue.get("body") or "").strip(),
    }
    if include_comments:
        result["comments"] = [
            {
                "author": (c.get("user") or {}).get("login") or "unknown",
                "created_at": c.get("created_at") or "",
                "body": (c.get("body") or "").strip(),
            }
            for c in _comment_list(issue)
            if (c.get("body") or "").strip()
        ]
    return result


def _rank_categories(text: str, categories: dict[str, str], top_k: int) -> list[dict]:
    names = list(categories)
    descriptions = list(categories.values())
    embedder = get_embedder()

    # The new text is a "passage" (no prefix); categories are "queries" (prefixed),
    # matching the convention used to build the collection.
    issue_emb = np.asarray(embedder([text])[0], dtype=np.float32)
    cat_embs = np.asarray(embedder.embed_queries(descriptions), dtype=np.float32)

    sims = cat_embs @ issue_emb  # both L2-normalized -> cosine
    order = sims.argsort()[::-1][:top_k]
    return [{"category": names[i], "score": round(float(sims[i]), 4)} for i in order]


@mcp.tool()
def classify_issue(text: str, top_k: int = 3) -> list[dict]:
    """Zero-shot classify issue text by TOPIC (codebase area, e.g. backend/subsystem).

    This is orthogonal to ``classify_kind`` (what kind of issue it is) and
    ``classify_type`` (Bug / Feature / Enhancement).

    Args:
        text: the issue title/body (or any description) to categorize.
        top_k: how many top-scoring topics to return.

    Returns a list of {category, score} sorted by descending cosine score.
    """
    return _rank_categories(text, DEFAULT_TOPIC_CATEGORIES, top_k)


@mcp.tool()
def classify_kind(text: str, top_k: int = 3) -> list[dict]:
    """Zero-shot classify issue text by KIND (docs, performance, packaging, ...).

    This is orthogonal to ``classify_issue`` (topic area) and ``classify_type``
    (Bug / Feature / Enhancement, which uses labeled centroids instead).

    Args:
        text: the issue title/body (or any description) to categorize.
        top_k: how many top-scoring kinds to return.

    Returns a list of {category, score} sorted by descending cosine score.
    """
    return _rank_categories(text, DEFAULT_TYPE_CATEGORIES, top_k)


@functools.lru_cache(maxsize=1)
def _type_centroids():
    """Cache (names, matrix) of per-type centroids built from labeled issues."""
    cents = type_centroids(_collection())
    names = list(cents)
    mat = np.asarray([cents[n] for n in names], dtype=np.float32)
    return names, mat


@mcp.tool()
def classify_type(text: str, top_k: int = 3) -> list[dict]:
    """Classify issue text by TYPE (Bug / Feature / Enhancement).

    This is orthogonal to ``classify_issue`` (which assigns a topic area).
    It compares the text to few-shot centroids built from issues carrying
    GitHub ``type:`` labels, which is far more reliable than zero-shot phrases.

    Args:
        text: the issue title/body (or any description) to classify.
        top_k: how many top-scoring types to return.

    Returns a list of {type, score} sorted by descending cosine similarity.
    Reliability note: Bug is detected well (~90% recall) and Bug-vs-request is
    ~86% accurate; Feature vs Enhancement overlap heavily, so treat their
    relative order as a weak hint rather than a definitive label.
    """
    names, mat = _type_centroids()
    issue_emb = np.asarray(get_embedder()([text])[0], dtype=np.float32)
    sims = mat @ issue_emb  # centroids are unit vectors; issue_emb normalized
    order = sims.argsort()[::-1][:top_k]
    return [{"type": names[i], "score": round(float(sims[i]), 4)} for i in order]


@mcp.tool()
def cluster_themes(
    method: str = "kmeans", k: int = 20, reps: int = 3, min_cluster_size: int = 15
) -> list[dict]:
    """Cluster the entire issue collection into themes.

    Args:
        method: "kmeans" (uses k) or "hdbscan" (uses min_cluster_size, auto count).
        k: number of clusters for kmeans.
        reps: representative issues to include per cluster.
        min_cluster_size: minimum cluster size for hdbscan.

    Returns clusters (largest first) with id, size, keywords, and representative issues.
    """
    coll = _collection()
    embs, numbers, titles, states, urls = load_vectors(coll)
    labels = run_cluster(embs, method, k, min_cluster_size)

    clusters: list[dict] = []
    for cid in sorted(c for c in set(labels) if c != -1):
        idx = np.where(labels == cid)[0]
        centroid = embs[idx].mean(axis=0)
        order = idx[np.argsort(-(embs[idx] @ centroid))]
        clusters.append(
            {
                "cluster": int(cid),
                "size": len(idx),
                "keywords": top_keywords(titles, labels, cid),
                "representatives": [
                    {"number": numbers[i], "state": states[i], "title": titles[i], "url": urls[i]}
                    for i in order[:reps]
                ],
            }
        )
    clusters.sort(key=lambda c: -c["size"])
    return clusters


def _selftest() -> None:
    print("find_similar_issues('legend not showing', n=3):")
    for m in find_similar_issues("legend not showing", n=3):
        print("  ", m)
    print("\nsearch_issues('polars', limit=5):")
    for m in search_issues("polars", limit=5):
        print("  ", m)
    print("\nclassify_issue('bokeh hover tooltip is empty'):")
    for c in classify_issue("bokeh hover tooltip is empty"):
        print("  ", c)
    print("\nclassify_kind('docs are missing an example for streams'):")
    for c in classify_kind("docs are missing an example for streams"):
        print("  ", c)

    print("\nclassify_type('crash with traceback when saving plot'):")
    for c in classify_type("crash with traceback when saving plot"):
        print("  ", c)
    print("classify_type('Add a new UpSet plot element'):")
    for c in classify_type("Add a new UpSet plot element"):
        print("  ", c)
    print("\ncluster_themes(k=5, reps=1):")
    for c in cluster_themes(k=5, reps=1):
        print(f"   [{c['cluster']}] size={c['size']} {c['keywords']}")


if __name__ == "__main__":
    import sys

    if "--selftest" in sys.argv:
        _selftest()
    else:
        mcp.run()
