"""Zero-shot categorize every issue into predefined buckets by nearest-label embedding.

Each category is described by a short phrase. The phrases are embedded and every
issue's stored embedding is compared (cosine) to them; the best-scoring category
wins. Writes a CSV of number,title,state,category,score and prints per-category counts.

Examples::

    python classify.py                       # use built-in default categories
    python classify.py --labels labels.txt   # one "name: description" per line
    python classify.py --min-score 0.3 --out categories.csv
"""

from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from issuestore.categories import topic_categories_for, type_categories_for
from issuestore.config import REPO, get_collection, get_embedder

# Categories for the active repo (see issuestore/categories.py). Kept here as
# the CLI/visualizer's "no --labels given" fallback, one dict per dimension.
DEFAULT_TOPIC_CATEGORIES = topic_categories_for(REPO)
DEFAULT_TYPE_CATEGORIES = type_categories_for(REPO)


# GitHub labels -> canonical issue type (matching keys in categories.TYPE_CATEGORIES).
# Used to build few-shot centroids for these, which beat a zero-shot phrase for
# this distinction - and, when an issue carries the label itself, as ground
# truth. Label spellings vary by repo (e.g. hvplot has none of these); an entry
# simply never matches on a repo that doesn't use it.
TYPE_LABEL_MAP = {
    "type: bug": "bug",
    "type: feature": "feature",
    "type: enhancement": "enhancement",
    "type: docs": "documentation",
    "type: maintenance": "ci",
    "type: infra": "ci",
    "tag: packaging": "installation / packaging",
    "tag: component: testing": "testing",
}


def type_centroids(collection) -> dict[str, np.ndarray]:
    """Build a unit centroid embedding per issue type from labeled issues.

    Reads the stored embeddings and label metadata, keeps issues that carry
    exactly one label recognized by ``TYPE_LABEL_MAP``, and averages their
    embeddings. Returns a mapping of type name -> L2-normalized centroid vector.
    """
    got = collection.get(include=["embeddings", "metadatas"])
    embs = np.asarray(got["embeddings"], dtype=np.float32)

    buckets: dict[str, list[int]] = {}
    for i, meta in enumerate(got["metadatas"]):
        labels = [s.strip() for s in (meta.get("labels") or "").split(",")]
        hits = {TYPE_LABEL_MAP[l] for l in labels if l in TYPE_LABEL_MAP}
        if len(hits) == 1:  # skip untyped or ambiguously multi-typed issues
            buckets.setdefault(hits.pop(), []).append(i)

    centroids: dict[str, np.ndarray] = {}
    for name, idx in buckets.items():
        v = embs[idx].mean(axis=0)
        centroids[name] = v / np.linalg.norm(v)
    return centroids


def classify_type_dimension(collection, categories: dict[str, str], min_score: float = 0.0):
    """Assign each stored issue's TYPE, one of ``categories`` (e.g. documentation,
    performance, bug, feature, ...).

    For a name covered by ``TYPE_LABEL_MAP``, issues carrying the matching
    GitHub label get it as ground truth (score 1.0); everything else is
    nearest-match by embedding cosine, using a few-shot centroid (built from
    those labeled issues) in place of the zero-shot phrase wherever one is
    available, since that's far more reliable than a phrase for these names.

    Same return shape as ``classify_issues``, so it's a drop-in replacement for
    the type dimension specifically.
    """
    embedder = get_embedder()
    got = collection.get(include=["embeddings", "metadatas"])
    issue_embs = np.asarray(got["embeddings"], dtype=np.float32)

    centroids = type_centroids(collection)

    names = list(categories)
    phrase_names = [n for n in names if n not in centroids]
    phrase_embs = np.asarray(
        embedder.embed_queries([categories[n] for n in phrase_names]), dtype=np.float32
    )
    phrase_by_name = dict(zip(phrase_names, phrase_embs, strict=True))
    combined = np.asarray(
        [centroids[n] if n in centroids else phrase_by_name[n] for n in names], dtype=np.float32
    )

    # Both sets are L2-normalized, so a dot product is cosine similarity.
    sims = issue_embs @ combined.T
    best = sims.argmax(axis=1)
    best_score = sims[np.arange(len(best)), best]

    assigned: list[str] = []
    scores: list[float] = []
    for i, meta in enumerate(got["metadatas"]):
        labels = [s.strip() for s in (meta.get("labels") or "").split(",")]
        hits = {TYPE_LABEL_MAP[l] for l in labels if l in TYPE_LABEL_MAP}
        if len(hits) == 1:
            assigned.append(hits.pop())
            scores.append(1.0)
        else:
            s = float(best_score[i])
            assigned.append(names[best[i]] if s >= min_score else "unknown")
            scores.append(round(s, 4))

    return pd.DataFrame(
        {
            "number": [m["number"] for m in got["metadatas"]],
            "title": [m["title"] for m in got["metadatas"]],
            "state": [m["state"] for m in got["metadatas"]],
            "url": [m["html_url"] for m in got["metadatas"]],
            "category": assigned,
            "score": scores,
        }
    ).sort_values(["category", "score"], ascending=[True, False])


