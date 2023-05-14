import re
from datetime import datetime
from functools import cache
from runpy import run_path

import pandas as pd
import requests
from bs4 import BeautifulSoup
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.version import InvalidVersion, Version
from rich.console import Console
from rich.table import Table


def get_python_releases():
    url = "https://www.python.org/doc/versions/"
    resp = requests.get(url)
    soup = BeautifulSoup(resp.text, features="html.parser")
    table = soup.find(id="python-documentation-by-version").find_all("li")

    release_dates = {}
    regex = re.compile(r"(\d+\.\d+[\.\d+]*).+?(\d+ \w+ \d+)")

    for row in table:
        raw_version, raw_date = re.findall(regex, row.text)[0]
        if raw_version == "2.7":
            break

        version = Version(raw_version)
        date = pd.to_datetime(raw_date).to_pydatetime()

        if not version.micro:
            continue

        release_dates[f"{version.major}.{version.minor}"] = date

    return release_dates


release_dates = get_python_releases()


@cache
def get_resp(url):
    return requests.get(url).json()


@cache
def pypi_info(package, python_version="3.7"):
    url = f"https://pypi.org/pypi/{package}/json"
    resp = get_resp(url)

    results = []
    versions = []
    if "releases" not in resp:
        resp["releases"] = {}

    for version, infos in resp["releases"].items():
        try:
            package_version = Version(version)
        except InvalidVersion:
            continue
        if package_version.is_prerelease:
            continue
        versions.append(package_version)

        for info in infos:
            if (
                datetime.fromisoformat(info["upload_time"])
                < release_dates[python_version]
            ):
                continue
            if info["requires_python"] is None:
                results.append(package_version)
                # continue
            elif SpecifierSet(info["requires_python"].replace(".*", "")).contains(
                python_version
            ):
                results.append(package_version)

    min_version = str(min(results)) if results else "-"
    max_version = str(max(results)) if results else "-"
    cur_version = str(max(versions)) if versions else "-"

    return package, min_version, max_version, cur_version


def get_packages_from_file(main_package):
    output = run_path(f"/home/shh/Development/holoviz/repos/{main_package}/setup.py")
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
