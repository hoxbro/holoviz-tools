#!/usr/bin/env bash

set -euo pipefail

CONDA_ENV=holoviz
PACKAGES=(panel holoviews hvplot param datashader geoviews lumen holonote spatialpandas)
CUDA_PACKAGES=(cupy)
UNIX_PACKAGES=(memray tsdownsample)
ALL_PACKAGES=(
    python=3.12

    # Visualization
    bokeh plotly matplotlib-base seaborn-base altair

    # Data processing
    numpy pandas xarray polars numba
    dask-core scipy scikit-image dask-expr

    # Data loading
    lxml openpyxl fastparquet pooch pyarrow
    # "intake<2" intake-sql intake-parquet intake-xarray
    s3fs h5netcdf zarr hdf5
    ibis-sqlite sqlalchemy python-duckdb
    bokeh_sampledata

    # Notebook
    jupyterlab ipywidgets jupyterlab_code_formatter jupyterlab-myst
    pyviz_comms ipywidgets_bokeh jupyter_bokeh

    # Testing
    pytest pytest-xdist pytest-rerunfailures parameterized pytest-asyncio hypothesis
    pytest-randomly detect-test-pollution nbval microsoft::pytest-playwright microsoft::playwright

    # Geo
    geopandas rioxarray rasterio cartopy geodatasets

    # Dev Tools
    nodejs "debugpy==1.8.5"
    pyinstrument snakeviz psutil py-spy tuna
    setuptools_scm watchfiles cachecontrol lockfile

    # Typing
    mypy typing-extensions pandas-stubs
    types-bleach types-croniter types-Markdown types-psutil
    types-requests types-tqdm

    # Tooling
    rich-click httpx platformdirs zstandard

    # Misc
    tqdm colorcet
    markdown markdown-it-py mdit-py-plugins linkify-it-py
)

create_environment() {
    conda env remove -n $CONDA_ENV -y >/dev/null || true
    mamba create -n $CONDA_ENV "${ALL_PACKAGES[@]}" -y -c microsoft -c bokeh/label/rc

    # https://docs.bokeh.org/en/latest/docs/dev_guide/setup.html
    conda env config vars set BOKEH_RESOURCES=server -n $CONDA_ENV
    conda env config vars set BOKEH_BROWSER=none -n $CONDA_ENV
    conda env config vars set BOKEH_MINIFIED=false -n $CONDA_ENV
    conda env config vars set BOKEH_PRETTY=true -n $CONDA_ENV
    conda env config vars set USE_PYGEOS=0 -n $CONDA_ENV
    conda env config vars set HYPOTHESIS_MAX_EXAMPLES=1 -n $CONDA_ENV
}

_install() (
    set -euxo pipefail

    if [ -d "$1" ]; then
        cd "$1"

        # Save current branch and stash files
        BRANCH=$(git branch --show-current)
        DIRTY=$(git status -s -uno | wc -l)
        git stash -m "setup script $(date +%Y-%m-%d_%H.%M)"
        git checkout main

        # Update main
        git fetch origin
        git pull origin --tags --force
        git reset --hard origin/main
        git fetch --all --prune

        # Go back branch and unstash files
        git checkout "$BRANCH"
        if ((DIRTY > 0)); then git stash pop; fi
    else
        git clone git@github.com:holoviz/"$1".git
        cd "$1"
    fi

    if [ -f .pre-commit-config.yaml ]; then
        pre-commit install -t=pre-commit --install-hooks
    fi

    # Install the package
    conda uninstall --force --offline --yes "$1" || true
    python -m pip install --no-deps --disable-pip-version-check -ve .
)

install() (
    set +e
    _install "$1" &>"/tmp/holoviz_$1_$(date +%Y-%m-%d_%H.%M).log"
    if (($? > 0)); then
        echo "!!! Failed installing $1 !!!"
    else
        echo "Finished installing $1"
    fi
    echo -ne "\r" # Clean new line
    set -e
)

SECONDS=0

# Create the repo directory
mkdir -p "$HOLOVIZ_REP"
cd "$HOLOVIZ_REP"

# Conda info and activate
CONDA_INFO=$(conda info --json)
CONDA_DIR=$(echo "$CONDA_INFO" | jq -r .conda_prefix)
PLATFORM=$(echo "$CONDA_INFO" | jq -r .platform)
CUDA=$(echo "$CONDA_INFO" | jq -r 'any(.virtual_pkgs[]; .[0] == "__cuda")')
source "$CONDA_DIR/etc/profile.d/conda.sh"
conda activate base

# Add custom packages
if [ "$CUDA" == "true" ]; then ALL_PACKAGES+=("${CUDA_PACKAGES[@]}"); fi
if [[ "$PLATFORM" =~ ^(linux-64|osx-arm64|osx-64)$ ]]; then ALL_PACKAGES+=("${UNIX_PACKAGES[@]}"); fi

# Starting up the machine
echo "Creating environment $CONDA_ENV"
create_environment
conda activate "$CONDA_ENV"
for p in "${PACKAGES[@]}"; do install "$p" & done
python -m playwright install &>/dev/null &
wait

# Clean up
rm -f "$CONDA_DIR"/envs/"$CONDA_ENV"/Library/usr/bin/cygpath.exe
rm -f ~/.config/dask/dask.yaml
rm -f "$(which holoviews)"

echo -e "\nRun time: $(((SECONDS / 60) % 60)) min and $((SECONDS % 60)) sec"
