from __future__ import annotations

from pathlib import Path
from subprocess import check_output

import rich_click as click
from _artifact import console, download_files
from rich_menu import argument_menu
from utilities import clean_exit

# Needs diff-so-fancy in path

REPOS = ["holoviews", "panel", "hvplot", "datashader", "geoviews", "lumen"]


def get_files(
    repo, good_run, bad_run, test, os, python, workflow, force
) -> tuple[Path | None, Path | None]:
    good_run, bad_run, good_path, bad_path = download_files(
        repo, good_run, bad_run, workflow, force=force
    )

    found = False
    for file in good_path.iterdir():
        name = file.name.lower()
        if os in name and python in name and f"_{test}" in name:
            found = True
            break

    if not found:
        return None, None

    good_file = good_path / file.name
    bad_file = bad_path / file.name
    return good_file, bad_file


@clean_exit
@click.command(context_settings={"show_default": True})
@argument_menu("repo", choices=REPOS, console=console, title="Select a repo")
@click.argument("good_run", type=int, required=False)
@click.argument("bad_run", type=int, required=False)
@click.option(
    "--test",
    default="unit",
    type=click.Choice(["unit", "ui", "core"]),
    help="Test type",
)
@click.option(
    "--os",
    default="linux",
    type=click.Choice(["linux", "mac", "windows"]),
    help="Operating system",
)
@click.option(
    "--python",
    default="3.11",
    type=click.Choice(["3.8", "3.9", "3.10", "3.11"]),
    help="Python version",
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
def cli(good_run, bad_run, repo, test, os, python, workflow, force) -> None:
    good_file, bad_file = get_files(repo, good_run, bad_run, test, os, python, workflow, force)

    if not good_file or not good_file.exists():
        console.print(
            "Good artifact does not exists. Please check the options.",
            style="bright_red",
        )
        return
    if not bad_file or not bad_file.exists():
        console.print(
            "Bad artifact does not exists. Please check the options.",
            style="bright_red",
        )
        return

    cmd = f"git diff {bad_file} {good_file} | diff-so-fancy"
    diff = check_output(cmd, shell=True).decode()

    if diff:
        click.echo(diff)
    else:
        click.echo("No differences found for the given parameters.")


if __name__ == "__main__":
    cli()
