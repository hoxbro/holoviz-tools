from __future__ import annotations

import asyncio
import os
import re
from collections import defaultdict
from textwrap import dedent

import httpx
import rich_click as click
from pandas.io.clipboard import clipboard_set
from rich.console import Console
from rich.markdown import Markdown
from rich_menu import live_menu

HEADERS = {
    "Accept": "application/vnd.github+json",
    "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
    "X-GitHub-Api-Version": "2022-11-28",
}
REPOS = ["holoviews", "panel", "hvplot", "datashader", "geoviews", "lumen"]
LABELS = {
    "type: feature": "New features",
    "type: enhancement": "Enhancements",
    "type: bug": "Bug fixes",
    "type: compatibility": "Compatibility",
    "type: docs": "Documentation",
    "type: maintenance": "Maintenance",
    None: "Other",
}

console = Console()
no_re = re.compile(r"\(#(\d*)\)$")


def clean_message(msg):
    msg = msg.strip()
    return msg[0].upper() + msg[1:]


def get_latest_release(owner, repo):
    url = f"https://api.github.com/repos/{owner}/{repo}/releases/latest"

    with httpx.Client() as client:
        response = client.get(url, headers=HEADERS)
        response.raise_for_status()

    return response.json()["tag_name"]


def get_commits_since_last_release(owner, repo, head):
    url = f"https://api.github.com/repos/{owner}/{repo}/compare/{head}...main"

    with httpx.Client() as client:
        response = client.get(url, headers=HEADERS)
        raw = response.raise_for_status().json()["commits"]

    commits = {
        int(no.group(1)): msg
        for c in raw
        if (no := no_re.search(msg := c["commit"]["message"]))
    }
    return commits


async def get_commit_info(owner, repo, pull_request_number):
    url = f"https://api.github.com/repos/{owner}/{repo}/issues/{pull_request_number}"
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=HEADERS)
        data = response.raise_for_status().json()

    user = "@" + data["user"]["login"]
    label = None
    for l in data["labels"]:
        if l["name"] in LABELS:
            label = l["name"]
            break

    return user, label


async def get_changelog(owner, repo, release):
    commits = get_commits_since_last_release(owner, repo, release)

    info = await asyncio.gather(*[get_commit_info(owner, repo, c) for c in commits])

    users = set()
    labels = defaultdict(list)

    for v, (user, label) in zip(commits.values(), info):
        labels[label].append(v)
        users.add(user)

    text = f"""
    Users: {", ".join(sorted(users, key=lambda x: x.lower()))}

    """
    text = dedent(text)

    for label, title in LABELS.items():
        text += f"{title}:\n"
        if msg := labels[label]:
            text += "- " + "\n- ".join(map(clean_message, msg))
        text += "\n\n"

    text = re.sub(
        r"\(#(\d*)\)",
        lambda x: f"([#{x.group(1)}](https://github.com/{owner}/{repo}/pull/{x.group(1)}))",
        text,
    )
    return text


@click.command(context_settings={"show_default": True})
@click.argument("repo", type=click.Choice(REPOS), required=False)
def cli(repo) -> None:
    if repo is None:
        repo = live_menu(
            REPOS, console=console, title="Select a repo to generate changelog for"
        )

    owner = "holoviz"
    latest_release = get_latest_release(owner, repo)

    with console.status(
        f"Generating changelog for {repo} for latest relase {latest_release} to now..."
    ):
        text = asyncio.run(get_changelog(owner, repo, latest_release))

    console.print(Markdown(text))
    clipboard_set(text)
    console.print("\nChangelog copied to clipboard", style="italic white")


if __name__ == "__main__":
    cli()
