import httpx

# https://conda-forge.org/status/migration/?name=python313
GREEN, RED, RESET = "\033[0;32m", "\033[0;31m", "\033[0m"

deps = [
    "fastparquet",
    "numba",
    "pyarrow",
    "vtk",
    "scikit-image",
    "python-duckdb",
    "pywin32",  # jupyter ecosystem
]

url = "https://raw.githubusercontent.com/regro/cf-graph-countyfair/master/status/migration_json/python313.json"
resp = httpx.get(url).raise_for_status()
data = resp.json()
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