def classify_issues(collection, categories: dict[str, str], min_score: float = 0.0):
    """Assign each stored issue to its nearest category by embedding cosine.

    Returns a DataFrame with number, title, state, url, category, score, sorted
    by (category, score). Shared by the CLI and the visualizer so both agree on
    how categories are computed.
    """
    names = list(categories)
    descriptions = list(categories.values())

    embedder = get_embedder()
    got = collection.get(include=["embeddings", "metadatas"])
    issue_embs = np.asarray(got["embeddings"], dtype=np.float32)
    # Categories are the "queries" (use the bge query prefix); issues are passages.
    cat_embs = np.asarray(embedder.embed_queries(descriptions), dtype=np.float32)

    # Both sets are L2-normalized, so a dot product is cosine similarity.
    sims = issue_embs @ cat_embs.T
    best = sims.argmax(axis=1)
    best_score = sims[np.arange(len(best)), best]

    assigned = [
        names[b] if s >= min_score else "unknown" for b, s in zip(best, best_score, strict=False)
    ]

    return pd.DataFrame(
        {
            "number": [m["number"] for m in got["metadatas"]],
            "title": [m["title"] for m in got["metadatas"]],
            "state": [m["state"] for m in got["metadatas"]],
            "url": [m["html_url"] for m in got["metadatas"]],
            "category": assigned,
            "score": np.round(best_score, 4),
        }
    ).sort_values(["category", "score"], ascending=[True, False])


def load_categories(path: str | None) -> dict[str, str] | None:
    """Load a custom 'name: description' label file, or None to use the
    built-in topic/type dimensions."""
    if not path:
        return None
    cats: dict[str, str] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            name, _, desc = line.partition(":")
            cats[name.strip()] = desc.strip() or name.strip()
    return cats


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--labels",
        help="file of 'name: description' lines (default: built-in topic + type dimensions)",
    )
    parser.add_argument(
        "--min-score", type=float, default=0.0, help="assign 'unknown' below this cosine score"
    )
    parser.add_argument("--out", default="categories.csv", help="CSV output path")
    args = parser.parse_args()

    collection = get_collection()
    categories = load_categories(args.labels)

    if categories is not None:
        df = classify_issues(collection, categories, args.min_score)
        df.drop(columns="url").to_csv(args.out, index=False)

        print(
            f"Classified {len(df)} issues into {len(categories)} categories. Wrote {args.out}.\n"
        )
        for name, cnt in df["category"].value_counts().items():
            print(f"  {cnt:>5}  {name}")
        return

    # No custom labels: classify topic (codebase area) and type (kind of issue)
    # independently, since they're orthogonal, and merge into one CSV.
    topic_df = classify_issues(collection, DEFAULT_TOPIC_CATEGORIES, args.min_score)
    type_df = classify_type_dimension(collection, DEFAULT_TYPE_CATEGORIES, args.min_score)
    df = topic_df.rename(columns={"category": "topic", "score": "topic_score"}).merge(
        type_df[["number", "category", "score"]].rename(
            columns={"category": "type", "score": "type_score"}
        ),
        on="number",
    )
    df = df.sort_values(["topic", "type"])
    df.drop(columns="url").to_csv(args.out, index=False)

    print(
        f"Classified {len(df)} issues into {len(DEFAULT_TOPIC_CATEGORIES)} topics and "
        f"{len(DEFAULT_TYPE_CATEGORIES)} types. Wrote {args.out}.\n"
    )
    print("By topic:")
    for name, cnt in df["topic"].value_counts().items():
        print(f"  {cnt:>5}  {name}")
    print("\nBy type:")
    for name, cnt in df["type"].value_counts().items():
        print(f"  {cnt:>5}  {name}")


if __name__ == "__main__":
    main()
