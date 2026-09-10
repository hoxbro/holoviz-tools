"""Print a single issue's raw data straight from the local cache.

The downloader stores one ``issue-<n>.json`` per issue under the per-repo cache
(``config.DATA_DIR``); this reads that file back so you can inspect an issue's
title, body, labels, and comments without another GitHub round-trip. The other
commands (``query``, ``serve``) only surface metadata, so this is the way to get
at the full raw content that is already sitting on disk.

Examples::

    issuestore show 5361            # human-readable summary (title, body, comments)
    issuestore show 5361 --json     # the full raw issue JSON, as downloaded
    issuestore show 5361 --repo bokeh/bokeh
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from issuestore.config import REPO, data_dir_for


def issue_path(number: int, repo: str = REPO) -> str:
    """Absolute path of the cached raw JSON for ``number`` in ``repo``."""
    return os.path.join(data_dir_for(repo), f"issue-{number}.json")


def load_issue(number: int, repo: str = REPO) -> dict:
    """Load the raw issue object from the cache, or exit with a helpful message."""
    path = issue_path(number, repo)
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        msg = (
            f"No cached data for issue #{number} at {path}.\n"
            f"Run `issuestore download` first (repo: {repo})."
        )
        raise SystemExit(msg) from None
    except (OSError, json.JSONDecodeError) as exc:
        msg = f"Could not read {path}: {exc}"
        raise SystemExit(msg) from exc


def _comment_list(issue: dict) -> list[dict]:
    """Flatten the comments list, handling the double-nested slurp shape."""
    comments = issue.get("comments")
    if isinstance(comments, list) and comments and isinstance(comments[0], list):
        comments = comments[0]
    return [c for c in (comments or []) if isinstance(c, dict)]


def format_issue(issue: dict) -> str:
    """Render a readable summary: header fields, body, then non-empty comments."""
    labels = ", ".join(
        l.get("name", "") for l in (issue.get("labels") or []) if isinstance(l, dict)
    )
    lines = [
        f"#{issue.get('number')} {issue.get('title') or ''}",
        f"state:   {issue.get('state') or ''}",
        f"labels:  {labels or '-'}",
        f"author:  {(issue.get('user') or {}).get('login') or '-'}",
        f"created: {issue.get('created_at') or '-'}",
        f"url:     {issue.get('html_url') or '-'}",
        "",
        (issue.get("body") or "").strip() or "(no description)",
    ]
    comments = _comment_list(issue)
    if comments:
        lines.append(f"\n--- {len(comments)} comment(s) ---")
        for c in comments:
            author = (c.get("user") or {}).get("login") or "unknown"
            body = (c.get("body") or "").strip()
            lines.append(f"\n[{author}] {c.get('created_at') or ''}\n{body}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("number", type=int, help="issue number to show")
    parser.add_argument("--repo", default=REPO, help=f"owner/name (default: {REPO})")
    parser.add_argument(
        "--json", action="store_true", help="print the full raw issue JSON instead of a summary"
    )
    args = parser.parse_args()

    issue = load_issue(args.number, args.repo)
    if args.json:
        json.dump(issue, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print(format_issue(issue))


if __name__ == "__main__":
    main()
