import ast
import os
import sys
from subprocess import check_output

import panel as pn
from packaging.version import Version

CUR_VERSION = Version(pn.__version__)
BASE_CUR_VERSION = Version(CUR_VERSION.base_version)
PATH = os.path.dirname(pn.__file__)


class StackLevelChecker(ast.NodeVisitor):
    def __init__(self, file) -> None:
        self.file = file
        self.violations = set()

    def _check_version(self, node: ast.Call) -> None:
        if node.func.id != "deprecated":
            return
        deprecated_version = Version(node.args[0].s)
        if BASE_CUR_VERSION >= deprecated_version:
            self.violations.add(
                f"{self.file}:{node.lineno}:{node.col_offset}: "
                f"Found version '{deprecated_version}' in 'deprecated' should have been removed. "
                f"Current version is '{CUR_VERSION}'."
            )

    def visit_Call(self, node: ast.Expr) -> None:
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            self._check_version(node)

        self.generic_visit(node)


def check_file(file) -> int:
    with open(os.path.join(PATH, file)) as f:
        tree = ast.parse(f.read())

    stacklevel_checker = StackLevelChecker(file)
    stacklevel_checker.visit(tree)

    for v in stacklevel_checker.violations:
        print(v)

    return len(stacklevel_checker.violations)


def main() -> None:
    files = check_output(["git", "ls-files", "."], cwd=PATH)
    violations = 0
    for file in files.decode().split("\n"):
        if file.endswith(".py"):
            violations += check_file(file)
    sys.exit(violations > 0)

if __name__ == "__main__":
    main()
