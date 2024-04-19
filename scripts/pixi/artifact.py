from __future__ import annotations

import contextlib
import os
import sys
from pathlib import Path

import rich_click as click
import yaml
from _artifact import console, download_files
from pandas.io.clipboard import clipboard_set
from rich.table import Table
from rich_menu import argument_menu

REPOS = ["holoviews"]  # , "panel", "hvplot", "datashader", "geoviews", "lumen"]


def get_files(repo, good_run, bad_run, workflow, force) -> tuple[Path | None, Path | None]:
    good_run, bad_run, good_path, bad_path = download_files(
        repo, good_run, bad_run, workflow, force=force, artifact_names=["pixi-lock"]
    )
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
    return good_run, bad_run, good_file, bad_file


def get_env(file):
    with open(file) as f:
        data = f.read()
    data = data.split("\npackages:")[0]
    return yaml.load(data, Loader=yaml.CLoader)["environments"]


def compare_envs(repo, good_run, bad_run, env, arch, good_file, bad_file):
    good_envs, bad_envs = get_env(good_file), get_env(bad_file)

    output = False
    for k_env, v_env in good_envs.items():
        if not k_env.startswith("test") or (env is not None and k_env != env):
            continue
        for k_arch, good_env in v_env["packages"].items():
            if arch is not None and k_arch != arch:
                continue

            # Assumes symmetry between runs if not we just ignore
            with contextlib.suppress(KeyError):
                bad_env = bad_envs[k_env]["packages"][k_arch]
                output |= table_output(repo, good_run, bad_run, k_env, k_arch, good_env, bad_env)

    if output is False:
        console.print("No differences found between the runs")


def table_output(repo, good_run, bad_run, env, arch, good_env, bad_env):
    bad_list = {os.path.basename(next(iter(p.values()))) for p in bad_env}
    good_list = {os.path.basename(next(iter(p.values()))) for p in good_env}
    good_only = good_list - bad_list
    bad_only = bad_list - good_list

    packages = {p.split("-")[:-2][0] for p in good_only | bad_only if p != "."}
    if not packages:
        return False

    info = []
    for p in sorted(packages):
        good = [g for g in good_only if g.startswith(p)]
        bad = [g for g in bad_only if g.startswith(p)]
        info.append((p, good[0] if good else "-", bad[0] if bad else "-"))

    table = Table(
        title=f"Difference in packages on {repo!r} for env {env!r} on arch {arch!r}",
    )
    table.add_column("Package", min_width=15)
    table.add_column(f"[green]Good run (#{good_run})[/green]", style="green")
    table.add_column(f"[red]Bad run (#{bad_run})[/red]", style="red")

    for i in info:
        table.add_row(*i)

    console.print(table)
    return True


@click.command(context_settings={"show_default": True})
@argument_menu("repo", choices=REPOS, console=console, title="Select a repo")
@click.argument("good_run", type=int, required=False)
@click.argument("bad_run", type=int, required=False)
@click.option(
    "--env",
    default=None,
    type=click.Choice(["test-39", "test-310", "test-311", "test-312", "test-ui", "test-core"]),
    help="Test type",
)
@click.option(
    "--arch",
    default=None,
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
def cli(repo, good_run, bad_run, env, arch, workflow, force) -> None:
    good_run, bad_run, good_file, bad_file = get_files(repo, good_run, bad_run, workflow, force)

    # Save to command to clipboard
    code = f"holoviz artifact-test {repo} {good_run} {bad_run} "
    if env:
        code += f"--env {env} "
    if arch:
        code += f"--arch {arch} "
    if workflow != "test.yaml":
        code += f"--workflow {workflow} "
    if force:
        code += "--force "
    clipboard_set(code)

    compare_envs(repo, good_run, bad_run, env, arch, good_file, bad_file)


if __name__ == "__main__":
    cli()
