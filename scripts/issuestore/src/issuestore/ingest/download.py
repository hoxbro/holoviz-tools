"""Download all issues and PRs (and their comments) for a repo via the GitHub REST API.

Uses httpx and writes one ``issue-<n>.json`` per issue and one ``pr-<n>.json``
per pull request into the per-repo cache (``config.DATA_DIR``), matching the
shape ``build_db`` expects: the full object plus a ``comments`` list. For PRs
the listing's ``pull_request`` block (which carries ``merged_at``) is preserved
so merge state is known without an extra call.
The scan for *what* to fetch goes through the GraphQL API: one request lists a
page of issues *and* a page of pull requests with their ``updatedAt``, ordered
newest-first. Issues are filtered server-side by the watermark left by the last
complete run; pull requests have no such filter, so both kinds also stop as soon
as the listing reaches that watermark instead of paging the whole repository.
Re-running then fetches new records plus any whose GitHub ``updated_at`` is
newer than the local copy; unchanged records are left untouched. ``--force``
re-downloads everything, ``--full-scan`` ignores the watermark, and ``--no-prs``
restricts the pull to issues only.

Examples::

    python -m issuestore.ingest.download
    python -m issuestore.ingest.download --no-prs
    ISSUE_REPO=pandas-dev/pandas python -m issuestore.ingest.download
    python -m issuestore.ingest.download --repo bokeh/bokeh --force
    python -m issuestore.ingest.download --full-scan
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
GRAPHQL_URL = f"{API_ROOT}/graphql"
PER_PAGE = 100

# Newest ``updatedAt`` covered by the last complete run, per record kind. Lives
# beside the cached records; `build_db` only globs `issue-*`/`pr-*` so it is
# ignored there.
WATERMARK_FILE = "scan-watermark.json"

# One document covers both connections, so a scan costs a single round-trip per
# page instead of one per kind. Issues support a server-side ``since`` filter;
# ``pullRequests`` does not, so PRs rely on the watermark stop alone.
_SCAN_CONNECTIONS = {
    "issue": """
    issues(first: %(per_page)d, after: $issueCursor, filterBy: {since: $since},
           orderBy: {field: UPDATED_AT, direction: DESC}) {
      pageInfo { hasNextPage endCursor }
      nodes { number updatedAt comments { totalCount } }
    }""",
    "pr": """
    pullRequests(first: %(per_page)d, after: $prCursor,
                 orderBy: {field: UPDATED_AT, direction: DESC}) {
      pageInfo { hasNextPage endCursor }
      nodes { number updatedAt comments { totalCount } mergedAt }
    }""",
}

# GraphQL rejects declared-but-unused variables, so each kind carries its own.
_SCAN_VARIABLES = {
    "issue": ("$issueCursor: String", "$since: DateTime"),
    "pr": ("$prCursor: String",),
}

_SCAN_FIELD = {"issue": "issues", "pr": "pullRequests"}
_SCAN_CURSOR_VAR = {"issue": "issueCursor", "pr": "prCursor"}


def _scan_query(kinds: tuple[str, ...]) -> str:
    """Build a scan query covering exactly ``kinds``."""
    params = ", ".join(
        ["$owner: String!", "$name: String!", *(v for k in kinds for v in _SCAN_VARIABLES[k])]
    )
    body = "".join(_SCAN_CONNECTIONS[k] % {"per_page": PER_PAGE} for k in kinds)
    return f"query({params}) {{\n  repository(owner: $owner, name: $name) {{{body}\n  }}\n}}\n"


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


async def _graphql(client: httpx2.AsyncClient, query: str, variables: dict) -> dict:
    """POST a GraphQL query and return its ``data`` block.

    GraphQL reports failures in the body of a 200 response, so the payload is
    inspected instead of relying on the status code alone.
    """
    for attempt in range(6):
        resp = await client.post(GRAPHQL_URL, json={"query": query, "variables": variables})
        if resp.status_code in (429, 502, 503):
            await asyncio.sleep(int(resp.headers.get("retry-after", 2**attempt)))
            continue
        resp.raise_for_status()
        payload = resp.json()
        errors = payload.get("errors") or []
        if any(e.get("type") == "RATE_LIMITED" for e in errors):
            reset = int(resp.headers.get("x-ratelimit-reset", "0"))
            delay = max(reset - int(time.time()), 1)
            print(f"\n  rate limited; sleeping {delay}s...", file=sys.stderr)
            await asyncio.sleep(delay)
            continue
        if errors:
            msg = f"GraphQL error: {errors}"
            raise RuntimeError(msg)
        return payload["data"]
    msg = "GraphQL scan failed after 6 attempts"
    raise RuntimeError(msg)


async def _scan(
    client: httpx2.AsyncClient, repo: str, kinds: tuple[str, ...], watermarks: dict[str, str]
) -> dict[str, tuple[list[dict], bool]]:
    """List every kind in ``kinds`` newest-first, one page of each per request.

    Returns ``{kind: (listed, stopped_early)}``. Each entry carries only what
    the download path needs: ``number``, ``updated_at``, the comment count (to
    skip the comments call for records with none) and, for PRs, the
    ``pull_request`` block holding ``merged_at``.

    Issues are filtered server-side by ``filterBy: {since: ...}``; PRs have no
    such filter, so both kinds also stop client-side once the listing -- ordered
    by ``updatedAt`` descending -- reaches the watermark left by the last
    complete run. The comparison is strict rather than ``<=`` so that records
    sharing the watermark's second are re-listed; GitHub truncates timestamps to
    seconds, and one updated within the same second the previous scan ran would
    otherwise be skipped forever. ``filterBy.since`` is inclusive, so it keeps
    those same records in the result.

    A kind drops out of the query once it is exhausted, so a run that has caught
    up on issues keeps paging PRs without re-requesting issue pages.
    """
    owner, name = repo.split("/", 1)
    listed: dict[str, list[dict]] = {k: [] for k in kinds}
    stopped_early = dict.fromkeys(kinds, False)
    cursors: dict[str, str | None] = dict.fromkeys(kinds)
    active = list(kinds)
    while active:
        variables: dict[str, str | None] = {"owner": owner, "name": name}
        for kind in active:
            variables[_SCAN_CURSOR_VAR[kind]] = cursors[kind]
            if kind == "issue":
                variables["since"] = watermarks.get("issue")
        data = await _graphql(client, _scan_query(tuple(active)), variables)
        for kind in list(active):
            conn = data["repository"][_SCAN_FIELD[kind]]
            watermark = watermarks.get(kind)
            reached_watermark = False
            for node in conn["nodes"]:
                updated_at = node["updatedAt"]
                if watermark and updated_at < watermark:
                    reached_watermark = True
                    break
                rec = {
                    "number": node["number"],
                    "updated_at": updated_at,
                    "comments": node["comments"]["totalCount"],
                }
                if kind == "pr":
                    rec["pull_request"] = {"merged_at": node["mergedAt"]}
                listed[kind].append(rec)
            if reached_watermark:
                stopped_early[kind] = True
                active.remove(kind)
            elif conn["pageInfo"]["hasNextPage"]:
                cursors[kind] = conn["pageInfo"]["endCursor"]
            else:
                active.remove(kind)
    return {k: (listed[k], stopped_early[k]) for k in kinds}


def _load_watermarks(out_dir: str) -> dict[str, str]:
    try:
        with open(os.path.join(out_dir, WATERMARK_FILE), encoding="utf-8") as f:
            return json.load(f)
    except OSError, ValueError:
        return {}


def _save_watermarks(out_dir: str, marks: dict[str, str]) -> None:
    with open(os.path.join(out_dir, WATERMARK_FILE), "w", encoding="utf-8") as f:
        json.dump(marks, f)


def _stored_updated_at(path: str) -> str | None:
    """Return the scan timestamp of a previously downloaded record, if readable.

    Prefers ``scan_updated_at`` -- the value the GraphQL scan reported when the
    record was last written -- because for PRs GraphQL's ``updatedAt`` tracks
    the pull-request record while REST's ``updated_at`` tracks the underlying
    issue, and the former runs ahead (PR-only events such as a branch deletion
    bump it alone). Comparing across the two clocks would mark those PRs stale
    on every run. Records cached before that key existed fall back to
    ``updated_at`` and settle after one refetch.

    GitHub timestamps are ISO 8601 UTC (``...Z``), so lexical comparison of two
    such strings matches chronological order.
    """
    try:
        with open(path, encoding="utf-8") as f:
            stored = json.load(f)
    except OSError, ValueError:
        return None
    return stored.get("scan_updated_at") or stored.get("updated_at")


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

    # Preserve the listing's pull_request block (carries merged_at) so build_db
    # can tell merged PRs apart without a second round-trip.
    if "pull_request" in listed and not issue.get("pull_request"):
        issue["pull_request"] = listed["pull_request"]

    # Stamp the scan's own timestamp so the next run compares like with like.
    issue["scan_updated_at"] = listed["updated_at"]

    with open(out, "w", encoding="utf-8") as f:
        json.dump(issue, f)


async def _download(
    repo: str,
    out_dir: str,
    force: bool = False,
    include_prs: bool = True,
    full_scan: bool = False,
) -> None:
    token = os.environ["GITHUB_TOKEN"]
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    os.makedirs(out_dir, exist_ok=True)

    async with httpx2.AsyncClient(http2=True, headers=headers, timeout=30.0) as client:
        # A single GraphQL document pages both connections, and --no-prs drops
        # the PR connection from it outright.
        stored_marks = _load_watermarks(out_dir)
        scan_from = {} if force or full_scan else stored_marks
        kinds = ("issue", "pr") if include_prs else ("issue",)
        print(f"Scanning {' and '.join(f'{k}s' for k in kinds)} for {repo}...", file=sys.stderr)
        scanned = await _scan(client, repo, kinds, scan_from)
        records: list[tuple[dict, str]] = []
        newest: dict[str, str] = {}
        for kind in kinds:
            listed, stopped_early = scanned[kind]
            records.extend((rec, kind) for rec in listed)
            # `listed` is newest-first, so its head is the high-water mark.
            newest[kind] = max(
                (listed[0]["updated_at"] if listed else ""), stored_marks.get(kind, "")
            )
            scope = "changed since last run" if stopped_early else "total"
            print(f"  {len(listed)} {kind}s ({scope})", file=sys.stderr)
        print("Downloading full content...", file=sys.stderr)

        # Decide which records need (re)fetching before firing off requests.
        pending: list[tuple[dict, str]] = []
        new_count = 0
        refreshed_count = 0
        for listed, kind in records:
            number = listed["number"]
            out = os.path.join(out_dir, f"{kind}-{number}.json")
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
            print(f"\r[{done}/{todo}] #{listed['number']:<8}", end="", file=sys.stderr)

        await asyncio.gather(*(_run(listed, out) for listed, out in pending))

        # Only advance the watermark once every pending fetch has landed; an
        # interrupted run leaves the old mark so the next scan re-covers it.
        _save_watermarks(out_dir, {**stored_marks, **{k: v for k, v in newest.items() if v}})

    print(
        f"\nDone. {new_count} new, {refreshed_count} refreshed. JSON files are in {out_dir}",
        file=sys.stderr,
    )


def download(
    repo: str,
    out_dir: str,
    force: bool = False,
    include_prs: bool = True,
    full_scan: bool = False,
) -> None:
    asyncio.run(
        _download(repo, out_dir, force=force, include_prs=include_prs, full_scan=full_scan)
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--repo", default=REPO, help=f"owner/name (default: {REPO})")
    parser.add_argument("--out", default=None, help="output dir (default: per-repo cache)")
    parser.add_argument("--force", action="store_true", help="re-download existing records")
    parser.add_argument("--no-prs", action="store_true", help="download issues only, skip PRs")
    parser.add_argument(
        "--full-scan", action="store_true", help="scan every record, ignoring the watermark"
    )
    args = parser.parse_args()

    # DATA_DIR is derived from ISSUE_REPO; if --repo differs, honor it explicitly.
    out_dir = args.out or (
        DATA_DIR
        if args.repo == REPO
        else os.path.join(
            os.path.dirname(os.path.dirname(DATA_DIR)), args.repo.replace("/", "__"), "data"
        )
    )
    download(
        args.repo,
        out_dir,
        force=args.force,
        include_prs=not args.no_prs,
        full_scan=args.full_scan,
    )


if __name__ == "__main__":
    main()
