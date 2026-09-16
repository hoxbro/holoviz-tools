"""Unified ``issuestore`` command-line entry point.

Dispatches subcommands to the standalone module ``main()`` functions so each
keeps its own flags, e.g. ``issuestore download --force``.

The target repository is auto-detected from the git remote of the invoking
directory (see ``issuestore.config``); set ``ISSUE_REPO`` to override.

Examples::

    issuestore download --force
    issuestore build
    issuestore refresh                          # download, then build
    issuestore show 5361                        # raw cached issue data, no GitHub call
    issuestore query "duplicate legend entries"
    issuestore fixed                            # open issues a merged PR likely fixed
    issuestore serve
"""

from __future__ import annotations

import importlib
import sys

# Subcommand -> module exposing a zero-arg ``main()`` that parses ``sys.argv``.
COMMANDS: dict[str, str] = {
    "download": "issuestore.ingest.download",
    "build": "issuestore.ingest.build_db",
    "refresh": "issuestore.ingest.refresh",
    "show": "issuestore.analysis.show",
    "query": "issuestore.analysis.query",
    "fixed": "issuestore.analysis.fixed",
    "cluster": "issuestore.analysis.cluster",
    "classify": "issuestore.analysis.classify",
    "visualize": "issuestore.analysis.visualize",
    "serve": "issuestore.server",
}


def _usage() -> str:
    cmds = "\n".join(f"    {name}" for name in COMMANDS)
    return f"usage: issuestore <command> [options]\n\ncommands:\n{cmds}\n"


def _serve(argv: list[str]) -> int:
    """Run the MCP server (mirrors ``python -m issuestore.server``)."""
    server = importlib.import_module("issuestore.server")
    if "--selftest" in argv:
        server._selftest()
    else:
        server.mcp.run()
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    if not argv or argv[0] in ("-h", "--help"):
        sys.stdout.write(_usage())
        return 0 if argv else 1

    cmd, rest = argv[0], argv[1:]
    if cmd not in COMMANDS:
        sys.stderr.write(f"issuestore: unknown command {cmd!r}\n\n{_usage()}")
        return 2

    # Delegated argparse reads sys.argv; make it see the right prog + args so
    # ``issuestore <cmd> --help`` renders correctly.
    sys.argv = [f"issuestore {cmd}", *rest]

    if cmd == "serve":
        return _serve(rest) or 0

    module = importlib.import_module(COMMANDS[cmd])
    return module.main() or 0


if __name__ == "__main__":
    raise SystemExit(main())
