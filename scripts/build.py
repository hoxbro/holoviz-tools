import contextlib
import tarfile
import zipfile
from itertools import zip_longest

import rich_click as click
from _artifact import console, download_files
from rich.table import Table
from rich_menu import argument_menu

REPOS = ["holoviews", "panel", "datashader", "geoviews"]


def zip_files(zip_path):
    with zipfile.ZipFile(zip_path, "r") as zip_ref:
        zip_file_list = zip_ref.namelist()
    version = zip_path.name.split("-py3")[0]
    return {f.replace(version, "$VERSION") for f in zip_file_list}


def tar_files(tar_path):
    with tarfile.open(tar_path, "r") as tar_ref:
        tar_file_list = [member.name for member in tar_ref.getmembers() if member.isfile()]
    version = tar_path.name.split(".tar")[0].split("-py_0")[0]
    return {f.replace(version, "$VERSION") for f in tar_file_list}


def compare_zip_files(zip1_path, zip2_path):
    zip1 = zip_files(zip1_path)
    zip2 = zip_files(zip2_path)
    zip1_missing = sorted(zip1 - zip2)
    zip2_missing = sorted(zip2 - zip1)
    return zip1_missing, zip2_missing


def compare_tar_files(tar1_path, tar2_path):
    tar1 = tar_files(tar1_path)
    tar2 = tar_files(tar2_path)
    tar1_missing = sorted(tar1 - tar2)
    tar2_missing = sorted(tar2 - tar1)
    return tar1_missing, tar2_missing


def generate_table(title, version1, version2, missing1, missing2):
    if not missing1 and not missing2:
        console.print(f"[green]{title} are identical[/green]")
        return
    table = Table(title=title)
    table.add_column(f"[green]Files only in run 1\n{version1}[/green]", style="green")
    table.add_column(f"[red]Files only in run 2\n{version2}[/red]", style="red")
    for m1, m2 in zip_longest(missing1, missing2, fillvalue="-"):
        table.add_row(m1, m2)
    console.print(table)


@click.command(context_settings={"show_default": True})
@argument_menu("repo", choises=REPOS, console=console, title="Select a repo")
@click.argument("good_run", type=int, required=False)
@click.argument("bad_run", type=int, required=False)
@click.option(
    "--workflow",
    default="build.yaml",
    type=str,
    help="Workflow filename",
)
@click.option(
    "--force/--no-force",
    default=False,
    help="Force download artifacts",
)
def cli(repo, good_run, bad_run, workflow, force) -> None:
    good_run, bad_run, good_path, bad_path = download_files(
        repo, good_run, bad_run, workflow, artifact_names=["pip", "conda"]
    )

    with contextlib.suppress(StopIteration):  # Wheel
        before_path = next(good_path.glob("*.whl"))
        after_path = next(bad_path.glob("*.whl"))
        version1 = before_path.name.split("-py3")[0].split("-")[-1]
        version2 = after_path.name.split("-py3")[0].split("-")[-1]
        missing_whl1, missing_whl2 = compare_zip_files(before_path, after_path)
        generate_table(
            f"{repo} - wheels", version1, version2, missing_whl1, missing_whl2
        )

    with contextlib.suppress(StopIteration):  # Source distribution
        before_path = next(good_path.glob("*.tar.gz"))
        after_path = next(bad_path.glob("*.tar.gz"))
        version1 = before_path.name.split(".tar")[0].split("-")[-1]
        version2 = after_path.name.split(".tar")[0].split("-")[-1]
        missing_sdist1, missing_sdist2 = compare_tar_files(before_path, after_path)
        #  Filter out top-level example folder, this is a known bug
        missing_sdist1 = [f for f in missing_sdist1 if not f.startswith("$VERSION/examples")]
        missing_sdist2 = [f for f in missing_sdist2 if not f.startswith("$VERSION/examples")]
        generate_table(
            f"{repo} - sdist", version1, version2, missing_sdist1, missing_sdist2
        )

    with contextlib.suppress(StopIteration):  # Conda
        before_path = next(good_path.glob("*.tar.bz2"))
        after_path = next(bad_path.glob("*.tar.bz2"))
        version1 = before_path.name.split(".tar")[0].split("-py_0")[0].split("-")[-1]
        version2 = after_path.name.split(".tar")[0].split("-py_0")[0].split("-")[-1]
        missing_conda1, missing_conda2 = compare_tar_files(before_path, after_path)
        generate_table(
            f"{repo} - conda", version1, version2, missing_conda1, missing_conda2
        )


if __name__ == "__main__":
    cli()
