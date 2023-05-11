import importlib
import re
from inspect import getfile
from pathlib import Path

import nbformat

PACKAGES = ["holoviews", "panel", "hvplot", "datashader", "geoviews"]

root = lambda p: Path(getfile(__import__(p))).parents[1]


def extract_imports(s):
    i1 = re.findall(r"^import (.+?)[\W|$]", s, re.MULTILINE)
    i2 = re.findall(r"^from (.+?)\W", s, re.MULTILINE)
    return set(i1 + i2)


def get_nb_imports(file):
    nb = nbformat.read(file, nbformat.NO_CONVERT)
    imports = set()
    for cell in nb["cells"]:
        if cell["cell_type"] == "code":
            imports |= extract_imports(cell["source"])

    return imports


def main(package):

    imports = set()
    for file in root(package).rglob("*.ipynb"):
        imports |= get_nb_imports(file)

    for i in sorted(imports):
        if i.startswith("."):
            continue
        available = importlib.util.find_spec(i.strip().lower()) is not None
        if not available:
            print(i)


PACKAGES = ["holoviews", "panel", "hvplot", "datashader", "geoviews"]

for p in PACKAGES:
    print(p)
    main(p)
