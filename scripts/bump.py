import json
import os
import sys
from pathlib import Path
from subprocess import PIPE, STDOUT, CalledProcessError, run

from packaging.version import InvalidVersion, Version
from rich.console import Console
from rich_menu import live_menu

GREEN, RED, RESET = "\033[92m", "\033[91m", "\033[0m"
console = Console()


def git(*args, **kwargs):
    return (
        run(["git", *args], check=True, stdout=PIPE, stderr=STDOUT, **kwargs)
        .stdout.strip()
        .decode()
    )


def bump_version(version, part):
    # Split the version into its parts
    major, minor, micro, pre = version.major, version.minor, version.micro, version.pre
    pre_letter, pre_num = pre if pre else (None, None)

    # Bump the specified part
    match part:
        case "major":
            major += 1
            minor = 0
            micro = 0
            pre = None
        case "minor":
            minor += 1
            micro = 0
            pre = None
        case "patch":
            micro += 1
            pre = None
        case "a" | "b" | "rc":
            if pre_letter == part:
                pre_num += 1
            else:
                pre_letter = part
                pre_num = 1
            pre = (pre_letter, pre_num)
        case None:
            pre = None
        case _:
            raise ValueError("Invalid part: choose 'major', 'minor', 'patch', 'a', 'b', or 'rc'")

    # Construct the new version string
    new_version = f"v{major}.{minor}.{micro}"
    if pre:
        new_version += f"{pre_letter}{pre_num}"

    return new_version


def get_possible_versions(current_version):
    if current_version.pre:
        parts = ["a", "b", "rc", None]
        return [bump_version(current_version, part=part) for part in parts]
    else:
        return [
            bump_version(Version(bump_version(current_version, part=p1)), part=p2)
            for p1 in ["patch", "minor", "major"]
            for p2 in ["a", "b", "rc"]
        ]


def js_update(package, version):
    package_file = Path(f"{package}/package.json")
    if not package_file.exists():
        return

    print(f"{GREEN}[{package}]{RESET} Updating package.json")
    js_ver = version.removeprefix("v")
    for n in ["a", "b", "c"]:
        js_ver = js_ver.replace(n, f"-{n}.")

    package_json = json.loads(package_file.read_text())
    package_json["version"] = js_ver
    package_file.write_text(f"{json.dumps(package_json, indent=2)}\n")
    print(f"{GREEN}[{package}]{RESET} Updating package-lock.json")
    try:
        run(["npm", "update", package], cwd=package, capture_output=True, check=True)
    except CalledProcessError as e:
        print(f"{RED}[{package}]{RESET} Failed to update package-lock.json: {e}")
        sys.exit(1)

    git("add", f"{package}/package.json", f"{package}/package-lock.json")
    git("commit", "-m", f"Update package.json to {js_ver}", "--no-verify")


def validate_version(package, version):
    try:
        version_info = Version(version)
        if version_info.pre:
            version = f"v{version_info}"
        else:
            version = f"v{version_info.major}.{version_info.minor}.{version_info.micro}"
    except InvalidVersion:
        print(f"{RED}[{package}]{RESET} Invalid version: {version}")
        sys.exit(1)
    try:
        git("rev-parse", "HEAD", version)  # Will fail if it does not exits
        print(f"{RED}[{package}]{RESET} Tag {version} already exists")
        sys.exit(1)
    except CalledProcessError:
        pass
    return version


def main():
    directory = git("rev-parse", "--show-toplevel")
    current_tag = git("describe", "--tags", "--abbrev=0")
    package = os.path.basename(directory)
    os.chdir(directory)

    print(f"{GREEN}[{package}]{RESET} Current version: {current_tag}")

    version_options = get_possible_versions(Version(current_tag))
    new_version = live_menu([*version_options, "input"], console, title="Select a version")
    if new_version == "input":
        new_version = console.input("Enter a version: ")
    new_version = validate_version(package, new_version)
    print(f"{GREEN}[{package}]{RESET} New version: {new_version}")

    js_update(package, new_version)

    commit = git("rev-parse", "HEAD")
    git("tag", new_version, commit, "-m", new_version.replace("v", "Version "))
    print(f"{GREEN}[{package}]{RESET} Tagged {new_version}")


if __name__ == "__main__":
    main()
