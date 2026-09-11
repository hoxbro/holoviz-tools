"""Find open issues that a merged PR appears to have already fixed.

Two complementary passes flag candidate open issues:

* **reference pass** - merged PRs whose text references the issue via a closing
  keyword (``Fixes/Closes/Resolves #N`` -> ``reason="closes"``) or a bare
  ``#N`` mention (``reason="mentions"``). These are parsed at build time and
  stored on each PR's Chroma metadata (``closes`` / ``mentions``).
* **semantic pass** - merged PRs whose embedding is highly similar to the open
  issue's embedding (``reason="semantic"``), catching fixes that never cited
  the issue number.

Candidates are merged per issue and deduped by PR, preferring the strongest
reason (closes > mentions > semantic).

Examples::

    issuestore fixed                      # scan all open issues
    issuestore fixed 5361                 # just this open issue
    issuestore fixed --threshold 0.85 --limit 20
"""

from __future__ import annotations

import argparse

import numpy as np

from issuestore.config import get_collection

# Strongest reason first; used both to dedupe and to sort candidates.
_REASON_PRIORITY = {"closes": 0, "mentions": 1, "semantic": 2}


def _ref_numbers(meta: dict, field: str) -> set[int]:
    """Parse a comma-joined issue-number metadata field back into a set of ints."""
    raw = meta.get(field) or ""
    return {int(x) for x in raw.split(",") if x.strip().isdigit()}


def _candidate(meta: dict, reason: str, similarity: float | None) -> dict:
    return {
        "pr": meta["number"],
        "title": meta["title"],
        "url": meta.get("html_url", ""),
        "merged_at": meta.get("merged_at", ""),
        "reason": reason,
        "similarity": similarity,
    }


def build_reference_index(pr_metas: list[dict]) -> dict[int, list[dict]]:
    """Map issue number -> merged-PR candidates that reference it.

    Each PR contributes at most one entry per referenced issue, using the
    stronger ``closes`` reason when a number appears both as a close and a
    mention (``parse_closes`` already keeps the two sets disjoint).
    """
    index: dict[int, list[dict]] = {}
    for meta in pr_metas:
        for reason, field in (("closes", "closes"), ("mentions", "mentions")):
            for num in _ref_numbers(meta, field):
                index.setdefault(num, []).append(_candidate(meta, reason, None))
    return index


def semantic_candidates(
    issue_embs: np.ndarray,
    issue_numbers: list[int],
    pr_embs: np.ndarray,
    pr_metas: list[dict],
    threshold: float,
    top_k: int = 5,
) -> dict[int, list[dict]]:
    """Map issue number -> merged-PR candidates above ``threshold`` cosine similarity.

    Embeddings are L2-normalized (see ``BGEEmbeddingFunction``), so the dot
    product is cosine similarity; a single matrix multiply scores every
    issue/PR pair at once.
    """
    if issue_embs.size == 0 or pr_embs.size == 0:
        return {}
    sims = issue_embs @ pr_embs.T  # (n_issues, n_prs)
    out: dict[int, list[dict]] = {}
    for i, num in enumerate(issue_numbers):
        row = sims[i]
        hits: list[dict] = []
        for j in np.argsort(-row)[:top_k]:
            score = float(row[j])
            if score < threshold:
                break
            hits.append(_candidate(pr_metas[j], "semantic", round(score, 4)))
        if hits:
            out[num] = hits
    return out


def merge_candidates(ref_hits: list[dict], sem_hits: list[dict]) -> list[dict]:
    """Combine one issue's reference and semantic candidates.

    Deduped by PR number, keeping the strongest reason while preserving any
    similarity score, then sorted strongest-reason-first and by similarity.
    """
    by_pr: dict[int, dict] = {}
    for cand in [*ref_hits, *sem_hits]:
        existing = by_pr.get(cand["pr"])
        if existing is None:
            by_pr[cand["pr"]] = dict(cand)
            continue
        # Prefer the stronger reason; carry over a similarity from either side.
        sim = existing["similarity"] if cand["similarity"] is None else cand["similarity"]
        if _REASON_PRIORITY[cand["reason"]] < _REASON_PRIORITY[existing["reason"]]:
            merged = dict(cand)
        else:
            merged = dict(existing)
        merged["similarity"] = sim
        by_pr[cand["pr"]] = merged
    cands = list(by_pr.values())
    cands.sort(key=lambda c: (_REASON_PRIORITY[c["reason"]], -(c["similarity"] or 0.0)))
    return cands


