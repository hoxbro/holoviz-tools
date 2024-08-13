#!/usr/bin/env bash

set -euo pipefail

CONDA_ENV=holoviz
DEV_BOKEH=""
PACKAGES=(panel holoviews hvplot param datashader geoviews lumen holonote spatialpandas)
NVIDIA_PACKAGES=(cupy)
UNIX_PACKAGES=(memray tsdownsample)
ALL_PACKAGES=(
    python=3.12

    # Visualization
    bokeh plotly matplotlib seaborn altair

    # Data processing
    numpy pandas xarray polars numba
    dask-core scipy scikit-image dask-expr

    # Data loading
    lxml openpyxl fastparquet pooch pyarrow
    "intake<2" intake-sql intake-parquet intake-xarray
    s3fs h5netcdf zarr hdf5
    ibis-sqlite sqlalchemy python-duckdb
    bokeh_sampledata

    # Notebook
    jupyterlab ipywidgets jupyterlab_code_formatter jupyterlab-myst
    ipywidgets_bokeh jupyter_bokeh

    # Testing
    pytest pytest-xdist pytest-rerunfailures parameterized pytest-asyncio
    pytest-randomly detect-test-pollution nbval microsoft::pytest-playwright microsoft::playwright

    # Geo
    geopandas rioxarray rasterio spatialpandas cartopy geodatasets

    # Dev Tools
    nodejs python-build debugpy ruff
    pyinstrument snakeviz psutil py-spy tuna asv
    pyviz::nbsite

    # Typing
    mypy typing-extensions pandas-stubs
    types-bleach types-croniter types-Markdown types-psutil
    types-requests types-tqdm

    # Misc
    diskcache streamz aiohttp rich-click setuptools_scm watchfiles
    pyviz_comms tqdm pyct httpx colorcet
    markdown markdown-it-py mdit-py-plugins linkify-it-py
    cachecontrol lockfile platformdirs zstandard
)

create_environment() {
    # Create environment
    conda env list | grep $CONDA_ENV | awk '{print $1}' | xargs -r -L1 conda env remove -y -n || echo "No environment to remove"
    mamba create -n $CONDA_ENV ${ALL_PACKAGES[@]} -y -c microsoft
    conda activate $CONDA_ENV

    # Insert custom install
    if [ -n "$DEV_BOKEH" ]; then
        export DEV_BOKEH
        BOKEH_VERSION=$(
            mamba repoquery search bokeh -c bokeh/label/dev --offline --json |
                jq -r '.result.pkgs | map(select(.version | startswith(env.DEV_BOKEH))) | max_by(.timestamp) | .version'
        )
        mamba install bokeh==$BOKEH_VERSION -c bokeh/label/dev -y
    fi

    # Environment variables
    # https://docs.bokeh.org/en/latest/docs/dev_guide/setup.html
    conda env config vars set BOKEH_RESOURCES=server -n $CONDA_ENV
    conda env config vars set BOKEH_BROWSER=none -n $CONDA_ENV
    conda env config vars set BOKEH_MINIFIED=false -n $CONDA_ENV
    conda env config vars set BOKEH_PRETTY=true -n $CONDA_ENV
    conda env config vars set USE_PYGEOS=0 -n $CONDA_ENV
    conda env config vars set HYPOTHESIS_MAX_EXAMPLES=1 -n $CONDA_ENV

    # conda env config vars set PYTHONWARNINGS=default

    if [[ $OS == "windows" ]]; then
        rm "$HOME/miniconda3/envs/$CONDA_ENV/Library/usr/bin/cygpath.exe" || true
    fi
    rm -f ~/.config/dask/dask.yaml
}

install_package() {

    if [ -d "$1" ]; then
        cd $1

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
        git checkout $BRANCH
        if (($DIRTY > 0)); then git stash pop; fi

    else
        git clone git@github.com:holoviz/$1.git
        cd $1
        pre-commit install --allow-missing-config || echo no pre-commit
    fi

    # pre-commit initialize
    pre-commit install-hooks || echo no pre-commit
    cp -a "$(cd -- "$(dirname "$0")" >/dev/null 2>&1 && pwd -P)/pre-push" .git/hooks/pre-push

    # Install the package
    conda uninstall --force --offline --yes $1 || true
    # conda develop .  # adding to environments .pth file
    # pwd >> $(python -c "import site; print(site.getsitepackages()[0])")/holoviz.pth

    # This should be removed when packages uses pyproject.toml
    if [[ -f setup.py ]]; then
        SETUPTOOLS_ENABLE_FEATURES=legacy-editable python -m pip install --no-deps -e .
    else
        SETUPTOOLS_ENABLE_FEATURES= python -m pip install --no-deps -e .
    fi
    if [[ "$1" == "holoviews" ]]; then
        # Don't want the holoviews command
        rm $(which holoviews) || echo "already uninstalled"
    fi
    # rm -rf build/
    cd ..
}

run() {
    set +euo pipefail
    (set -euxo pipefail && $1 $2) >"/tmp/holoviz_$2_$(date +%Y-%m-%d_%H.%M).log" 2>&1
    if (($? > 0)); then
        echo "!!! Failed installing $2 !!!"
    else
        echo "Finished installing $2"
    fi
    echo -ne "\r" # Clean new line
}

SECONDS=0

# Note need to have drive installed
mkdir -p $HOLOVIZ_REP
cd $HOLOVIZ_REP

# Activate conda
source $(conda info | grep -i 'base environment' | awk '{print $4}')/etc/profile.d/conda.sh
conda activate base

# OS and NVIDIA detection
OS=$(python -c 'import platform; print(platform.system())')
NVIDIA=$(conda info | (grep cuda || echo -n) | wc -l)

# Add custom packages
if [ $NVIDIA == "1" ]; then ALL_PACKAGES+=(${NVIDIA_PACKAGES[@]}); fi
if [[ $OS == "Linux" || $OS == "Darwin" ]]; then ALL_PACKAGES+=(${UNIX_PACKAGES[@]}); fi

# Starting up the machine
create_environment

# Install packages
conda activate $CONDA_ENV
for p in ${PACKAGES[@]}; do
    run install_package $p &
done

# Download data
python -m playwright install &>/dev/null &
python -m bokeh sampledata &>/dev/null &

wait

echo -e "\nRun time: $((($SECONDS / 60) % 60)) min and $(($SECONDS % 60)) sec"
