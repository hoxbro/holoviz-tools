from __future__ import annotations

import contextlib
import io
import re
import tarfile
import zipfile
from itertools import zip_longest

import rich_click as click
import zstandard as zstd
from pandas.io.clipboard import clipboard_set
from rich.table import Table

from _artifact import console, download_files
from rich_menu import argument_menu

REPOS = ["holoviews", "panel", "datashader", "geoviews", "lumen", "spatialpandas"]


def _get_version_re(repo_version):
    repo_version1 = re.findall(r"^\w+.\d+.\d+.\d+", repo_version)[0]
    repo_version1 = repo_version1.replace(r"-", ".")  # For repo/version path
    re1 = re.compile(repo_version1)

    # For JS versioning
    repo_version = re.escape(repo_version)
    repo_version2 = re.sub(r"(\d)\-?(rc|a|b)\.?(\d)", r"\1\-?\2\.?\3", repo_version)
    repo_version2 = repo_version2.replace(r"\-", ".")  # For repo/version path
    re2 = re.compile(repo_version2)
    return re1, re2


def zip_filelist(zip_path):
    with zipfile.ZipFile(zip_path, "r") as zip_ref:
        zip_filelist = zip_ref.namelist()
    repo_version = zip_path.name.split("-py3")[0].split("-py2")[0]
    re1, re2 = _get_version_re(repo_version)
    return {re1.sub("$VERSION", re2.sub("$VERSION", f)) for f in zip_filelist}


def tar_filelist(tar_path):
    with tarfile.open(tar_path, "r") as tar_ref:
        tar_filelist = [member.name for member in tar_ref.getmembers() if member.isfile()]
    repo_version = tar_path.name
    repo_version = repo_version.replace("-core", "").split(".tar")[0].split("-py_0")[0]  # conda
    repo_version = repo_version.split(".tgz")[0].removeprefix("holoviz-")  # npm
    re1, re2 = _get_version_re(repo_version)
    return {re1.sub("$VERSION", re2.sub("$VERSION", f)) for f in tar_filelist}


def conda_filelist(conda_path):
    conda_filelist = []
    with zipfile.ZipFile(conda_path, "r") as conda_zip:
        conda_contents = conda_zip.namelist()
        conda_filelist.extend([name for name in conda_contents if not name.endswith(".tar.zst")])
        tar_zst_files = [name for name in conda_contents if name.endswith(".tar.zst")]
        for tar_zst_file in tar_zst_files:
            with conda_zip.open(tar_zst_file) as tar_zst_stream:
                dctx = zstd.ZstdDecompressor()
                decompressed = dctx.stream_reader(tar_zst_stream)

                with tarfile.open(fileobj=io.BytesIO(decompressed.read())) as tar:
                    for tarinfo in tar.getmembers():
                        if tarinfo.isfile():
                            conda_filelist.append(tarinfo.name)

    repo_version = conda_path.name.replace("-core", "").split(".conda")[0].split("-py_0")[0]
    re1, re2 = _get_version_re(repo_version)
    return {re1.sub("$VERSION", re2.sub("$VERSION", f)) for f in conda_filelist}


def compare_zip_files(zip1_path, zip2_path):
    zip1 = zip_filelist(zip1_path)
    zip2 = zip_filelist(zip2_path)
    zip1_missing = sorted(zip1 - zip2)
    zip2_missing = sorted(zip2 - zip1)
    return zip1_missing, zip2_missing


def compare_tar_files(tar1_path, tar2_path):
    tar1 = tar_filelist(tar1_path)
    tar2 = tar_filelist(tar2_path)
    tar1_missing = sorted(tar1 - tar2)
    tar2_missing = sorted(tar2 - tar1)
    return tar1_missing, tar2_missing


def compare_conda_files(conda1_path, conda2_path):
    conda1 = conda_filelist(conda1_path)
    conda2 = conda_filelist(conda2_path)
    conda1_missing = sorted(conda1 - conda2)
    conda2_missing = sorted(conda2 - conda1)
    return conda1_missing, conda2_missing


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

    with contextlib.suppress(IndexError):  # Wheel
        before_path = sorted(good_path.glob("*.whl"))[0]
        after_path = sorted(bad_path.glob("*.whl"))[0]
        version1 = before_path.name.split("-py3")[0].replace("-", " ")
        version2 = after_path.name.split("-py3")[0].replace("-", " ")
        missing_whl1, missing_whl2 = compare_zip_files(before_path, after_path)
        generate_table(f"{repo.title()} - wheel", version1, version2, missing_whl1, missing_whl2)

    with contextlib.suppress(IndexError):  # Source distribution
        before_path = sorted(good_path.glob("*.tar.gz"))[0]
        after_path = sorted(bad_path.glob("*.tar.gz"))[0]
        version1 = before_path.name.split(".tar")[0].replace("-", " ")
        version2 = after_path.name.split(".tar")[0].replace("-", " ")
        missing_sdist1, missing_sdist2 = compare_tar_files(before_path, after_path)
        # missing_sdist1 = [f for f in missing_sdist1 if not f.startswith("$VERSION/examples")]
        # missing_sdist1 = [f for f in missing_sdist1 if not f.startswith("$VERSION/doc")]
        # missing_sdist2 = [f for f in missing_sdist2 if not f.startswith("$VERSION/examples")]
        # missing_sdist2 = [f for f in missing_sdist2 if not f.startswith("$VERSION/doc")]
        generate_table(
            f"{repo.title()} - sdist", version1, version2, missing_sdist1, missing_sdist2
        )

    with contextlib.suppress(IndexError):  # Conda pkg-format 1
        before_path = sorted(good_path.glob("*.tar.bz2"), key=lambda x: "core" not in x.name)[0]
        after_path = sorted(bad_path.glob("*.tar.bz2"), key=lambda x: "core" not in x.name)[0]
        version1 = before_path.name.split(".tar")[0].split("-py_0")[0].replace("-", " ")
        version2 = after_path.name.split(".tar")[0].split("-py_0")[0].replace("-", " ")
        missing_conda1, missing_conda2 = compare_tar_files(before_path, after_path)
        generate_table(
            f"{repo.title()} - conda #1", version1, version2, missing_conda1, missing_conda2
        )

    with contextlib.suppress(IndexError):  # Conda pkg-format 2
        before_path = sorted(good_path.glob("*.conda"), key=lambda x: "core" not in x.name)[0]
        after_path = sorted(bad_path.glob("*.conda"), key=lambda x: "core" not in x.name)[0]
        version1 = before_path.name.split(".conda")[0].split("-py_0")[0].replace("-", " ")
        version2 = after_path.name.split(".conda")[0].split("-py_0")[0].replace("-", " ")
        missing_conda1, missing_conda2 = compare_conda_files(before_path, after_path)
        generate_table(
            f"{repo.title()} - conda #2", version1, version2, missing_conda1, missing_conda2
        )

    with contextlib.suppress(IndexError):  # NPM
        before_path = sorted(good_path.glob("*.tgz"))[0]
        after_path = sorted(bad_path.glob("*.tgz"))[0]
        version1 = before_path.name.split(".tgz")[0].replace("-", " ").removeprefix("holoviz-")
        version2 = after_path.name.split(".tgz")[0].replace("-", " ").removeprefix("holoviz-")
        missing_conda1, missing_conda2 = compare_tar_files(before_path, after_path)
        generate_table(
            f"{repo.title()} - npmjs", version1, version2, missing_conda1, missing_conda2
        )


if __name__ == "__main__":
    cli()
