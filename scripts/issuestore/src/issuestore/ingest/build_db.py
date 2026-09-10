"""Build a ChromaDB of holoviews GitHub issues for grouping and duplicate detection.

Reads the raw GitHub issue JSON files in ``data/`` (as produced by
``issuestore download`` / ``ingest/download.py``), extracts only the relevant content, embeds it with
``BAAI/bge-large-en-v1.5`` on the GPU, and upserts it into a persistent Chroma
collection.

    Usage::

    python build_db.py            # build / update the collection
    python build_db.py --force    # re-embed every issue, ignoring updated_at
    python build_db.py --test     # build, then run sanity-check queries
    python build_db.py --test-only  # skip build, only run sanity-check queries

Re-running only (re-)embeds new issues plus any whose ``updated_at`` is newer
than the copy already in the collection; unchanged issues are skipped so a
rebuild after a fresh ``download`` costs no GPU work for untouched issues.
``--force`` re-embeds everything.
"""

from __future__ import annotations

import argparse
import glob
import json
import os

from issuestore.config import DATA_DIR, UPSERT_BATCH, get_collection, get_embedder


def _is_bot(user: dict | None) -> bool:
    if not user:
        return False
    login = (user.get("login") or "").lower()
    return user.get("type") == "Bot" or login.endswith("[bot]")


def _comment_list(issue: dict) -> list[dict]:
    """Return the flat list of comments, handling the double-nested slurp shape."""
    comments = issue.get("comments")
    if not isinstance(comments, list):
        return []
    # Older caches nested comments as a slurped [[...]] list; flatten those.
    if comments and isinstance(comments[0], list):
        comments = comments[0]
    return [c for c in comments if isinstance(c, dict)]


def build_document(issue: dict) -> str:
    """Assemble the text to embed: title + body + non-bot comments, front-loaded."""
    parts: list[str] = [f"Title: {issue.get('title') or ''}"]
    body = (issue.get("body") or "").strip()
    if body:
        parts.append(body)
    for c in _comment_list(issue):
        if _is_bot(c.get("user")):
            continue
        cbody = (c.get("body") or "").strip()
        if not cbody:
            continue
        author = (c.get("user") or {}).get("login") or "unknown"
        parts.append(f"Comment by {author}: {cbody}")
    return "\n\n".join(parts)


def build_metadata(issue: dict, n_comments: int) -> dict:
    labels = ", ".join(
        l.get("name", "") for l in (issue.get("labels") or []) if isinstance(l, dict)
    )
    state = issue.get("state") or ""
    return {
        "number": int(issue.get("number", 0)),
        "title": issue.get("title") or "",
        "state": state,
        "labels": labels,
        "author": (issue.get("user") or {}).get("login") or "",
        "created_at": issue.get("created_at") or "",
        "updated_at": issue.get("updated_at") or "",
        "closed_at": issue.get("closed_at") or "",
        "html_url": issue.get("html_url") or "",
        "comment_count": n_comments,
        "is_open": state == "open",
    }


def iter_issues():
    files = sorted(glob.glob(os.path.join(DATA_DIR, "issue-*.json")))
    for path in files:
        try:
            with open(path, encoding="utf-8") as f:
                yield json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"  WARN: skipping {path}: {exc}")


def _stored_updated_at(collection) -> dict[str, str]:
    """Map issue id -> ``updated_at`` for everything already in the collection.

    Used to skip re-embedding issues that have not changed since the last build.
    GitHub timestamps are ISO 8601 UTC, so lexical comparison matches chronology.
    """
    existing = collection.get(include=["metadatas"])
    stored: dict[str, str] = {}
    for id_, meta in zip(existing["ids"], existing["metadatas"] or [], strict=False):
        stored[id_] = (meta or {}).get("updated_at") or ""
    return stored


def build(collection, force: bool = False) -> None:
    ids: list[str] = []
    docs: list[str] = []
    metas: list[dict] = []
    total = 0
    embedded = 0
    skipped = 0

    stored = {} if force else _stored_updated_at(collection)

    def flush() -> None:
        nonlocal ids, docs, metas
        if not ids:
            return
        collection.upsert(ids=ids, documents=docs, metadatas=metas)
        ids, docs, metas = [], [], []

    for issue in iter_issues():
        number = issue.get("number")
        if number is None:
            continue
        total += 1
        id_ = str(number)
        updated_at = issue.get("updated_at") or ""
        # Skip when the collection already holds this issue at an updated_at that
        # is at least as recent as the file; only changed issues are re-embedded.
        if not force and id_ in stored and stored[id_] >= updated_at and updated_at:
            skipped += 1
            continue
        n_comments = len(_comment_list(issue))
        ids.append(id_)
        docs.append(build_document(issue))
        metas.append(build_metadata(issue, n_comments))
        embedded += 1
        if len(ids) >= UPSERT_BATCH:
            flush()
            print(f"  embedded {embedded} issues...")
    flush()
    print(
        f"Done. {embedded} embedded, {skipped} unchanged (skipped) of {total} issues. "
        f"Collection count: {collection.count()}"
    )


def run_tests(collection, embedder) -> None:
    print("\n=== Grouping sanity check: 'bug with bokeh plotting' ===")
    q = embedder.embed_query("bug with bokeh plotting")
    res = collection.query(query_embeddings=[q], n_results=5)
    for meta, dist in zip(res["metadatas"][0], res["distances"][0], strict=False):
        print(f"  #{meta['number']:<6} [{meta['state']:<6}] sim={1 - dist:.3f}  {meta['title']}")

    print("\n=== Duplicate sanity check: seed from an existing issue ===")
    sample = collection.get(ids=["1000"])
    if sample["ids"]:
        title = sample["metadatas"][0]["title"]
        print(f"  seed #1000: {title}")
        q = embedder.embed_query(title)
        res = collection.query(query_embeddings=[q], n_results=5)
        for meta, dist in zip(res["metadatas"][0], res["distances"][0], strict=False):
            print(
                f"  #{meta['number']:<6} [{meta['state']:<6}] sim={1 - dist:.3f}  {meta['title']}"
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force", action="store_true", help="re-embed every issue, ignoring updated_at"
    )
    parser.add_argument("--test", action="store_true", help="run sanity queries after build")
    parser.add_argument("--test-only", action="store_true", help="skip build, only run queries")
    args = parser.parse_args()

    embedder = get_embedder()
    collection = get_collection(create=True)

    if not args.test_only:
        build(collection, force=args.force)
    if args.test or args.test_only:
        run_tests(collection, embedder)


if __name__ == "__main__":
    main()
