import os

import yaml
from pandas.io.clipboard import clipboard_set
from rich.console import Console
from rich.table import Table

console = Console()


def get_env(file, env, os):
    with open(file) as f:
        data = f.read()
    data = data.split("\npackages:")[0]
    spaces = "  "

    ns = [f"{spaces}{env}:"]
    for n in data.split(f"\n{spaces}{env}:")[1].split("\n")[1:]:
        if not n.startswith(spaces + " "):
            break
        ns.append(n)
    data = "\n".join(ns)

    spaces = "      "
    ns = [f"{spaces}{os}:"]
    for n in data.split(f"\n{spaces}{os}:")[1].split("\n")[1:]:
        if not n.startswith(f"{spaces}-"):
            break
        ns.append(n)
    data = "\n".join(ns)

    return yaml.safe_load(data)[os]


repo = "holoviews"
good_run = "/home/shh/Downloads/bad_pixi.lock"
bad_run = "/home/shh/Downloads/bad-pixi2.lock"
env = "test-312"
arch = "linux-64"

good_env = get_env(good_run, env, arch)
bad_env = get_env(bad_run, env, arch)


good_run = "2222"  # tmp
bad_run = "2223"  # tmp

bad_list = {os.path.basename(next(iter(p.values()))) for p in bad_env}
good_list = {os.path.basename(next(iter(p.values()))) for p in good_env}
good_only = good_list - bad_list
bad_only = bad_list - good_list

packages = {p.split("-")[:-2][0] for p in good_only | bad_only}
info = []
for p in sorted(packages):
    good = [g for g in good_only if g.startswith(p)]
    bad = [g for g in bad_only if g.startswith(p)]
    info.append((p, good[0] if good else "-", bad[0] if bad else "-"))

code = f"holoviz artifact {repo} {good_run} {bad_run} --env {env} --arch {arch}"
clipboard_set(code)

table = Table(
    title=f"Difference in packages on {repo!r} for environment {env!r} on {arch!r}",
    caption=f"created with: `{code}`",
)
table.add_column("Package", min_width=15)
table.add_column(f"Only in good lock (#{good_run})", style="green")
table.add_column(f"Only in bad lock (#{bad_run})", style="red")

for i in info:
    table.add_row(*i)

console.print(table)
