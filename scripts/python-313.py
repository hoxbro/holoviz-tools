from __future__ import annotations

import httpx

# https://conda-forge.org/status/migration/?name=python313
GREEN, RED, RESET = "\033[0;32m", "\033[0;31m", "\033[0m"

deps = [
    "fastparquet",
    "h5py",
    "numba",
    "numpy",
    "pandas",
    "pyarrow",
    "python-duckdb",
    "pywin32",  # jupyter ecosystem
    "scikit-image",
    "vtk",
]

url = "https://raw.githubusercontent.com/regro/cf-graph-countyfair/master/status/migration_json/python313.json"
data = httpx.get(url).raise_for_status().json()
opts = ["awaiting-parents", "awaiting-pr", "bot-error", "done", "in-pr", "not-solvable"]

for dep in sorted(deps):
    matched = False
    for opt in opts:
        if dep in data[opt]:
            if opt == "done":
                print(f"{GREEN}{dep:<15}{opt}{RESET}")
            else:
                print(f"{RED}{dep:<15}{opt}{RESET}")
            matched = True
            break
    if not matched:
        print(f"{RED}{dep:<15}no-match{RESET}")
