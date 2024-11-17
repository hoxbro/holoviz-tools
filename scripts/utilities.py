from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
from subprocess import run
from typing import Never

from rich.progress import track

if sys.stdout.isatty():
    GREEN, RED, RESET = "\033[0;32m", "\033[0;31m", "\033[0m"
else:
    GREEN = RED = RESET = ""


def exit_print(x) -> Never:
    print(f"{RED}{x}{RESET}")
    sys.exit(1)


def git(*args, **kwargs) -> str:
    return run(["git", *args], check=True, capture_output=True, **kwargs).stdout.strip().decode()


def trackpool(func, iterable, description) -> list:
    with ThreadPoolExecutor() as executor:
        futures = list(
            track(
                executor.map(func, iterable),
                description=description,
                total=len(iterable),
                transient=True,
            )
        )
    return futures
