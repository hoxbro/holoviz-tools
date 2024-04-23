import contextlib
import re
import tarfile
import zipfile
from itertools import zip_longest

import rich_click as click
from _artifact import console, download_files
from pandas.io.clipboard import clipboard_set
from rich.table import Table
from rich_menu import argument_menu

REPOS = ["holoviews", "panel", "datashader", "geoviews"]


def _get_version_re(repo_version):
    repo_version = re.escape(repo_version)
    repo_version = re.sub(r"(\d)\-?(rc|a|b)\.?(\d)", r"\1\-?\2\.?\3", repo_version)  # For JS versioning
    repo_version = repo_version.replace(r"\-", ".")  # For repo/version path
    return re.compile(repo_version)


def zip_files(zip_path):
    with zipfile.ZipFile(zip_path, "r") as zip_ref:
        zip_file_list = zip_ref.namelist()
    repo_version = zip_path.name.split("-py3")[0].split("-py2")[0]
    re_version = _get_version_re(repo_version)
    return {re_version.sub("$VERSION", f) for f in zip_file_list}


def tar_files(tar_path):
    with tarfile.open(tar_path, "r") as tar_ref:
        tar_file_list = [member.name for member in tar_ref.getmembers() if member.isfile()]
    repo_version = tar_path.name.split(".tar")[0].split("-py_0")[0].split(".tgz")[0].removeprefix("holoviz-")
    re_version = _get_version_re(repo_version)
    return {re_version.sub("$VERSION", f) for f in tar_file_list}


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
        console.print(f"[green]{title} has identical filelist[/green]")
        return
    table = Table(title=title)
    table.add_column(f"[green]Files only in run 1\n{version1}[/green]", style="green")
    table.add_column(f"[red]Files only in run 2\n{version2}[/red]", style="red")
    for m1, m2 in zip_longest(missing1, missing2, fillvalue="-"):
        table.add_row(m1, m2)
    console.print(table)


@click.command(context_settings={"show_default": True})
@argument_menu("repo", choices=REPOS, console=console, title="Select a repo")
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
        repo, good_run, bad_run, workflow, force=force, artifact_names=["pip", "conda", "npm"]
    )

    # Save to command to clipboard
    code = f"holoviz artifact-build {repo} {good_run} {bad_run} "
    if workflow != "build.yaml":
        code += f"--workflow {workflow} "
    if force:
        code += "--force "
    clipboard_set(code)

    with contextlib.suppress(StopIteration):  # Wheel
        before_path = next(good_path.glob("*.whl"))
        after_path = next(bad_path.glob("*.whl"))
        version1 = before_path.name.split("-py3")[0].replace("-", " ")
        version2 = after_path.name.split("-py3")[0].replace("-", " ")
        missing_whl1, missing_whl2 = compare_zip_files(before_path, after_path)
        generate_table(f"{repo.title()} - wheel", version1, version2, missing_whl1, missing_whl2)

    with contextlib.suppress(StopIteration):  # Source distribution
        before_path = next(good_path.glob("*.tar.gz"))
        after_path = next(bad_path.glob("*.tar.gz"))
        version1 = before_path.name.split(".tar")[0].replace("-", " ")
        version2 = after_path.name.split(".tar")[0].replace("-", " ")
        missing_sdist1, missing_sdist2 = compare_tar_files(before_path, after_path)
        #  Filter out top-level example folder, this is a known bug
        missing_sdist1 = [f for f in missing_sdist1 if not f.startswith("$VERSION/examples")]
        missing_sdist2 = [f for f in missing_sdist2 if not f.startswith("$VERSION/examples")]
        generate_table(
            f"{repo.title()} - sdist", version1, version2, missing_sdist1, missing_sdist2
        )

    with contextlib.suppress(StopIteration):  # Conda
        before_path = next(good_path.glob("*.tar.bz2"))
        after_path = next(bad_path.glob("*.tar.bz2"))
        version1 = before_path.name.split(".tar")[0].split("-py_0")[0].replace("-", " ")
        version2 = after_path.name.split(".tar")[0].split("-py_0")[0].replace("-", " ")
        missing_conda1, missing_conda2 = compare_tar_files(before_path, after_path)
        generate_table(
            f"{repo.title()} - conda", version1, version2, missing_conda1, missing_conda2
        )

    with contextlib.suppress(StopIteration):  # NPM
        before_path = next(good_path.glob("*.tgz"))
        after_path = next(bad_path.glob("*.tgz"))
        version1 = before_path.name.split(".tgz")[0].replace("-", " ").strip("holoviz ")
        version2 = after_path.name.split(".tgz")[0].replace("-", " ").strip("holoviz ")
        missing_conda1, missing_conda2 = compare_tar_files(before_path, after_path)
        generate_table(
            f"{repo.title()} - npmjs", version1, version2, missing_conda1, missing_conda2
        )


if __name__ == "__main__":
    cli()
