from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import rich_click as click
from rich.console import Console

console = Console()
ts = str(int(time.time()))

# TODO
# - Allow script files instead of code
# - Allow to specify other dependencies


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


def run_in_shell(script: str, log_file: Path) -> bool:
    with open(log_file, "a") as log:
        result = subprocess.run(["bash", "-c", script], stdout=log, stderr=log, check=False)
    return result.returncode == 0


def test_version(pkg: str, version: str, test_cmd: str, conda_sh: Path, log_file: Path) -> bool:
    ev = version.replace(".", "_")
    env_name = f"tmp_{ts}_{ev}"
    with open(log_file, "a") as log:
        log.write(f"  Creating environment: {env_name}\n")
        result = subprocess.run(
            ["mamba", "create", "-y", "-n", env_name, f"{pkg}={version}", "--offline"],
            stdout=log,
            stderr=log,
            check=False,
        )
        if result.returncode != 0:
            return False

    script = f"""
        source "{conda_sh}"
        conda activate {env_name}
        python -c "{test_cmd}"
        rc=$?
        conda deactivate
        exit $rc
    """
    return run_in_shell(script, log_file)


@click.command()
@click.argument("package")
@click.argument("good_version")
@click.argument("bad_version")
@click.argument("test_command")
def cli(package: str, good_version: str, bad_version: str, test_command: str):
    """
    Bisect a conda package version range to find the first failing version.

    PACKAGE: Name of the package
    GOOD_VERSION: Known good version
    BAD_VERSION: Known bad version
    TEST_COMMAND: Python command to run (quoted)
    """
    log_file = log_path(package)
    conda_info = load_conda_info()
    conda_sh = Path(conda_info["conda_prefix"]) / "etc" / "profile.d" / "conda.sh"

    console.print(f"[yellow][+] Getting all versions of '{package}'[/yellow]")
    search = subprocess.run(
        ["mamba", "search", package, "--json", "--offline"], capture_output=True, check=True
    )
    search_json = json.loads(search.stdout)
    all_versions = sorted(
        {pkg["version"] for pkg in search_json["result"]["pkgs"]},
        key=lambda s: list(map(int, s.split("."))),
    )

    try:
        g_idx = all_versions.index(good_version)
        b_idx = all_versions.index(bad_version)
    except ValueError:
        console.print(
            f"[red]Error:[/red] Either {good_version} or {bad_version} not found in available versions."
        )
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
    if test_version(package, good_version, test_command, conda_sh, log_file):
        console.print(f"[green]    {good_version} passed[/green]")
    else:
        console.print(f"[red]    {good_version} failed. It must pass. Exiting.[/red]")
        sys.exit(1)

    if test_version(package, bad_version, test_command, conda_sh, log_file):
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
        if test_version(package, ver, test_command, conda_sh, log_file):
            console.print("[green] passed[/green]")
            left = mid
        else:
            console.print("[red] failed[/red]")
            right = mid

    problem = versions[right]
    console.print("[yellow][+] Done[/yellow]")
    console.print(f"[green]    First failing version is: {problem}[/green]")


if __name__ == "__main__":
    cli()  # pyright: ignore[reportCallIssue]
