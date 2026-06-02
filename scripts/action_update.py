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
USES_PATTERN = re.compile(
    r"(uses:\s*)([A-Za-z0-9_.-]+/[A-Za-z0-9_./:-]+)@([^\s#]+)([ \t]*#[^\n]*)?"
)
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)

HOLOVIZ_TASKS_REPO = "holoviz-dev/holoviz_tasks"
HOLOVIZ_TASKS_RENAMES = {
    f"{HOLOVIZ_TASKS_REPO}/pixi_install": f"{HOLOVIZ_TASKS_REPO}/pixi-install",
    f"{HOLOVIZ_TASKS_REPO}/pixi_lock": f"{HOLOVIZ_TASKS_REPO}/pixi-lock",
}

console = Console()


@cache
def github_api(path: str) -> list | dict:
    url = f"https://api.github.com/{path}"
    with suppress(httpx.HTTPError):
        return (
            httpx.get(url, headers=HEADERS, params={"per_page": 100, "page": 1})
            .raise_for_status()
            .json()
        )


def get_names(path: str) -> list[str] | None:
    data = github_api(path)
    if not isinstance(data, list):
        return None
    return [item["name"] for item in data if "name" in item]


@cache
def resolve_sha(repo: str, ref: str) -> str | None:
    """Resolve a tag or branch name to its commit SHA (handles annotated and lightweight tags)."""
    for git_ref in (f"tags/{ref}", f"heads/{ref}"):
        data = github_api(f"repos/{repo}/git/ref/{git_ref}")
        if not isinstance(data, dict):
            continue
        obj = data.get("object", {})
        if obj.get("type") == "tag":
            tag_data = github_api(f"repos/{repo}/git/tags/{obj['sha']}")
            if isinstance(tag_data, dict):
                return tag_data.get("object", {}).get("sha")
        return obj.get("sha")
    return None


def _parse_version(s: str) -> tuple[int, ...]:
    return tuple(int(x) for x in s.split("."))


def find_latest_tag(repo: str, ref: str, expand: bool = False) -> str | None:
    """Return the latest tag/branch name for a versioned ref, or None if already current."""
    if ref in SKIP_REFS:
        return None

    m = re.match(r"^([^0-9]*)(\d+(?:\.\d+)*)$", ref)
    if not m:
        return None

    prefix = m.group(1)
    version_str = m.group(2)
    current_version = _parse_version(version_str)
    escaped = re.escape(prefix)
    has_dot = "." in version_str
    expanding = expand and not has_dot
    version_pattern = escaped + (r"(\d+(?:\.\d+)*)" if (has_dot or expanding) else r"(\d+)")

    for endpoint in (f"repos/{repo}/tags", f"repos/{repo}/branches"):
        names = get_names(endpoint)
        if names is None:
            continue

        candidates = [
            (_parse_version(cm.group(1)), name)
            for name in names
            if (cm := re.fullmatch(version_pattern, name))
            and (
                not expanding
                or (
                    _parse_version(cm.group(1))[: len(current_version)] == current_version
                    and len(_parse_version(cm.group(1))) > len(current_version)
                )
            )
        ]
        if candidates:
            best_version, best_name = max(candidates, key=lambda x: x[0])
            return best_name if best_version > current_version else None

    return None


def latest_for_ref(
    repo_ref: tuple[str, str, str | None, bool, bool, bool],
) -> tuple[str, str, str | None, str | None]:
    """
    Returns (repo, ref, latest_tag, latest_sha).
    For SHA-pinned refs: latest_sha holds the new commit hash to write.
    For tag/branch refs: latest_tag holds the new ref to write, latest_sha is None.
    With pin=True: tag/branch refs are also resolved to a SHA.
    With expand=True: short refs like v1 are expanded to the latest v1.X.Y tag.
    With mutable=True: check for updates in mutable tags (e.g. v1).
    """
    repo, ref, current_tag, pin, expand, mutable = repo_ref

    if SHA_PATTERN.match(ref):
        if current_tag is None:
            return repo, ref, None, None
        latest_tag = find_latest_tag(repo, current_tag, expand=expand)
        if latest_tag is None:
            if mutable and "." not in current_tag:
                latest_tag = current_tag
            else:
                return repo, ref, None, None
        new_sha = resolve_sha(repo, latest_tag)
        if new_sha == ref:
            return repo, ref, None, None
        return repo, ref, latest_tag, new_sha

    latest_tag = find_latest_tag(repo, ref, expand=expand)
    if pin:
        effective_tag = latest_tag or ref
        new_sha = resolve_sha(repo, effective_tag)
        return repo, ref, effective_tag, new_sha
    return repo, ref, latest_tag, None


