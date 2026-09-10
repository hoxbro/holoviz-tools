"""Discover themes among the issues by clustering their stored embeddings.

Pulls all embeddings out of the Chroma collection (no re-embedding needed),
clusters them, and prints each group's size, top keywords (TF-IDF over titles),
and a few representative issues. Also writes assignments to a CSV.

Examples::

    python cluster.py                       # HDBSCAN (auto number of clusters)
    python cluster.py --method kmeans --k 25
    python cluster.py --min-cluster-size 20 --out clusters.csv
"""

from __future__ import annotations

import argparse

import numpy as np
import pandas as pd
from sklearn.cluster import HDBSCAN, KMeans
from sklearn.feature_extraction.text import TfidfVectorizer

from issuestore.config import get_collection

# Below this many titles, TF-IDF isn't meaningful, so just join them verbatim.
MIN_KEYWORD_DOCS = 2


def load_vectors(collection):
    got = collection.get(include=["embeddings", "metadatas"])
    embs = np.asarray(got["embeddings"], dtype=np.float32)
    numbers = [m["number"] for m in got["metadatas"]]
    titles = [m["title"] for m in got["metadatas"]]
    states = [m["state"] for m in got["metadatas"]]
    urls = [m["html_url"] for m in got["metadatas"]]
    return embs, numbers, titles, states, urls


def cluster(embs, method: str, k: int, min_cluster_size: int):
    # Embeddings are L2-normalized, so euclidean distance is monotonic with cosine.
    if method == "kmeans":
        model = KMeans(n_clusters=k, n_init=10, random_state=0)
    else:
        model = HDBSCAN(min_cluster_size=min_cluster_size, metric="euclidean")
    return model.fit_predict(embs)


def top_keywords(titles: list[str], labels: np.ndarray, cluster_id: int, n: int = 6) -> str:
    mask = labels == cluster_id
    docs = [t for t, m in zip(titles, mask, strict=False) if m]
    if len(docs) < MIN_KEYWORD_DOCS:
        return ", ".join(docs)[:60]
    try:
        vec = TfidfVectorizer(stop_words="english", max_features=2000)
        tfidf = vec.fit_transform(docs)
        scores = np.asarray(tfidf.mean(axis=0)).ravel()
        vocab = np.array(vec.get_feature_names_out())
        return ", ".join(vocab[scores.argsort()[::-1][:n]])
    except ValueError:
        return ""


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--method", choices=["hdbscan", "kmeans"], default="hdbscan")
    parser.add_argument("--k", type=int, default=25, help="number of clusters for kmeans")
    parser.add_argument(
        "--min-cluster-size", type=int, default=15, help="HDBSCAN min cluster size"
    )
    parser.add_argument(
        "--reps", type=int, default=3, help="representative issues to show per cluster"
    )
    parser.add_argument("--out", default="clusters.csv", help="CSV output path")
    args = parser.parse_args()

    collection = get_collection()
    embs, numbers, titles, states, urls = load_vectors(collection)
    print(
        f"Loaded {len(numbers)} issue vectors ({embs.shape[1]}-dim). Clustering with {args.method}..."
    )

    labels = cluster(embs, args.method, args.k, args.min_cluster_size)

    df = pd.DataFrame(
        {"number": numbers, "title": titles, "state": states, "url": urls, "cluster": labels}
    )
    df.to_csv(args.out, index=False)

    unique = sorted(set(labels))
    n_noise = int((labels == -1).sum())
    print(
        f"Found {len([c for c in unique if c != -1])} clusters"
        + (f" ({n_noise} unclustered)" if -1 in unique else "")
        + f". Wrote {args.out}.\n"
    )

    # Order clusters by size (largest first), noise last.
    sizes = {c: int((labels == c).sum()) for c in unique}
    for cid in sorted((c for c in unique if c != -1), key=lambda c: -sizes[c]):
        idx = np.where(labels == cid)[0]
        # Representatives = closest to the cluster centroid.
        centroid = embs[idx].mean(axis=0)
        order = idx[np.argsort(-(embs[idx] @ centroid))]
        print(f"[cluster {cid}] size={sizes[cid]}  keywords: {top_keywords(titles, labels, cid)}")
        for i in order[: args.reps]:
            print(f"    #{numbers[i]:<6} [{states[i]:<6}] {titles[i]}")
        print()


if __name__ == "__main__":
    main()
