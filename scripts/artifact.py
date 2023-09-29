from __future__ import annotations

import os
from io import BytesIO
from pathlib import Path
from shutil import rmtree
from subprocess import check_output
from zipfile import ZipFile

import requests
import rich_click as click
from rich.console import Console

# Needs diff-so-fancy in path

PATH = Path("~/.cache/holoviz-cli/artifact").expanduser().resolve()
PATH.mkdir(parents=True, exist_ok=True)

HEADERS = {
    "Accept": "application/vnd.github+json",
    "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
    "X-GitHub-Api-Version": "2022-11-28",
}


def get_runs(repo, workflow, prs) -> dict | None:
    url = (
        f"https://api.github.com/repos/holoviz/{repo}/actions/workflows/{workflow}/runs"
    )
    results = {}
    for page in range(1, 10):
        resp = requests.get(url, params={"page": page, "per_page": 30}, headers=HEADERS)
        assert resp.ok
        for run in resp.json()["workflow_runs"]:
            if run["run_number"] in prs:
                results[run["run_number"]] = run["url"] + "/artifacts"

            if len(prs) == len(results):
                return results


def download_artifact(repo, pr, url) -> None:
    resp = requests.get(url, headers=HEADERS)
    assert resp.ok
    artifact = resp.json()["artifacts"]
    if not artifact:
        (PATH / f"{repo}_{pr}").mkdir(exist_ok=True)
        return
    download_url = artifact[0]["archive_download_url"]
    zipfile = requests.get(download_url, headers=HEADERS)
    assert resp.ok

    bio = BytesIO(zipfile.content)
    bio.seek(0)
    with ZipFile(bio) as zip_ref:
        zip_ref.extractall(PATH / f"{repo}_{pr}")


def get_files(
    repo, good_run, bad_run, test, os, python, workflow, force
) -> tuple[Path, Path]:
    good_path = PATH / f"{repo}_{good_run}"
    bad_path = PATH / f"{repo}_{bad_run}"

    if force:
        rmtree(good_path, ignore_errors=True)
        rmtree(bad_path, ignore_errors=True)

    prs = []
    if not good_path.exists():
        prs.append(good_run)
    if not bad_path.exists():
        prs.append(bad_run)

    if prs:
        runs = get_runs(repo, workflow, prs)
        for pr, url in runs.items():
            download_artifact(repo, pr, url)

    for file in good_path.iterdir():
        name = file.name.lower()
        if os in name and python in name and test in name:
            break

    good_file = good_path / file.name
    bad_file = bad_path / file.name
    return good_file, bad_file


# Context setting working with: https://github.com/ewels/rich-click/pull/115
@click.command(context_settings={"show_default": True})
@click.argument("good_run", type=int)
@click.argument("bad_run", type=int)
@click.option(
    "--repo",
    default="holoviews",
    type=click.Choice(["holoviews", "panel", "hvplot", "datashader", "geoviews"]),
    help="Repository (default: holoviews)",
)
@click.option(
    "--test",
    default="unit",
    type=click.Choice(["unit", "ui", "core"]),
    help="Test type (default: unit)",
)
@click.option(
    "--os",
    default="linux",
    type=click.Choice(["linux", "mac", "windows"]),
    help="Operating system (default: linux)",
)
@click.option(
    "--python",
    default="3.10",
    type=click.Choice(["3.8", "3.9", "3.10", "3.11"]),
    help="Python version (default: 3.10)",
)
@click.option(
    "--workflow",
    default="test.yaml",
    type=str,
    help="Workflow filename (default: test.yaml)",
)
@click.option(
    "--force/--no-force",
    default=False,
    help="Force download artifacts (default: False)",
)
def cli(good_run, bad_run, repo, test, os, python, workflow, force) -> None:
    console = Console()
    with console.status("Downloading artifacts..."):
        good_file, bad_file = get_files(
            repo, good_run, bad_run, test, os, python, workflow, force
        )

    if not good_file.exists():
        console.print(
            "Good artifact does not exists. Please check the parameters.",
            style="bright_red",
        )
        return
    if not bad_file.exists():
        console.print(
            "Bad artifact does not exists. Please check the parameters.",
            style="bright_red",
        )
        return

    cmd = f"git diff {bad_file} {good_file} | diff-so-fancy"
    diff = check_output(cmd, shell=True).decode()

    if diff:
        print(diff)
    else:
        console.print("No differences found for the given parameters.")


if __name__ == "__main__":
    cli()
