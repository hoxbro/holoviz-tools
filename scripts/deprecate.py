import ast
import os
import sys
from subprocess import check_output

import panel as pn
from packaging.version import Version

CUR_VERSION = Version(pn.__version__)
BASE_CUR_VERSION = Version(CUR_VERSION.base_version)
PATH = os.path.dirname(pn.__file__)
GREEN, RED, RESET = "\033[92m", "\033[91m", "\033[0m"


class StackLevelChecker(ast.NodeVisitor):
    def __init__(self, file) -> None:
        self.file = file
        self.deprecations = set()

    def _check_version(self, node: ast.Call) -> None:
        if node.func.id != "deprecated":
            return
        deprecated_version = Version(node.args[0].s)
        if BASE_CUR_VERSION >= deprecated_version:
            msg = (
                f"{RED}{self.file}:{node.lineno}:{node.col_offset}: "
                f"Found version '{deprecated_version}' in 'deprecated' should have been removed.{RESET}"
            )
            self.deprecations.add((True, msg))
        else:
            msg = (
                f"{GREEN}{self.file}:{node.lineno}:{node.col_offset}: "
                f"Found version '{deprecated_version}' in 'deprecated'.{RESET}"
            )
            self.deprecations.add((False, msg))

    def visit_Call(self, node: ast.Expr) -> None:
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            self._check_version(node)

        self.generic_visit(node)


def check_file(file) -> int:
    with open(os.path.join(PATH, file)) as f:
        tree = ast.parse(f.read())

    stacklevel_checker = StackLevelChecker(file)
    stacklevel_checker.visit(tree)

    errs = 0
    for err, msg in stacklevel_checker.deprecations:
        if err:
            errs += 1
        print(msg)

    return errs


def main() -> None:
    files = check_output(["git", "ls-files", "."], cwd=PATH)
    deprecations = 0
    print(f"Current version is '{CUR_VERSION}'.")
    for file in files.decode().split("\n"):
        if file.endswith(".py"):
            deprecations += check_file(file)
    sys.exit(deprecations > 0)


if __name__ == "__main__":
    main()
