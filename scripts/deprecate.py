from __future__ import annotations

import ast
import os
import sys
import warnings
from importlib.util import find_spec
from typing import cast

import rich_click as click
from packaging.version import Version

from _artifact import console
from rich_menu import argument_menu
from utilities import GREEN, RED, RESET, exit_print, git

REPOS = ["panel", "holoviews"]


class StackLevelChecker(ast.NodeVisitor):
    def __init__(self, file, base_version) -> None:
        self.file = file
        self.base_version = base_version
        self.deprecations = 0

    def _check_version(self, node: ast.Call) -> None:
        func = cast(ast.Name, node.func)
        if func.id != "deprecated":
            return
        args = cast(list[ast.Constant], node.args)
        deprecated_version = Version(args[0].value)
        if self.base_version >= deprecated_version:
            msg = (
                f"{RED}{self.file}:{node.lineno}:{node.col_offset}: "
                f"Found version '{deprecated_version}' in 'deprecated' should have been removed.{RESET}"
            )
            self.deprecations += 1
        else:
            msg = (
                f"{GREEN}{self.file}:{node.lineno}:{node.col_offset}: "
                f"Found version '{deprecated_version}' in 'deprecated'.{RESET}"
            )
        print(msg)

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            self._check_version(node)

        self.generic_visit(node)


def get_info(module):
    spec = find_spec(module)
    if spec is None:
        exit_print(f"Module '{module}' not found.")
    if spec.submodule_search_locations is None:
        exit_print(f"Module '{module}' is not a package.")
    path = spec.submodule_search_locations[0]
    tag = git("describe", "--abbrev=0", "main", cwd=path)
    version = Version(tag)
    base_version = Version(version.base_version)
    return version, base_version, path


def check_file(file, path, base_version) -> int:
    with open(os.path.join(path, file)) as f:
        data = f.read()

    if "deprecated" not in data:
        return 0

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SyntaxWarning)
        tree = ast.parse(data, file)

    stacklevel_checker = StackLevelChecker(file, base_version)
    stacklevel_checker.visit(tree)
    return stacklevel_checker.deprecations


@click.command(context_settings={"show_default": True})
@argument_menu("repo", choices=REPOS, console=console, title="Select a repo")
def main(repo) -> None:
    version, base_version, path = get_info(repo)
    files = git("ls-files", ".", cwd=path)
    deprecations = 0
    print(f"Latest tag of {repo} on main is '{version}'.")
    for file in files.split("\n"):
        if file.endswith(".py"):
            deprecations += check_file(file, path, base_version)
    sys.exit(deprecations > 0)


if __name__ == "__main__":
    main()  # pyright: ignore[reportCallIssue]
