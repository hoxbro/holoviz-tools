from __future__ import annotations

import argparse
import os
import re
import sys
from contextlib import suppress
from functools import cache
from pathlib import Path

import httpx
from rich.console import Console

from utilities import trackpool

SKIP_REFS = {"main", "master", "dev", "develop", "latest", "HEAD"}
HEADERS = {
    "Accept": "application/vnd.github+json",
    "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
    "X-GitHub-Api-Version": "2022-11-28",
}
USES_PATTERN = re.compile(r"(uses:\s*)([A-Za-z0-9_.-]+/[A-Za-z0-9_./:-]+)@([^\s#]+)")

console = Console()


@cache
def github_api(path: str) -> list | None:
    url = f"https://api.github.com/{path}"
    with suppress(httpx.HTTPError):
        return (
            httpx.get(url, headers=HEADERS, params={"per_page": 100, "page": 1})
            .raise_for_status()
            .json()
        )
    return None


def get_names(path: str) -> list[str] | None:
    data = github_api(path)
    if data is None:
        return None
    return [item["name"] for item in data if "name" in item]


def latest_for_ref(repo_ref: tuple[str, str]) -> tuple[str, str, str | None]:
    repo, ref = repo_ref
    if ref in SKIP_REFS:
        return repo, ref, None

    m = re.match(r"^(.*?)(\d+)$", ref)
    if not m:
        return repo, ref, None

    prefix, current_num = m.group(1), int(m.group(2))
    escaped = re.escape(prefix)

    for endpoint in (f"repos/{repo}/tags", f"repos/{repo}/branches"):
        names = get_names(endpoint)
        if names is None:
            continue

        candidates = [
            (int(cm.group(1)), name)
            for name in names
            if (cm := re.fullmatch(escaped + r"(\d+)", name))
        ]
        if candidates:
            best_num, best_name = max(candidates, key=lambda x: x[0])
            return repo, ref, (best_name if best_num > current_num else None)

    return repo, ref, None


def collect_refs(workflow_files: list[Path]) -> list[tuple[str, str]]:
    seen: dict[tuple[str, str], None] = {}
    for path in workflow_files:
        for m in USES_PATTERN.finditer(path.read_text()):
            parts = m.group(2).split("/")
            repo = "/".join(parts[:2])
            key = (repo, m.group(3))
            seen[key] = None
    return list(seen)


def update_files(workflow_files: list[Path], dry_run: bool = False) -> None:
    refs = collect_refs(workflow_files)
    results = trackpool(latest_for_ref, refs, "Checking GitHub Actions")

    updates: dict[tuple[str, str], str | None] = {
        (repo, ref): latest for repo, ref, latest in results
    }

    any_changes = False
    for path in workflow_files:
        text = path.read_text()
        changes: list[tuple[str, str, str]] = []

        def replacer(m: re.Match, _changes: list = changes) -> str:
            action_path = m.group(2)
            ref = m.group(3)
            repo = "/".join(action_path.split("/")[:2])
            latest = updates.get((repo, ref))
            if latest:
                _changes.append((action_path, ref, latest))
                return f"{m.group(1)}{action_path}@{latest}"
            return m.group(0)

        new_text = USES_PATTERN.sub(replacer, text)
        if new_text == text:
            continue

        any_changes = True
        label = "[bold]\\[dry-run][/bold] " if dry_run else ""
        console.print(f"\n{label}[bold]{path}[/bold]")
        col1 = max(len(a) for a, _, _ in changes)
        col2 = max(len(r) for _, r, _ in changes)
        for action_path, ref, latest in changes:
            console.print(f"  {action_path:<{col1}}  @{ref:<{col2}}  ->  @{latest}")
        if not dry_run:
            path.write_text(new_text)

    if not any_changes:
        console.print("\n[green]All actions are up to date.[/green]")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "workflows_dir",
        nargs="?",
        default=".github/workflows",
        help="Directory with workflow YAML files (default: .github/workflows)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Show changes without writing")
    args = parser.parse_args()

    workflows_dir = Path(args.workflows_dir)
    if not workflows_dir.is_dir():
        print(f"Error: {workflows_dir} is not a directory", file=sys.stderr)
        sys.exit(1)

    workflow_files = sorted(list(workflows_dir.glob("*.yml")) + list(workflows_dir.glob("*.yaml")))
    if not workflow_files:
        console.print("No workflow files found.")
        return

    console.print(
        f"Found [bold]{len(workflow_files)}[/bold] workflow file(s) in [bold]{workflows_dir}[/bold]"
    )
    update_files(workflow_files, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
