#!/usr/bin/env python3

from __future__ import annotations

import ast
import json
import os
import re
import uuid
from contextlib import suppress
from datetime import date
from pathlib import Path

import httpx
from bs4 import BeautifulSoup
from pandas.io.clipboard import clipboard_get, clipboard_set

PATH = Path(os.environ["HOLOVIZ_DEV"]).resolve() / "development"


def get_id():
    return str(uuid.uuid4())


def main(url):
    codeblocks, repo, filename = get_code_and_info(url)
    notebook = create_notebook(codeblocks, url)
    save_notebook(repo, filename, notebook)
    python = create_python(codeblocks, url)
    save_python(repo, filename, python)


def get_code_and_info(url):
    if "github.com" in url:
        codeblocks, repo, filename = _get_github(url)
    elif "discourse.holoviz.org" in url:
        codeblocks, repo, filename = _get_discourse(url)
    else:
        msg = f"Not valid url: {url}"
        raise ValueError(msg)

    codeblocks = sanitize_codeblock(codeblocks)
    assert len(codeblocks) > 0

    return codeblocks, repo, filename


def sanitize_string(s):
    return "".join(x for x in s.strip() if x.isalnum() or x == " ").replace(" ", "_")


def sanitize_codeblock(codeblocks):
    new = []
    for n in codeblocks:
        with suppress(SyntaxError):
            n = n.text
            ast.parse(n)
            new.append(n)
    return new


def _get_github(url):
    resp = httpx.get(url).raise_for_status()

    soup = BeautifulSoup(resp.text, features="html.parser")
    codeblocks = soup.find_all("div", class_={"highlight", "notranslate"})

    info = soup.find("title").text.split(" · ")
    number = info[1].split("#")[1]
    title = sanitize_string(info[0])
    repo = "dev_" + info[2].split("/")[1]
    filename = f"{number}_{title}"

    return codeblocks, repo, filename


def _get_discourse(url):
    url = url + ".json"
    resp = httpx.get(url).raise_for_status()

    data = resp.json()
    regex = re.compile("lang-")
    codeblocks = []
    for post in data["post_stream"]["posts"]:
        soup = BeautifulSoup(post["cooked"], features="html.parser")
        codeblocks.extend(soup.find_all(True, class_=regex))

    number = data["id"]
    title = sanitize_string(data["title"])
    repo = "discourse"
    filename = f"{number}_{title}"

    return codeblocks, repo, filename


def create_notebook(codeblocks, url):
    notebook = {
        "cells": [],
        "metadata": {"language_info": {"name": "python", "pygments_lexer": "ipython3"}},
        "nbformat": 4,
        "nbformat_minor": 5,
    }

    info = f"Downloaded from {url} at {date.today()}."
    header = {"cell_type": "markdown", "metadata": {}, "source": [info], "id": get_id()}
    notebook["cells"].append(header)

    empty_code_cell = {
        "cell_type": "code",
        "metadata": {},
        "outputs": [],
        "source": [],
        "execution_count": None,
    }
    for code in codeblocks:
        cell = empty_code_cell.copy()
        cell["id"] = get_id()
        cell["source"] = [c + "\n" for c in code.split("\n")]
        notebook["cells"].append(cell)

    return notebook


def create_python(codeblocks, url):
    info = f"# Downloaded from {url} at {date.today()}.\n\n"

    python_file = [info]

    for i, code in enumerate(codeblocks):
        if i == 0 and "import panel as pn" not in code:
            code = "import panel as pn\n" + code
        # if '.servable(' not in code:
        #     n
        python_file.extend([f"# %% Codeblock {i+1}\n", code, "\n\n"])

    return python_file


def link(uri, label=None, parameters=None):
    # https://gist.github.com/egmontkob/eb114294efbcd5adb1944c9f3cb5feda
    if label is None:
        label = uri
    if parameters is None:
        parameters = ""

    # OSC 8 ; params ; URI ST <name> OSC 8 ;; ST
    escape_mask = "\033]8;{};{}\033\\{}\033]8;;\033\\"

    return escape_mask.format(parameters, uri, label)


def save_notebook(repo, filename, notebook):
    repo_path = PATH / repo
    repo_path.mkdir(exist_ok=True)
    file = repo_path / f"{filename}.ipynb"

    here_url = (
        f"http://localhost:8888/lab/workspaces/auto-W/tree/development/{repo}/{filename}.ipynb"
    )
    clipboard_set(here_url)
    here_url = link(here_url, "here")

    if file.exists():
        print(f"{repo.replace('dev_', '')} #{filename.split('_')[0]} already exists {here_url}")
        return

    with open(file, "w") as f:
        json.dump(notebook, f)

    print(f"{repo.replace('dev_', '')} #{filename.split('_')[0]} saved {here_url}")


def save_python(repo, filename, python):
    repo_path = PATH / repo
    repo_path.mkdir(exist_ok=True)
    file = repo_path / f"{filename}.py"

    if file.exists():
        print(f"{repo.replace('dev_', '')} #{filename.split('_')[0]} already exists:")
        print(f"\t{file}")
        return

    with open(file, "w") as f:
        f.write("".join(python))

    print(f"{repo.replace('dev_', '')} #{filename.split('_')[0]} saved:")
    print(f"\t{file}")


if __name__ == "__main__":
    url = clipboard_get()
    main(url)
