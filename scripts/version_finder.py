"""Get dependencies info for a package

Minimum:
- The first version released after a new Python feature release is released.
- The requires python specifier allow the Python version.

Maximum:
- The last version which requires python specifier allows.

Current:
- The latest version released.

Spec 0:
- Follows the standard: https://scientific-python.org/specs/spec-0000/
- Support for two year after a feature release of the package.
"""

from __future__ import annotations

import collections
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from functools import cache
from runpy import run_path
from typing import Any

import requests
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.version import InvalidVersion, Version
from rich.console import Console
from rich.progress import track
from rich.prompt import Prompt
from rich.table import Table

py_releases = {
    "3.8": datetime(2019, 10, 14),
    "3.9": datetime(2020, 10, 5),
    "3.10": datetime(2021, 10, 4),
    "3.11": datetime(2022, 10, 24),
    "3.12": datetime(2023, 10, 2),
}
spec_drop_date = datetime.now() - timedelta(days=int(365 * 2))
HEADERS = {"Accept": "application/vnd.pypi.simple.v1+json"}
console = Console()


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


@cache
def get_resp(url, with_headers=True) -> dict[str, Any] | None:
    headers = HEADERS if with_headers else {}
    resp = requests.get(url, headers=headers)
    if resp.ok:
        return resp.json()
    else:
        return None


@cache
def pypi_info(package: str, python_version: str = "3.9") -> tuple[str, ...]:
    url = f"https://pypi.org/simple/{package}"
    resp = get_resp(url, with_headers=True)

    if not resp:
        return package, "-", "-", "-", "-"

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

    spec0 = [r for r, d in releases.items() if r.micro == 0 and spec_drop_date <= d]
    spec0_version = str(min(spec0)) if spec0 else "-"

    return package, min_version, max_version, cur_version, spec0_version


def get_packages_from_file(main_package: str) -> tuple[set[str], str]:
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


def get_packages_from_pypi(main_package) -> tuple[set[str], str]:
    url = f"https://pypi.org/pypi/{main_package}/json"
    resp = get_resp(url)

    python_requires = resp["info"]["requires_python"].replace(">=", "")

    packages = {Requirement(r).name for r in resp["info"]["requires_dist"]}

    return packages, python_requires


def query(main_package, python_requires=None) -> None:
    try:
        packages, lowest_supported_python = get_packages_from_file(main_package)
    except Exception:
        packages, lowest_supported_python = get_packages_from_pypi(main_package)

    python_requires = python_requires or lowest_supported_python

    info = trackpool(
        lambda p: pypi_info(p, python_requires),
        sorted(packages),
        f"Getting dependencies info for {main_package}",
    )
    table = Table(
        title=f"Package information for {main_package.capitalize()} and Python {python_requires}"
    )
    table.add_column("Package")
    table.add_column("Minimum", justify="right", min_width=10)
    table.add_column("Maximum", justify="right", min_width=10)
    table.add_column("Current", justify="right", min_width=10)
    table.add_column("Spec 0", justify="right", min_width=10)

    for i in info:
        table.add_row(*i)

    console.print(table)


def main() -> None:
    while True:
        main_package = Prompt.ask("Package (no input to quit)", console=console)
        if not main_package:
            break

        python_requires = Prompt.ask(
            "Python version", console=console, choices=py_releases, default="3.9"
        )
        query(main_package, python_requires)


if __name__ == "__main__":
    main()
