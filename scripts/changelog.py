from __future__ import annotations

import os
import re
import shutil
import sqlite3
import tempfile
from functools import partial
from pathlib import Path

import httpx
import rich_click as click
from pandas.io.clipboard import clipboard_set
from rich.console import Console
from rich.markdown import Markdown

from rich_menu import argument_menu, live_menu

HEADERS = {
    "Accept": "application/vnd.github+json",
    "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
    "X-GitHub-Api-Version": "2022-11-28",
}
REPOS = ["holoviews", "panel", "hvplot", "datashader", "geoviews", "lumen"]
console = Console()


def get_session_id() -> str:
    # https://github.com/yt-dlp/yt-dlp/blob/c39358a54bc6675ae0c50b81024e5a086e41656a/yt_dlp/cookies.py#l117
    firefox_dir = Path("~/.librewolf").expanduser()
    profile = next(firefox_dir.rglob("cookies.sqlite"))

    with tempfile.TemporaryDirectory() as tmpdir:
        file = shutil.copy(profile, tmpdir)

        conn = sqlite3.connect(file)
        c = conn.cursor()
        c.execute(
            "SELECT value FROM moz_cookies WHERE name = 'user_session' and host = 'github.com'"
        )
        session_id = c.fetchone()[0]
        conn.close()
        return session_id


def get_changelog(owner, repo, previous_release, branch="main"):
    url = f"https://github.com/{owner}/{repo}/releases/notes?commitish={branch}&tag_name={branch}&previous_tag_name={previous_release}"
    headers = {
        "Accept": "application/json",
        "Cookie": f"user_session={get_session_id()}",
    }
    with httpx.Client() as client:
        response = client.get(url, headers=headers)
        response.raise_for_status()

    body = response.json()["body"]
    users = set()
    body = re.sub(r"\*(.+?) by (@.+?) in (.+?)\n", partial(update_message, users=users), body)
    body += f'\n\n Contributors: {", ".join(sorted(users, key=lambda x: x.lower()))}'
    return body


def update_message(match, users):
    users.add(match.group(2))
    text = match.group(1).strip()
    text = text[0].upper() + text[1:]
    commit = match.group(3)
    commit_no = commit.split("/")[-1]
    msg = f"- {text} ([#{commit_no}]({commit}))\n"
    return msg


def get_releases(owner, repo):
    url = f"https://api.github.com/repos/{owner}/{repo}/releases"

    with httpx.Client() as client:
        response = client.get(url, headers=HEADERS)
        response.raise_for_status()
    tags = [r["tag_name"] for r in response.json()]
    return tags


@click.command(context_settings={"show_default": True})
@argument_menu(
    "repo",
    console=console,
    choices=REPOS,
    title="Select a repo to generate changelog for",
)
@click.argument("use_latest", type=bool, default=True)
@click.argument("branch", type=str, default="main")
def cli(repo, use_latest, branch) -> None:
    owner = "holoviz"
    releases = get_releases(owner, repo)
    if use_latest:
        release = releases[0]
    else:
        release = live_menu(
            releases,
            console=console,
            title="Select a previous release to generate changelog from",
        )
    with console.status(
        f"Generating changelog for {repo} for latest release {release} to {branch}..."
    ):
        text = get_changelog(owner, repo, release, branch)

    clipboard_set(text)
    console.print(Markdown(text))
    console.print("\nChangelog copied to clipboard", style="italic white")


if __name__ == "__main__":
    cli()
