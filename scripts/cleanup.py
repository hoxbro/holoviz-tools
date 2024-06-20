#!/usr/bin/env python

from __future__ import annotations

import os
import re
from contextlib import suppress
from functools import cache
from pathlib import Path
from shutil import move, rmtree
from subprocess import check_output

import httpx
from bs4 import BeautifulSoup
from rich.console import Console
from utilities import clean_exit, trackpool

console = Console()
PATH = Path(os.environ["HOLOVIZ_DEV"]).resolve() / "development"

# Not needed but makes it faster
HEADERS = {
    "Accept": "application/vnd.github+json",
    "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
    "X-GitHub-Api-Version": "2022-11-28",
}


def remove_temp() -> None:
    files = PATH.parent.glob("*.ipynb")
    for file in files:
        with suppress(Exception):
            move(file, PATH)

    tmps = [
        ".ipynb_checkpoints",
        "Untitled*.ipynb",
        "tmp*.py",
        "temp*.py",
        "untitled*.txt",
        ".benchmarks",
        ".hypothesis",
        ".pytest_cache",
        "__pycache__",
        ".mypy_cache",
        "log*.txt",
        "cache",
        ".ruff_cache",
    ]

    for tmp in tmps:
        for f in PATH.rglob(tmp):
            if f.is_file():
                f.unlink()
            else:
                rmtree(f)

            console.print(
                f"Removed {f.relative_to(PATH)}",
                style="bright_black",
            )


@cache
def check_pr_closed(repo, no) -> bool:
    # Use API
    url = f"https://api.github.com/repos/holoviz/{repo}/issues/{no}"
    resp = httpx.get(url, headers=HEADERS)
    with suppress(httpx.HTTPError):
        tag = resp.raise_for_status().json()["state"]
        return tag in ["closed", "merged"]

    # Else Web-Scraping
    url = f"https://github.com/holoviz/{repo}/issues/{no}"
    resp = httpx.get(url, follow_redirects=True).raise_for_status()

    soup = BeautifulSoup(resp.text, features="html.parser")
    tag = soup.find(class_="State").text.strip().lower()
    return tag in ["closed", "merged"]


def archive() -> None:
    repos = sorted(PATH.glob("dev_*"))

    checks, srcs, dsts = [], [], []
    for repo_path in repos:
        repo = repo_path.name.replace("dev_", "")
        paths = repo_path.glob("*")

        for path in sorted(paths):
            if "archive" in path.name:
                continue

            digit = re.search(r"^\d+", path.name)
            if digit is None:
                console.print(
                    f"Not able to associate PR for {path.relative_to(PATH)}",
                    style="bright_black",
                )
                # maybe look in path for url
                continue

            no = digit.group(0)
            checks.append((repo, no))

            srcs.append(path)
            dsts.append(repo_path / "archive" / path.relative_to(repo_path))

    futures = trackpool(lambda x: check_pr_closed(*x), checks, "Checking files")

    for closed, (repo, no), src, dst in zip(futures, checks, srcs, dsts, strict=True):
        if closed:
            dst.parent.mkdir(exist_ok=True)
            move(src, dst)
            console.print(
                f"{repo} #{no} closed, archiving {src.relative_to(PATH)}",
                style="bright_black",
            )


def clean_notebooks() -> None:
    output = check_output(["clean-notebook", "-s", "."], cwd=PATH)
    console.print(output.decode(), style="bright_black")


def title(msg) -> None:
    print()
    console.print(msg, style="green")


@clean_exit
def main():
    title("Removing temporary files and directories")
    remove_temp()

    title("Archiving closed issues")
    archive()

    title("Cleaning notebooks")
    clean_notebooks()


if __name__ == "__main__":
    main()
