from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor

from rich.progress import track

GREEN, RED, RESET = "\033[0;32m", "\033[0;31m", "\033[0m"


def clean_exit(f):
    def wrapper(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except KeyboardInterrupt:
            print(f"{RED}Aborted{RESET}")
            sys.exit(1)

    return wrapper


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
