"""Find issues similar to a given issue or free-text query (duplicate / 'already fixed?' detection).

Results are ranked by a hybrid of dense (bge) similarity and BM25 keyword
scoring, fused with weighted Reciprocal Rank Fusion. The reported similarity is
always the cosine score, so the duplicate threshold keeps its meaning.

Examples::

    python query.py 1000                     # similar to existing issue #1000
    python query.py https://github.com/holoviz/holoviews/issues/1000
    python query.py "bokeh axes not updating on stream"   # free text
    python query.py 1000 --n 15 --state closed --threshold 0.9
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass

import bm25s
import numpy as np

from issuestore.config import get_collection, get_embedder

_ISSUE_URL = re.compile(r"/issues/(\d+)")
_TOKEN = re.compile(r"[a-z0-9_]+(?:\.[a-z0-9_]+)*")
_STOPWORDS = frozenset(bm25s.stopwords.STOPWORDS_EN)

# Tuned on maintainer-linked duplicate pairs; weighting dense 2:1 gave the best
# recall@10 across holoviews, panel, and bokeh.
DENSE_WEIGHT = 2.0
BM25_WEIGHT = 1.0
RRF_K = 60
CANDIDATES = 100


def tokenize(text: str) -> list[str]:
    """Lowercase word tokens; dotted names like ``hv.Curve`` are kept whole and split."""
    out = []
    for tok in _TOKEN.findall(text.lower()):
        if "." in tok:
            out.append(tok)
            out.extend(p for p in tok.split(".") if p and p not in _STOPWORDS)
        elif len(tok) > 1 and tok not in _STOPWORDS:
            out.append(tok)
    return out


@dataclass(frozen=True)
class SearchIndex:
    ids: list[str]
    metas: list[dict]
    embs: np.ndarray
    docs: list[str]
    bm25: bm25s.BM25
    pos: dict[str, int]


def load_index(collection) -> SearchIndex:
    """Snapshot the collection into memory with a BM25 index over the documents."""
    got = collection.get(include=["embeddings", "metadatas", "documents"])
    bm25 = bm25s.BM25()
    bm25.index([tokenize(d) for d in got["documents"]], show_progress=False)
    return SearchIndex(
        ids=got["ids"],
        metas=got["metadatas"],
        embs=np.asarray(got["embeddings"], dtype=np.float32),
        docs=got["documents"],
        bm25=bm25,
        pos={i: n for n, i in enumerate(got["ids"])},
    )


def resolve_seed(index: SearchIndex, embedder, raw: str):
    """Return (query_embedding, keyword_text, seed_number_or_None) from a number, URL, or free text.

    For an existing issue we reuse its stored passage embedding (symmetric
    passage-to-passage comparison), which is more accurate for duplicate
    detection than re-embedding its text as a query. Free text is embedded with
    the bge query prefix. The keyword text for an issue is its title and body;
    comments are left out since they often just point at other issues.
    """
    num = None
    if raw.isdigit():
        num = raw
    else:
        m = _ISSUE_URL.search(raw)
        if m:
            num = m.group(1)

    if num is not None:
        if num not in index.pos:
            sys.exit(f"Issue #{num} is not in the collection. Provide free text instead.")
        i = index.pos[num]
        return index.embs[i], index.docs[i].split("\n\nComment by ", 1)[0], num
    return np.asarray(embedder.embed_query(raw), dtype=np.float32), raw, None


def _mask(index: SearchIndex, state: str, kind: str) -> np.ndarray:
    mask = np.ones(len(index.ids), dtype=bool)
    for n, meta in enumerate(index.metas):
        if (
            (state == "open" and not meta.get("is_open"))
            or (state == "closed" and meta.get("is_open"))
            or (kind in ("issue", "pr") and meta.get("kind", "issue") != kind)
        ):
            mask[n] = False
    return mask


def find_similar(
    index: SearchIndex, embedder, raw: str, n: int = 10, state: str = "all", kind: str = "all"
):
    """Return (seed_number_or_None, [(metadata, cosine_similarity), ...]) best first."""
    emb, text, seed = resolve_seed(index, embedder, raw)
    mask = _mask(index, state, kind)
    if seed is not None:
        mask[index.pos[seed]] = False
    available = int(mask.sum())
    if available == 0:
        return seed, []

    sims = index.embs @ emb
    masked = np.where(mask, sims, -np.inf)
    k = min(CANDIDATES, available)
    top = np.argpartition(-masked, k - 1)[:k]
    dense = top[np.argsort(-masked[top])].tolist()

    keyword: list[int] = []
    tokens = [t for t in tokenize(text) if t in index.bm25.vocab_dict]
    if tokens:
        docs, scores = index.bm25.retrieve(
            [tokens], k=k, weight_mask=mask.astype(np.float32), show_progress=False, n_threads=0
        )
        keyword = [int(d) for d, s in zip(docs[0], scores[0], strict=True) if s > 0]

    fused: dict[int, float] = {}
    for weight, ranking in ((DENSE_WEIGHT, dense), (BM25_WEIGHT, keyword)):
        for rank, doc in enumerate(ranking):
            fused[doc] = fused.get(doc, 0.0) + weight / (RRF_K + rank + 1)
    best = sorted(fused, key=fused.__getitem__, reverse=True)[:n]
    return seed, [(index.metas[i], float(sims[i])) for i in best]


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "query", nargs="+", help="issue number, GitHub issue URL, or free-text query"
    )
    parser.add_argument("--n", type=int, default=10, help="number of results (default: 10)")
    parser.add_argument("--state", choices=["all", "open", "closed"], default="all")
    parser.add_argument(
        "--threshold", type=float, default=0.85, help="similarity to flag as likely duplicate"
    )
    args = parser.parse_args()

    index = load_index(get_collection())
    raw = " ".join(args.query)
    seed, matches = find_similar(index, get_embedder(), raw, n=args.n, state=args.state)

    if seed:
        print(f"Seed issue #{seed}: {index.metas[index.pos[seed]]['title']}\n")
    else:
        print(f"Query: {raw}\n")

    print(f"{'sim':>6}  {'flag':<5} {'state':<6} {'#num':<7} title")
    print("-" * 88)
    for meta, sim in matches:
        flag = "DUP?" if sim >= args.threshold else ""
        print(f"{sim:6.3f}  {flag:<5} {meta['state']:<6} #{meta['number']:<6} {meta['title']}")
        print(f"{'':>6}  {'':<5} {'':<6} {'':<7} {meta['html_url']}")


if __name__ == "__main__":
    main()
