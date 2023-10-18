from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import requests
from rich.console import Console
from rich.progress import track
from rich.table import Table


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


COLUMNS = {
    "name": "Workflow",
    "head_branch": "Branch",
    "display_title": "Title",
    "status": "Status",
    "run_started_at": "Duration",
    "triggering_actor.login": "User",
}

REPOS = [
    "colorcet",
    "datashader",
    "geoviews",
    "holonote",
    "holoviews",
    "holoviz",
    "hvplot",
    "jupyter-panel-proxy",
    "lumen",
    "panel",
    "param",
    "pyviz_comms",
    "spatialpandas",
]

HEADERS = {
    "Accept": "application/vnd.github+json",
    "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
    "X-GitHub-Api-Version": "2022-11-28",
}


def get_info(repo) -> pd.DataFrame | None:
    url = f"https://api.github.com/repos/holoviz/{repo}/actions/runs"
    resp = requests.get(url, params={"per_page": 30}, headers=HEADERS)
    assert resp.ok, "API timeout"
    df = pd.json_normalize(resp.json(), "workflow_runs")
    df = df[df["status"] != "completed"]
    if df.empty:
        return

    df = df[list(COLUMNS)].rename(COLUMNS, axis=1)
    df["Repo"] = repo
    return df


def main() -> None:
    console = Console()
    futures = trackpool(get_info, REPOS, "Getting status of Github Actions")

    try:
        df = pd.concat(futures)
    except ValueError:
        print("No running Github Actions")
        return

    df = df.sort_values("Duration", ascending=False)
    df["Duration"] = (
        (pd.Timestamp.now(tz="UTC") - pd.to_datetime(df["Duration"]))
        .dt.total_seconds()
        .apply(lambda x: f"{x / 60:0.0f} min")
    )
    print_table(df, console)


def print_table(df, console) -> None:
    table = Table(title="Running Github Actions")
    for c in df.columns:
        table.add_column(c)

    for r in df.itertuples(index=False):
        table.add_row(*r)

    console.print(table)


if __name__ == "__main__":
    main()
