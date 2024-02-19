import ast
import os
import sys
import warnings
from functools import cache
from importlib import import_module
from subprocess import check_output

from packaging.version import Version

if sys.stdout.isatty():
    GREEN, RED, RESET = "\033[92m", "\033[91m", "\033[0m"
else:
    GREEN = RED = RESET = ""


class StackLevelChecker(ast.NodeVisitor):
    def __init__(self, file, base_version) -> None:
        self.file = file
        self.base_version = base_version
        self.deprecations = set()

    def _check_version(self, node: ast.Call) -> None:
        if node.func.id != "deprecated":
            return
        deprecated_version = Version(node.args[0].value)
        if self.base_version >= deprecated_version:
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


@cache
def get_info(module):
    mod = import_module(module)
    version = Version(mod.__version__)
    base_version = Version(version.base_version)
    path = os.path.dirname(mod.__file__)
    return version, base_version, path


def check_file(file, module) -> int:
    _, base_version, path = get_info(module)
    with open(os.path.join(path, file)) as f:
        data = f.read()

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SyntaxWarning)
        tree = ast.parse(data, file)

    stacklevel_checker = StackLevelChecker(file, base_version)
    stacklevel_checker.visit(tree)

    errs = 0
    for err, msg in stacklevel_checker.deprecations:
        if err:
            errs += 1
        print(msg)

    return errs


def main(module) -> None:
    version, _, path = get_info(module)
    files = check_output(["git", "ls-files", "."], cwd=path)
    deprecations = 0
    print(f"Current version of {module} is '{version}'.")
    for file in files.decode().split("\n"):
        if file.endswith(".py"):
            deprecations += check_file(file, module)
    sys.exit(deprecations > 0)


if __name__ == "__main__":
    module = sys.argv[1] if len(sys.argv) > 1 else "panel"
    main(module)
