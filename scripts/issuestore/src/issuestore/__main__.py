from __future__ import annotations

import sys

from issuestore.cli import main

if sys.stdout.isatty():
    GREEN, RED, RESET, CLEAR = "\033[0;32m", "\033[0;31m", "\033[0m", "\033[F\033[K"
else:
    GREEN = RED = RESET = CLEAR = ""


def custom_excepthook(exctype, value, traceback):
    if exctype is KeyboardInterrupt:
        print(f"\n{RED}Aborted.{RESET}")
        sys.exit(1)
    elif exctype is KeyError and value.args[0] == "GITHUB_TOKEN":
        print(f"{RED}`GITHUB_TOKEN` environment variable not set.{RESET}")
        sys.exit(1)
    else:
        sys.__excepthook__(exctype, value, traceback)


sys.excepthook = custom_excepthook

if __name__ == "__main__":
    raise SystemExit(main())
