import collections
import os
from datetime import datetime, timedelta
from functools import cache
from runpy import run_path

import requests
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.version import InvalidVersion, Version
from rich.console import Console
from rich.table import Table

py_releases = {
    "3.8": datetime(2019, 10, 14),
    "3.9": datetime(2020, 10, 5),
    "3.10": datetime(2021, 10, 4),
    "3.11": datetime(2022, 10, 24),
    "3.12": datetime(2023, 10, 2),
}

headers = {"Accept": "application/vnd.pypi.simple.v1+json"}


@cache
def get_resp(url, with_headers=True):
    if with_headers:
        return requests.get(url, headers=headers).json()
    else:
        return requests.get(url, headers=None).json()


@cache
def pypi_info(package, python_version="3.9"):
    url = f"https://pypi.org/simple/{package}"
    resp = get_resp(url, with_headers=True)

    releases = collections.defaultdict(list)
    results = collections.defaultdict(list)
    for f in resp["files"]:
        ver = f["filename"].split("-")[1]
        try:
            version = Version(ver)
        except InvalidVersion:
            continue

        if version.is_prerelease:
            continue

        release_date = datetime.fromisoformat(f["upload-time"]).replace(tzinfo=None)
        releases[version].append(release_date)

        python_check1 = f["requires-python"] is None or (
            SpecifierSet(f["requires-python"].replace(".*", "")).contains(
                python_version
            )
        )
        python_check2 = release_date >= py_releases[python_version]
        if python_check1 and python_check2:
            results[version].append(release_date)

    results = {v: min(results[v]) for v in results}
    releases = {v: min(releases[v]) for v in releases}

    min_version = str(min(results)) if results else "-"
    max_version = str(max(results)) if results else "-"
    cur_version = str(max(releases)) if releases else "-"
    return package, min_version, max_version, cur_version


def get_packages_from_file(main_package):
    output = run_path(
        f"{os.environ['HOLOVIZ_REP']}/{main_package}/setup.py",
        run_name="not__main__",
    )
    setup = output["setup_args"]

    python_requires = setup["python_requires"].replace(">=", "")

    install_requires, extras_require = (
        setup["install_requires"],
        setup["extras_require"],
    )
    all_packages = install_requires + sum(extras_require.values(), [])
    packages = {Requirement(p).name for p in all_packages}

    return packages, python_requires


def get_packages_from_pypi(main_package):
    url = f"https://pypi.org/pypi/{main_package}/json"
    resp = get_resp(url)

    python_requires = resp["info"]["requires_python"].replace(">=", "")

    packages = {Requirement(r).name for r in resp["info"]["requires_dist"]}

    return packages, python_requires


def query(main_package, python_requires=None):
    console = Console()

    try:
        packages, lowest_supported_python = get_packages_from_file(main_package)
    except Exception:
        packages, lowest_supported_python = get_packages_from_pypi(main_package)

    python_requires = python_requires or lowest_supported_python

    with console.status(f"Getting dependencies info for {main_package}"):
        info = [pypi_info(p, python_requires) for p in sorted(packages)]

    table = Table(
        title=f"Package information for {main_package.capitalize()} and Python {python_requires}"
    )
    table.add_column("Package")
    table.add_column("Minimum", justify="right")
    table.add_column("Maximum", justify="right")
    table.add_column("Current", justify="right")

    for i in info:
        table.add_row(*i)

    console.print(table)


def main():
    main_package = input("Package: ").strip()
    python_requires = input("Python version: ").strip()
    while True:
        if not main_package:
            break

        query(main_package, python_requires)

        print("\nTry again?")
        main_package = input("Package: ").strip()
        python_requires = input("Python version: ").strip()
        print("\n")


if __name__ == "__main__":
    main()
