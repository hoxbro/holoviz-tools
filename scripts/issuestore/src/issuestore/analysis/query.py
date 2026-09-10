"""Find issues similar to a given issue or free-text query (duplicate / 'already fixed?' detection).

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

from issuestore.config import get_collection, get_embedder

_ISSUE_URL = re.compile(r"/issues/(\d+)")


def resolve_seed(collection, embedder, raw: str):
    """Return (query_embedding, seed_number_or_None) from a number, URL, or free text.

    For an existing issue we reuse its stored passage embedding (symmetric
    passage-to-passage comparison), which is more accurate for duplicate
    detection than re-embedding its text as a query. Free text is embedded with
    the bge query prefix.
    """
    num = None
    if raw.isdigit():
        num = raw
    else:
        m = _ISSUE_URL.search(raw)
        if m:
            num = m.group(1)

    if num is not None:
        got = collection.get(ids=[num], include=["embeddings"])
        if not got["ids"]:
            sys.exit(f"Issue #{num} is not in the collection. Provide free text instead.")
        return got["embeddings"][0], num
    return embedder.embed_query(raw), None


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

    collection = get_collection()
    embedder = get_embedder()

    raw = " ".join(args.query)
    q, seed = resolve_seed(collection, embedder, raw)

    where = None
    if args.state == "open":
        where = {"is_open": True}
    elif args.state == "closed":
        where = {"is_open": False}

    # Fetch a couple extra so we can drop the seed itself if present.
    res = collection.query(query_embeddings=[q], n_results=args.n + 1, where=where)

    if seed:
        print(f"Seed issue #{seed}: {collection.get(ids=[seed])['metadatas'][0]['title']}\n")
    else:
        print(f"Query: {raw}\n")

    print(f"{'sim':>6}  {'flag':<5} {'state':<6} {'#num':<7} title")
    print("-" * 88)
    shown = 0
    for meta, dist in zip(res["metadatas"][0], res["distances"][0], strict=False):
        if seed and str(meta["number"]) == seed:
            continue  # skip the seed matching itself
        sim = 1 - dist
        flag = "DUP?" if sim >= args.threshold else ""
        print(f"{sim:6.3f}  {flag:<5} {meta['state']:<6} #{meta['number']:<6} {meta['title']}")
        print(f"{'':>6}  {'':<5} {'':<6} {'':<7} {meta['html_url']}")
        shown += 1
        if shown >= args.n:
            break


if __name__ == "__main__":
    main()
