"""Download the latest issues/PRs and rebuild the vector store in one step.

Runs ``issuestore download`` followed by ``issuestore build`` against the same
repository, which is the usual pair: the download refreshes the JSON cache in
``config.DATA_DIR`` and the build (re-)embeds whatever changed. Both stages are
incremental, so a refresh with nothing new costs one GraphQL scan and no GPU
work.

Unlike ``download``, this takes no ``--repo``/``--out``: the build stage reads
``config.DATA_DIR``, so both stages must agree on the target. Use ``ISSUE_REPO``
to point the whole process at another repository, or ``--all`` to refresh
every supported repository in turn (each in its own subprocess).

Examples::

    issuestore refresh
    issuestore refresh --no-prs
    issuestore refresh --force          # re-download and re-embed everything
    ISSUE_REPO=holoviz/panel issuestore refresh
    issuestore refresh --all
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

from issuestore.repos import REPOS


def refresh(
    force: bool = False,
    include_prs: bool = True,
    full_scan: bool = False,
    test: bool = False,
) -> None:
    # Imported lazily: `config` resolves the target repo at import, which must
    # not happen in the `--all` parent process.
    from issuestore.config import DATA_DIR, REPO, get_collection, get_embedder  # noqa: PLC0415
    from issuestore.ingest.build_db import build, run_tests  # noqa: PLC0415
    from issuestore.ingest.download import download  # noqa: PLC0415

    download(REPO, DATA_DIR, force=force, include_prs=include_prs, full_scan=full_scan)

    # `get_embedder` loads the model onto the GPU, so it is called only after
    # the download has actually succeeded.
    print(f"\nBuilding collection for {REPO}...", file=sys.stderr)
    embedder = get_embedder()
    collection = get_collection(create=True)
    build(collection, force=force, include_prs=include_prs)
    if test:
        run_tests(collection, embedder)


def refresh_all(argv: list[str]) -> int:
    """Refresh every supported repo, continuing past failures; return an exit code."""
    failed = []
    for repo in REPOS:
        print(f"\n=== {repo} ===", file=sys.stderr, flush=True)
        result = subprocess.run(
            [sys.executable, "-m", "issuestore", "refresh", *argv],
            env={**os.environ, "ISSUE_REPO": repo},
            check=False,
        )
        if result.returncode != 0:
            failed.append(repo)
    if failed:
        print(f"\nRefresh failed for: {', '.join(failed)}", file=sys.stderr)
        return 1
    return 0


def main() -> int | None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--force", action="store_true", help="re-download and re-embed every record"
    )
    parser.add_argument("--no-prs", action="store_true", help="issues only, skip PRs")
    parser.add_argument(
        "--full-scan", action="store_true", help="scan every record, ignoring the watermark"
    )
    parser.add_argument("--test", action="store_true", help="run sanity queries after the build")
    parser.add_argument(
        "--all", action="store_true", help="refresh every supported repository in turn"
    )
    args = parser.parse_args()

    if args.all:
        return refresh_all([a for a in sys.argv[1:] if a != "--all"])

    refresh(
        force=args.force,
        include_prs=not args.no_prs,
        full_scan=args.full_scan,
        test=args.test,
    )


if __name__ == "__main__":
    main()
