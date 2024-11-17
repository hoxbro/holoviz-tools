from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from functools import cache
from io import BytesIO
from pathlib import Path
from shutil import rmtree
from zipfile import ZipFile

import httpx
import platformdirs
from rich.console import Console
from rich.live import Live

from rich_menu import live_menu, menu
from utilities import exit_print

ARTIFACT_PATH = platformdirs.user_cache_path() / "holoviz-cli" / "artifact"
ARTIFACT_PATH.mkdir(parents=True, exist_ok=True)

HEADERS = {
    "Accept": "application/vnd.github+json",
    "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
    "X-GitHub-Api-Version": "2022-11-28",
}
console = Console()


@cache
def download_runs(repo, workflow, page=1) -> tuple[dict, dict]:
    url = f"https://api.github.com/repos/holoviz/{repo}/actions/workflows/{workflow}/runs"
    resp = httpx.get(
        url, params={"page": page, "per_page": 30}, headers=HEADERS, timeout=20
    ).raise_for_status()

    results, urls = {}, {}
    for run in resp.json()["workflow_runs"]:
        no = run["run_number"]
        date = datetime.fromisoformat(run["created_at"])
        display = f"{no:<5} {run['conclusion'] or 'running':<13} {date:%Y-%m-%d %H:%M}    branch: {run['head_branch']} "
        results[no] = display
        urls[no] = run["url"] + "/artifacts"

    return results, urls


def select_run(repo, workflow) -> tuple[int, int]:
    with console.status(f"Fetching runs for {repo}..."):
        runs, _ = download_runs(repo, workflow, 1)

    run = live_menu(runs, title=f"Select a run for [bold]{repo}[/bold]", console=console)
    return run


def select_runs(repo, workflow) -> tuple[int, int]:
    with console.status(f"Fetching runs for {repo}..."):
        runs, _ = download_runs(repo, workflow, 1)

    with Live(console=console, transient=True) as live:
        good_run = menu(
            runs,
            live=live,
            title=f"Select a [green bold]good run[/green bold] for [bold]{repo}[/bold]",
        )
        del runs[good_run]

        bad_run = menu(
            runs,
            live=live,
            title=f"Select a [red bold]bad run[/red bold] for [bold]{repo}[/bold]",
            select_style="red bold",
        )
    return good_run, bad_run


def get_artifact_urls(repo, workflow, good_run, bad_run) -> tuple[str, str] | None:
    good_url, bad_url = None, None
    for page in range(1, 10):
        _, urls = download_runs(repo, workflow, page)
        if good_run in urls:
            good_url = urls[good_run]
        if bad_run in urls:
            bad_url = urls[bad_run]
        if good_url and bad_url:
            return good_url, bad_url


def get_artifact_data_url(download_path, url, artifact_names) -> list[tuple[str, str]]:
    if download_path.exists():
        return []

    resp = httpx.get(url, headers=HEADERS).raise_for_status()
    artifact = resp.json()["artifacts"]
    if not artifact:
        download_path.mkdir(exist_ok=True)
        return []
    if artifact_names:
        download_urls = [
            (download_path, a["archive_download_url"])
            for a in artifact
            if a["name"] in artifact_names
        ]
    else:
        download_urls = [(download_path, artifact[0]["archive_download_url"])]
    return download_urls


def download_url(download_path, download_url) -> None:
    zipfile = httpx.get(download_url, headers=HEADERS, follow_redirects=True).raise_for_status()
    bio = BytesIO(zipfile.content)
    bio.seek(0)
    with ZipFile(bio) as zip_ref:
        zip_ref.extractall(download_path)


def download_file(
    repo, run, workflow, *, force=False, artifact_names=None
) -> tuple[tuple[int, int], Path]:
    if run is None:
        run = select_run(repo, workflow)
        console.print(f"Selected: [green]Run {run}[/green]")

    path = ARTIFACT_PATH / f"{repo}_{workflow.split('.')[0]}_{run}"

    if force:
        rmtree(path, ignore_errors=True)

    if not path.exists():
        with console.status("Downloading artifacts..."):
            runs = get_artifact_urls(repo, workflow, run, run)
            if runs is None:
                exit_print("No artifacts found")
            good_url, _ = runs
            artifact_urls = get_artifact_data_url(path, good_url, artifact_names)
            with ThreadPoolExecutor() as executor:
                executor.map(lambda x: download_url(*x), artifact_urls)

    return run, path


def download_files(
    repo, good_run, bad_run, workflow, *, force=False, artifact_names=None
) -> tuple[int, int, Path, Path]:
    if good_run is None or bad_run is None:
        good_run, bad_run = select_runs(repo, workflow)
        console.print(
            f"Selected: [green]Good run {good_run}[/green] and [red]bad run {bad_run}[/red]"
        )

    good_path = ARTIFACT_PATH / f"{repo}_{workflow.split('.')[0]}_{good_run}"
    bad_path = ARTIFACT_PATH / f"{repo}_{workflow.split('.')[0]}_{bad_run}"

    if force:
        rmtree(good_path, ignore_errors=True)
        rmtree(bad_path, ignore_errors=True)

    if not good_path.exists() or not bad_path.exists():
        with console.status("Downloading artifacts..."):
            runs = get_artifact_urls(repo, workflow, good_run, bad_run)
            if runs is None:
                exit_print("No artifacts found")
            good_url, bad_url = runs
            artifact_urls = [
                *get_artifact_data_url(good_path, good_url, artifact_names),
                *get_artifact_data_url(bad_path, bad_url, artifact_names),
            ]
            with ThreadPoolExecutor() as executor:
                executor.map(lambda x: download_url(*x), artifact_urls)

    return good_run, bad_run, good_path, bad_path
