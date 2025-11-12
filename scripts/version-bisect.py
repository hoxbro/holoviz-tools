from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from functools import cache
from hashlib import sha256
from pathlib import Path

import rich_click as click
from rich.console import Console

console = Console()
ts = str(int(time.time()))

# TODO
# - Allow to ignore a version


def log_path(pkg: str) -> Path:
    return Path(f"/tmp/conda_cmp_{pkg}_{ts}.txt")


def load_conda_info():
    cache = Path("/tmp/conda_info.json")
    if cache.exists():
        return json.loads(cache.read_text())

    result = subprocess.run(["conda", "info", "--json"], capture_output=True, check=True)
    info = json.loads(result.stdout)
    cache.write_text(json.dumps(info))
    return info


@cache
def conda_envs():
    result = subprocess.run(["mamba", "env", "list", "--json"], capture_output=True, check=True)
    info = json.loads(result.stdout)
    return [os.path.basename(e) for e in info["envs"]]


def run_in_shell(script: str, log_file: Path) -> bool:
    with open(log_file, "a") as log:
        result = subprocess.run(["bash", "-c", script], stdout=log, stderr=log, check=False)
    return result.returncode == 0


def version_check(
    pkg: str,
    version: str,
    test_command: str,
    conda_sh: Path,
    log_file: Path,
    deps: tuple[str, ...] = (),
) -> bool:
    constraints = [f"{pkg}={version}"]
    constraints.extend(deps)
    constraints_str = " ".join(constraints)
    ev = sha256(constraints_str.encode()).hexdigest()
    env_name = f"tmp_{ev}"
    if env_name not in conda_envs():
        with open(log_file, "a") as log:
            log.write(f"  Creating environment: {env_name}\n")
            result = subprocess.run(
                ["mamba", "create", "-y", "-n", env_name, *constraints, "--offline"],
                stdout=log,
                stderr=log,
                check=False,
            )
            if result.returncode != 0:
                return False

    c = "" if os.path.exists(test_command) else "-c"
    script = f"""
        source "{conda_sh}"
        conda activate {env_name}
        python {c} "{test_command}"
        rc=$?
        conda deactivate
        exit $rc"""
    return run_in_shell(script, log_file)


def get_all_package_versions(package):
    console.print(f"[yellow][+] Getting all versions of '{package}'[/yellow]")
    search = subprocess.run(
        ["mamba", "search", package, "--json", "--offline"], capture_output=True, check=True
    )
    search_json = json.loads(search.stdout)
    all_versions = sorted(
        {pkg["version"] for pkg in search_json["result"]["pkgs"]},
        key=lambda s: list(map(int, s.split("."))),
    )
    return all_versions


@click.command()
@click.argument("package")
@click.argument("good_version")
@click.argument("bad_version")
@click.argument("test_command")
@click.option(
    "--deps",
    multiple=True,
    help="Additional dependencies to install (format: package=version or package)",
)
def cli(
    package: str, good_version: str, bad_version: str, test_command: str, deps: tuple[str, ...]
):
    """
    Bisect a conda package version range to find the first failing version.

    PACKAGE: Name of the package
    GOOD_VERSION: Known good version
    BAD_VERSION: Known bad version
    TEST_COMMAND: Python command to run (quoted)

    Use --deps to specify additional dependencies:
      --deps numpy=1.24 --deps scipy
    """
    log_file = log_path(package)
    conda_info = load_conda_info()
    conda_sh = Path(conda_info["conda_prefix"]) / "etc" / "profile.d" / "conda.sh"

    all_versions = get_all_package_versions(package)

    try:
        g_idx = all_versions.index(good_version)
    except ValueError:
        console.print(f"[red]Error:[/red] {good_version} not found in available versions.")
        sys.exit(1)
    try:
        b_idx = all_versions.index(bad_version)
    except ValueError:
        console.print(f"[red]Error:[/red] {bad_version} not found in available versions.")
        sys.exit(1)

    if g_idx < b_idx:
        versions = all_versions[g_idx : b_idx + 1]
    else:
        versions = all_versions[b_idx : g_idx + 1][::-1]

    console.print(
        f"[green]    Found {len(versions)} versions between {good_version} and {bad_version}[/green]"
    )

    # Step 2: Verify known good
    console.print("[yellow][+] Verifying baseline versions[/yellow]")
    if version_check(package, good_version, test_command, conda_sh, log_file, deps):
        console.print(f"[green]    {good_version} passed[/green]")
    else:
        console.print(f"[red]    {good_version} failed. It must pass. Exiting.[/red]")
        sys.exit(1)

    if version_check(package, bad_version, test_command, conda_sh, log_file, deps):
        console.print(f"[red]    {bad_version} passed. It must fail. Exiting.[/red]")
        sys.exit(1)
    else:
        console.print(f"[green]    {bad_version} failed as expected[/green]")

    # Step 3: Bisect
    console.print("[yellow][+] Starting bisection[/yellow]")
    left, right = 0, len(versions) - 1

    while right - left > 1:
        mid = (left + right) // 2
        ver = versions[mid]
        console.print(f"    Testing {ver}...", end="")
        if version_check(package, ver, test_command, conda_sh, log_file, deps):
            console.print("[green] passed[/green]")
            left = mid
        else:
            console.print("[red] failed[/red]")
            right = mid

    problem = versions[right]
    no_problem = versions[right - 1]
    console.print("[yellow][+] Done[/yellow]")
    console.print(f"[red]    Last failing version is:  {problem}[/red]")
    console.print(f"[green]    First passing version is: {no_problem}[/green]")


if __name__ == "__main__":
    cli()  # pyright: ignore[reportCallIssue]
