"""Download the latest issues/PRs and rebuild the vector store in one step.

Runs ``issuestore download`` followed by ``issuestore build`` against the same
repository, which is the usual pair: the download refreshes the JSON cache in
``config.DATA_DIR`` and the build (re-)embeds whatever changed. Both stages are
incremental, so a refresh with nothing new costs one GraphQL scan and no GPU
work.

Unlike ``download``, this takes no ``--repo``/``--out``: the build stage reads
``config.DATA_DIR``, so both stages must agree on the target. Use ``ISSUE_REPO``
to point the whole process at another repository.

Examples::

    issuestore refresh
    issuestore refresh --no-prs
    issuestore refresh --force          # re-download and re-embed everything
    ISSUE_REPO=holoviz/panel issuestore refresh
"""

from __future__ import annotations

import argparse
import sys

from issuestore.config import DATA_DIR, REPO, get_collection, get_embedder
from issuestore.ingest.build_db import build, run_tests
from issuestore.ingest.download import download


def refresh(
    force: bool = False,
    include_prs: bool = True,
    full_scan: bool = False,
    test: bool = False,
) -> None:
    download(REPO, DATA_DIR, force=force, include_prs=include_prs, full_scan=full_scan)

    # `get_embedder` loads the model onto the GPU, so it is called only after
    # the download has actually succeeded.
    print(f"\nBuilding collection for {REPO}...", file=sys.stderr)
    embedder = get_embedder()
    collection = get_collection(create=True)
    build(collection, force=force, include_prs=include_prs)
    if test:
        run_tests(collection, embedder)


def main() -> None:
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
    args = parser.parse_args()

    refresh(
        force=args.force,
        include_prs=not args.no_prs,
        full_scan=args.full_scan,
        test=args.test,
    )


if __name__ == "__main__":
    main()