def _matrix(got: dict) -> tuple[np.ndarray, list[int], list[dict]]:
    """Turn a Chroma ``get`` result into (embeddings, numbers, metadatas).

    Chroma returns ``embeddings`` as a numpy array, so test it for emptiness by
    length rather than truthiness (``array or []`` raises on a multi-element
    array).
    """
    raw = got.get("embeddings")
    if raw is None or len(raw) == 0:
        embs = np.empty((0, 0), dtype=np.float32)
    else:
        embs = np.asarray(raw, dtype=np.float32)
    metas = got.get("metadatas") or []
    numbers = [int(m["number"]) for m in metas]
    return embs, numbers, metas


def find_fixed(
    collection,
    threshold: float = 0.8,
    issue_number: int | None = None,
    limit: int = 0,
    top_k: int = 5,
) -> list[dict]:
    """Return open issues with their candidate fixing PRs (both passes merged).

    Args:
        collection: the Chroma collection holding issues and PRs.
        threshold: minimum cosine similarity for a semantic candidate.
        issue_number: restrict to a single open issue instead of scanning all.
        limit: cap the number of issues returned (0 = no cap).
        top_k: max semantic candidates considered per issue.

    Only issues that have at least one candidate are returned.
    """
    if issue_number is not None:
        got_issues = collection.get(ids=[str(issue_number)], include=["embeddings", "metadatas"])
    else:
        got_issues = collection.get(
            where={"$and": [{"is_open": True}, {"kind": "issue"}]},
            include=["embeddings", "metadatas"],
        )
    issue_embs, issue_numbers, issue_metas = _matrix(got_issues)

    got_prs = collection.get(
        where={"$and": [{"kind": "pr"}, {"merged": True}]},
        include=["embeddings", "metadatas"],
    )
    pr_embs, _, pr_metas = _matrix(got_prs)

    ref_index = build_reference_index(pr_metas)
    sem_index = semantic_candidates(issue_embs, issue_numbers, pr_embs, pr_metas, threshold, top_k)

    results: list[dict] = []
    for num, meta in zip(issue_numbers, issue_metas, strict=False):
        candidates = merge_candidates(ref_index.get(num, []), sem_index.get(num, []))
        if not candidates:
            continue
        results.append(
            {
                "number": num,
                "title": meta["title"],
                "url": meta.get("html_url", ""),
                "candidates": candidates,
            }
        )

    # Surface the most strongly-linked issues first (a confirmed "closes" beats a
    # weak semantic hint), then by best similarity, then newest.
    def _rank(item: dict) -> tuple:
        best = item["candidates"][0]
        return (_REASON_PRIORITY[best["reason"]], -(best["similarity"] or 0.0), -item["number"])

    results.sort(key=_rank)
    if limit > 0:
        results = results[:limit]
    return results


def _format(results: list[dict]) -> str:
    if not results:
        return "No open issues look already fixed by a merged PR."
    lines: list[str] = []
    for item in results:
        lines.append(f"#{item['number']} {item['title']}")
        lines.append(f"  {item['url']}")
        for c in item["candidates"]:
            sim = f" sim={c['similarity']:.3f}" if c["similarity"] is not None else ""
            lines.append(f"    [{c['reason']:<8}]{sim} PR #{c['pr']}  {c['title']}")
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "issue", nargs="?", type=int, default=None, help="a single open issue number to check"
    )
    parser.add_argument(
        "--threshold", type=float, default=0.8, help="min similarity for a semantic candidate"
    )
    parser.add_argument("--limit", type=int, default=0, help="max issues to report (0 = all)")
    parser.add_argument("--top-k", type=int, default=5, help="max semantic candidates per issue")
    args = parser.parse_args()

    collection = get_collection()
    # Semantic scoring reuses the embeddings already stored in Chroma, so no
    # GPU model load is needed here.
    results = find_fixed(
        collection,
        threshold=args.threshold,
        issue_number=args.issue,
        limit=args.limit,
        top_k=args.top_k,
    )
    print(_format(results))


if __name__ == "__main__":
    main()