def collect_refs(
    workflow_files: list[Path],
    pin: bool = False,
    expand: bool = False,
    mutable: bool = False,
    include: str | None = None,
) -> list[tuple[str, str, str | None, bool, bool, bool]]:
    seen: dict[tuple[str, str], str | None] = {}
    for path in workflow_files:
        for m in USES_PATTERN.finditer(path.read_text()):
            action_path = m.group(2)
            if include and include not in action_path:
                continue
            parts = action_path.split("/")
            repo = "/".join(parts[:2])
            ref = m.group(3)
            comment = m.group(4) or ""
            current_tag: str | None = None
            if SHA_PATTERN.match(ref):
                tag_match = re.search(r"#\s*(\S+)", comment)
                if tag_match:
                    current_tag = tag_match.group(1)
            key = (repo, ref)
            if key not in seen:
                seen[key] = current_tag
    return [(repo, ref, tag, pin, expand, mutable) for (repo, ref), tag in seen.items()]


def update_files(
    workflow_files: list[Path],
    dry_run: bool = False,
    pin: bool = False,
    expand: bool = False,
    mutable: bool = False,
    include: str | None = None,
) -> None:
    refs = collect_refs(workflow_files, pin=pin, expand=expand, mutable=mutable, include=include)

    for repo, ref, current_tag, *_ in refs:
        if SHA_PATTERN.match(ref) and current_tag is None:
            console.print(
                f"[yellow]Warning: cannot update {repo}@{ref} (SHA-pinned with no version comment)[/yellow]"
            )

    results = trackpool(latest_for_ref, refs, "Checking GitHub Actions")

    updates: dict[tuple[str, str], tuple[str, str | None] | None] = {
        (repo, ref): (latest_tag, latest_sha) if latest_tag else None
        for repo, ref, latest_tag, latest_sha in results
    }

    any_changes = False
    for path in workflow_files:
        text = path.read_text()
        changes: list[tuple[str, str, str]] = []

        def replacer(m: re.Match, _changes: list = changes) -> str:
            action_path = m.group(2)
            ref = m.group(3)
            repo = "/".join(action_path.split("/")[:2])

            update = updates.get((repo, ref))

            new_action_path = action_path
            if action_path in HOLOVIZ_TASKS_RENAMES:
                new_action_path = HOLOVIZ_TASKS_RENAMES[action_path]

            if update:
                latest_tag, latest_sha = update
                if latest_sha:
                    _changes.append(
                        (new_action_path, ref[:12], f"{latest_sha[:12]} ({latest_tag})")
                    )
                    return f"{m.group(1)}{new_action_path}@{latest_sha} # {latest_tag}"
                _changes.append((new_action_path, ref, latest_tag))
                return f"{m.group(1)}{new_action_path}@{latest_tag}"

            if new_action_path != action_path:
                _changes.append((action_path, ref, f"{new_action_path}@{ref}"))
                return f"{m.group(1)}{new_action_path}@{ref}"

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
    parser.add_argument(
        "--pin", action="store_true", help="Convert tag/branch refs to SHA-pinned versions"
    )
    parser.add_argument(
        "--expand",
        action="store_true",
        help="Expand short version refs (e.g. v1) to the latest full version (e.g. v1.2.3)",
    )
    parser.add_argument(
        "--mutable",
        action="store_true",
        help="Check for updates in mutable tags (e.g. v1) even if the tag name hasn't changed",
    )
    parser.add_argument(
        "--include",
        help="Only update actions whose name contains this string",
    )
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
    update_files(
        workflow_files,
        dry_run=args.dry_run,
        pin=args.pin,
        expand=args.expand,
        mutable=args.mutable,
        include=args.include,
    )


if __name__ == "__main__":
    main()
