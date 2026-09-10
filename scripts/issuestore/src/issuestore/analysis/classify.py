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

from issuestore.categories import categories_for
from issuestore.config import REPO, get_collection, get_embedder

# Categories for the active repo (see issuestore/categories.py). Kept here as
# DEFAULT_CATEGORIES for the CLI/visualizer's "no --labels given" fallback.
DEFAULT_CATEGORIES = categories_for(REPO)


# GitHub `type:` labels -> canonical issue type. Used to build few-shot centroids
# for classify_type (zero-shot phrases are too unstable to separate these).
TYPE_LABEL_MAP = {
    "type: bug": "Bug",
    "type: feature": "Feature",
    "type: enhancement": "Enhancement",
}


def type_centroids(collection) -> dict[str, np.ndarray]:
    """Build a unit centroid embedding per issue type from labeled issues.

    Reads the stored embeddings and label metadata, keeps issues that carry
    exactly one recognized ``type:`` label, and averages their embeddings.
    Returns a mapping of type name -> L2-normalized centroid vector.
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


def load_categories(path: str | None) -> dict[str, str]:
    if not path:
        return DEFAULT_CATEGORIES
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
        "--labels", help="file of 'name: description' lines (default: built-in categories)"
    )
    parser.add_argument(
        "--min-score", type=float, default=0.0, help="assign 'unknown' below this cosine score"
    )
    parser.add_argument("--out", default="categories.csv", help="CSV output path")
    args = parser.parse_args()

    categories = load_categories(args.labels)

    collection = get_collection()
    df = classify_issues(collection, categories, args.min_score)
    df.drop(columns="url").to_csv(args.out, index=False)

    print(f"Classified {len(df)} issues into {len(categories)} categories. Wrote {args.out}.\n")
    counts = df["category"].value_counts()
    for name, cnt in counts.items():
        print(f"  {cnt:>5}  {name}")


if __name__ == "__main__":
    main()
