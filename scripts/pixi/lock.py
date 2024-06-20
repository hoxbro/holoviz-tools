from __future__ import annotations

import os
import sys
from pathlib import Path
from shutil import copy2

import rich_click as click
from _artifact import console, download_file
from pandas.io.clipboard import clipboard_set
from rich_menu import argument_menu
from utilities import clean_exit

REPOS = ["holoviews", "panel"]  # , "hvplot", "datashader", "geoviews", "lumen"]


def get_file(repo, run, workflow, force) -> tuple[Path | None, Path | None]:
    run, path = download_file(repo, run, workflow, force=force, artifact_names=["pixi-lock"])
    file = path / "pixi.lock"

    if not file or not file.exists():
        console.print(
            "Good artifact does not exists. Please check the options.",
            style="bright_red",
        )
        sys.exit(1)
    return run, file


@clean_exit
@click.command(context_settings={"show_default": True})
@argument_menu("repo", choices=REPOS, console=console, title="Select a repo")
@click.argument("run", type=int, required=False)
@click.option(
    "--workflow",
    default="nightly_lock.yaml",
    type=str,
    help="Workflow filename",
)
@click.option(
    "--force/--no-force",
    default=False,
    help="Force download artifacts",
)
def cli(repo, run, workflow, force) -> None:
    run, src = get_file(repo, run, workflow, force)

    # Save to command to clipboard
    code = f"holoviz pixi-lock {repo} {run} "
    if workflow != "test.yaml":
        code += f"--workflow {workflow} "
    if force:
        code += "--force "
    clipboard_set(code)

    dst = Path(os.environ["HOLOVIZ_REP"]) / repo / "pixi.lock"
    copy2(src, dst)


if __name__ == "__main__":
    cli()
