from __future__ import annotations

import os
import sys
from datetime import datetime
from functools import cache
from io import BytesIO
from pathlib import Path
from shutil import rmtree
from zipfile import ZipFile

import httpx
import rich_click as click
import yaml
from pandas.io.clipboard import clipboard_set
from rich.console import Console
from rich.live import Live
from rich.table import Table
from rich_menu import argument_menu, menu

# Needs diff-so-fancy in path

PATH = Path("~/.cache/holoviz-cli/artifact").expanduser().resolve()
PATH.mkdir(parents=True, exist_ok=True)

HEADERS = {
    "Accept": "application/vnd.github+json",
    "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
    "X-GitHub-Api-Version": "2022-11-28",
}
REPOS = ["holoviews", "panel", "hvplot", "datashader", "geoviews", "lumen"]
console = Console()


@cache
def download_runs(repo, workflow, page=1) -> tuple[dict, dict]:
    url = f"https://api.github.com/repos/holoviz/{repo}/actions/workflows/{workflow}/runs"
    resp = httpx.get(
        url, params={"page": page, "per_page": 30}, headers=HEADERS, timeout=20
    ).raise_for_status()

    results, urls = {}, {}
    for run in resp.json()["workflow_runs"]:
        if run["status"] == "completed" and run["conclusion"] != "action_required":
            no = run["run_number"]
            date = datetime.fromisoformat(run["created_at"])
            display = f"{no:<5} {run['conclusion']:<13} {date:%Y-%m-%d %H:%M}    branch: {run['head_branch']} "
            results[no] = display
            urls[no] = run["url"] + "/artifacts"

    return results, urls


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


def download_artifact(repo, run, url) -> None:
    download_path = PATH / f"{repo}_{run}"
    if download_path.exists():
        return

    resp = httpx.get(url, headers=HEADERS).raise_for_status()
    artifact = resp.json()["artifacts"]
    if not artifact:
        download_path.mkdir(exist_ok=True)
        return
    download_url = artifact[0]["archive_download_url"]
    zipfile = httpx.get(download_url, headers=HEADERS, follow_redirects=True).raise_for_status()
    bio = BytesIO(zipfile.content)
    bio.seek(0)
    with ZipFile(bio) as zip_ref:
        zip_ref.extractall(download_path)


def get_files(repo, good_run, bad_run, workflow, force) -> tuple[Path | None, Path | None]:
    if good_run is None or bad_run is None:
        good_run, bad_run = select_runs(repo, workflow)
        console.print(
            f"Selected: [green]Good run {good_run}[/green] and [red]bad run {bad_run}[/red]"
        )

    good_path = PATH / f"{repo}_{good_run}"
    bad_path = PATH / f"{repo}_{bad_run}"

    if force:
        rmtree(good_path, ignore_errors=True)
        rmtree(bad_path, ignore_errors=True)

    if not good_path.exists() or not bad_path.exists():
        with console.status("Downloading artifacts..."):
            good_url, bad_url = get_artifact_urls(repo, workflow, good_run, bad_run)
            download_artifact(repo, good_run, good_url)
            download_artifact(repo, bad_run, bad_url)

    good_file, bad_file = good_path / "pixi.lock", bad_path / "pixi.lock"

    if not good_file or not good_file.exists():
        console.print(
            "Good artifact does not exists. Please check the options.",
            style="bright_red",
        )
        sys.exit(1)
    if not bad_file or not bad_file.exists():
        console.print(
            "Bad artifact does not exists. Please check the options.",
            style="bright_red",
        )
        sys.exit(1)
    return good_file, bad_file, good_run, bad_run


def get_env(file, env, os):  # RENAME
    with open(file) as f:
        data = f.read()
    data = data.split("\npackages:")[0]
    spaces = "  "

    ns = [f"{spaces}{env}:"]
    for n in data.split(f"\n{spaces}{env}:")[1].split("\n")[1:]:
        if not n.startswith(spaces + " "):
            break
        ns.append(n)
    data = "\n".join(ns)

    spaces = "      "
    ns = [f"{spaces}{os}:"]
    for n in data.split(f"\n{spaces}{os}:")[1].split("\n")[1:]:
        if not n.startswith(f"{spaces}-"):
            break
        ns.append(n)
    data = "\n".join(ns)

    return yaml.safe_load(data)[os]


def compare_envs(repo, good_run, bad_run, environment, arch, good_file, bad_file):
    good_env = get_env(good_file, environment, arch)
    bad_env = get_env(bad_file, environment, arch)

    bad_list = {os.path.basename(next(iter(p.values()))) for p in bad_env}
    good_list = {os.path.basename(next(iter(p.values()))) for p in good_env}
    good_only = good_list - bad_list
    bad_only = bad_list - good_list

    packages = {p.split("-")[:-2][0] for p in good_only | bad_only}
    if not packages:
        click.echo("No differences found for the given parameters.")
        return

    info = []
    for p in sorted(packages):
        good = [g for g in good_only if g.startswith(p)]
        bad = [g for g in bad_only if g.startswith(p)]
        info.append((p, good[0] if good else "-", bad[0] if bad else "-"))

    table = Table(
        title=f"Difference in packages on {repo!r} for environment {environment!r} on {arch!r}",
    )
    table.add_column("Package", min_width=15)
    table.add_column(f"Only in good lock (#{good_run})", style="green")
    table.add_column(f"Only in bad lock (#{bad_run})", style="red")

    for i in info:
        table.add_row(*i)

    console.print(table)


@click.command(context_settings={"show_default": True})
@argument_menu("repo", choises=REPOS, console=console, title="Select a repo")
@click.argument("good_run", type=int, required=False)
@click.argument("bad_run", type=int, required=False)
@click.option(
    "--environment",
    default="test-39",
    type=click.Choice(["test-39", "test-310", "test-311", "test-312", "test-ui", "test-core"]),
    help="Test type",
)
@click.option(
    "--arch",
    default="linux-64",
    type=click.Choice(["linux-64", "osx-arm64", "osx-64", "win-64"]),
    help="Operating system",
)
@click.option(
    "--workflow",
    default="test.yaml",
    type=str,
    help="Workflow filename",
)
@click.option(
    "--force/--no-force",
    default=False,
    help="Force download artifacts",
)
def cli(repo, good_run, bad_run, environment, arch, workflow, force) -> None:
    good_file, bad_file, good_run, bad_run = get_files(repo, good_run, bad_run, workflow, force)

    code = (
        f"holoviz artifact {repo} {good_run} {bad_run} --environment {environment} --arch {arch}"
    )
    clipboard_set(code)

    compare_envs(repo, good_run, bad_run, environment, arch, good_file, bad_file)


if __name__ == "__main__":
    cli()
