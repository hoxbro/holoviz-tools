"""Download all issues (and their comments) for a repo via the GitHub REST API.

Uses httpx and writes one ``issue-<n>.json`` per issue into the
per-repo cache (``config.DATA_DIR``), matching the shape ``build_db`` expects:
the full issue object plus a ``comments`` list. Pull requests are skipped.
Re-running only fetches new issues plus any whose GitHub ``updated_at`` is
newer than the local copy (i.e. issues that changed since the last pull);
unchanged issues are left untouched. ``--force`` re-downloads everything.

Examples::

    python -m issuestore.ingest.download
    ISSUE_REPO=pandas-dev/pandas python -m issuestore.ingest.download
    python -m issuestore.ingest.download --repo bokeh/bokeh --force
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from http import HTTPStatus

import httpx2

from issuestore.config import DATA_DIR, REPO

CONCURRENCY = 10


API_ROOT = "https://api.github.com"
PER_PAGE = 100


async def _get(
    client: httpx2.AsyncClient, url: str, params: dict | None = None
) -> httpx2.Response:
    """GET with basic secondary-rate-limit backoff."""
    for attempt in range(6):
        resp = await client.get(url, params=params)
        if (
            resp.status_code == HTTPStatus.FORBIDDEN
            and resp.headers.get("x-ratelimit-remaining") == "0"
        ):
            reset = int(resp.headers.get("x-ratelimit-reset", "0"))
            delay = max(reset - int(time.time()), 1)
            print(f"\n  rate limited; sleeping {delay}s...", file=sys.stderr)
            await asyncio.sleep(delay)
            continue
        if resp.status_code in (429, 502, 503):
            delay = int(resp.headers.get("retry-after", 2**attempt))
            await asyncio.sleep(delay)
            continue
        resp.raise_for_status()
        return resp
    resp.raise_for_status()
    return resp


async def _paginate(client: httpx2.AsyncClient, url: str, params: dict | None) -> list[dict]:
    """Follow RFC 5988 Link headers, accumulating JSON array results."""
    params = {**(params or {}), "per_page": PER_PAGE}
    items: list[dict] = []
    while url:
        resp = await _get(client, url, params)
        items.extend(resp.json())
        next_url = resp.links.get("next", {}).get("url")
        if next_url is None:
            break
        url = next_url
        params = None  # the next link already encodes query params
    return items


def _stored_updated_at(path: str) -> str | None:
    """Return the ``updated_at`` of a previously downloaded issue, if readable.

    GitHub timestamps are ISO 8601 UTC (``...Z``), so lexical comparison of two
    such strings matches chronological order.
    """
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f).get("updated_at")
    except OSError, ValueError:
        return None


async def _fetch_issue(
    client: httpx2.AsyncClient,
    sem: asyncio.Semaphore,
    repo: str,
    listed: dict,
    out: str,
) -> None:
    """Fetch one issue's full object plus comments and write it to ``out``.

    Bounded by ``sem`` so at most ``CONCURRENCY`` issues are in flight at once.
    """
    number = listed["number"]
    async with sem:
        # Fetch the full issue object (has fields the list omits, e.g. `type`)
        # plus all comments, then store them together.
        resp = await _get(client, f"{API_ROOT}/repos/{repo}/issues/{number}")
        issue = resp.json()
        comments: list[dict] = []
        if listed.get("comments", 0):
            comments = await _paginate(
                client, f"{API_ROOT}/repos/{repo}/issues/{number}/comments", {}
            )
        issue["comments"] = comments

    with open(out, "w", encoding="utf-8") as f:
        json.dump(issue, f)


async def _download(repo: str, out_dir: str, force: bool = False) -> None:
    token = os.environ["GITHUB_TOKEN"]
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    os.makedirs(out_dir, exist_ok=True)

    async with httpx2.AsyncClient(http2=True, headers=headers, timeout=30.0) as client:
        print(f"Listing issues for {repo}...", file=sys.stderr)
        issues = await _paginate(client, f"{API_ROOT}/repos/{repo}/issues", {"state": "all"})
        # The issues endpoint also returns PRs; drop them.
        issues = [it for it in issues if "pull_request" not in it]
        total = len(issues)
        print(f"Found {total} issues. Downloading full content...", file=sys.stderr)

        # Decide which issues need (re)fetching before firing off requests.
        pending: list[tuple[dict, str]] = []
        new_count = 0
        refreshed_count = 0
        for listed in issues:
            number = listed["number"]
            out = os.path.join(out_dir, f"issue-{number}.json")
            if not force and os.path.exists(out):
                stored = _stored_updated_at(out)
                # Skip only when the local copy is at least as recent as the
                # listing; a newer listing means the issue changed and is refetched.
                if stored is not None and stored >= listed.get("updated_at", ""):
                    continue
                refreshed_count += 1
            else:
                new_count += 1
            pending.append((listed, out))

        # Fetch up to CONCURRENCY issues concurrently.
        sem = asyncio.Semaphore(CONCURRENCY)
        done = 0
        todo = len(pending)

        async def _run(listed: dict, out: str) -> None:
            nonlocal done
            await _fetch_issue(client, sem, repo, listed, out)
            done += 1
            print(f"\r[{done}/{todo}] issue #{listed['number']:<8}", end="", file=sys.stderr)

        await asyncio.gather(*(_run(listed, out) for listed, out in pending))

    print(
        f"\nDone. {new_count} new, {refreshed_count} refreshed. Issue JSON files are in {out_dir}",
        file=sys.stderr,
    )


def download(repo: str, out_dir: str, force: bool = False) -> None:
    asyncio.run(_download(repo, out_dir, force=force))


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--repo", default=REPO, help=f"owner/name (default: {REPO})")
    parser.add_argument("--out", default=None, help="output dir (default: per-repo cache)")
    parser.add_argument("--force", action="store_true", help="re-download existing issues")
    args = parser.parse_args()

    # DATA_DIR is derived from ISSUE_REPO; if --repo differs, honor it explicitly.
    out_dir = args.out or (
        DATA_DIR
        if args.repo == REPO
        else os.path.join(
            os.path.dirname(os.path.dirname(DATA_DIR)), args.repo.replace("/", "__"), "data"
        )
    )
    download(args.repo, out_dir, force=args.force)


if __name__ == "__main__":
    main()
