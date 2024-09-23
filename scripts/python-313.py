import httpx

# https://conda-forge.org/status/migration/?name=python313

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
            print(f"{dep:<15}{opt}")
            matched = True
            break
    if not matched:
        print(f"{dep:<15}no-match")
