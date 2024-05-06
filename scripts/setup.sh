#!/usr/bin/env bash

set -euo pipefail

CONDA_ENV="holoviz"
PACKAGES=(panel holoviews hvplot param datashader geoviews lumen holonote)
ALL_PACKAGES=(
    python=3.12

    # Visualization
    bokeh plotly matplotlib seaborn altair

    # Data processing
    numpy pandas xarray polars numba
    dask-core scipy scikit-image tsdownsample

    # Data loading
    lxml openpyxl fastparquet pooch pyarrow
    "intake<2" intake-sql intake-parquet intake-xarray
    s3fs h5netcdf zarr hdf5
    ibis-sqlite sqlalchemy python-duckdb

    # Notebook
    jupyterlab ipywidgets jupyterlab_code_formatter jupyterlab-myst
    bokeh::ipywidgets_bokeh jupyter_bokeh

    # Testing
    pytest pytest-xdist pytest-rerunfailures pytest-benchmark parameterized pytest-asyncio
    nbsmoke nbval microsoft::pytest-playwright

    # Geo
    geopandas rioxarray rasterio spatialpandas
    cartopy pyogrio iris esmpy xesmf geodatasets metpy

    # Dev Tools
    nodejs python-build debugpy
    black ruff
    pyinstrument snakeviz psutil py-spy tuna asv
    pyviz::nbsite

    # Misc
    diskcache streamz aiohttp rich-click setuptools_scm watchfiles
    pyviz_comms tqdm pyct httpx colorcet
    markdown markdown-it-py mdit-py-plugins linkify-it-py
    cachecontrol lockfile platformdirs
)

NVIDIA_PACKAGES=(cupy)
UNIX_PACKAGES=(memray)

create_environments() {
    if [ "$1" == "CLEAN" ]; then
        # Clean up old environment
        conda env list | grep $CONDA_ENV | awk '{print $1}' | xargs -r -L1 conda env remove -y -n || echo "No environment to remove"

        # Creating environment (can't clone because they are linked)
        mamba create -n $CONDA_ENV ${ALL_PACKAGES[@]} -y
        # mamba create -n $CONDA_ENV"_clean" $PYTHON ${PACKAGES[@]} ${ALL_PACKAGES[@]} -y

    elif [ "$1" == "SYNC" ]; then
        echo -n ""
    else
        echo "Options for holoviz setup are clean and sync."
        exit 1
    fi

    wait

    conda activate $CONDA_ENV

    if [ "$1" == "CLEAN" ]; then
        # Insert custom install

        # Environment variables
        # https://docs.bokeh.org/en/latest/docs/dev_guide/setup.html
        conda env config vars set BOKEH_RESOURCES=server -n $CONDA_ENV
        conda env config vars set BOKEH_BROWSER=none -n $CONDA_ENV
        conda env config vars set BOKEH_MINIFIED=false -n $CONDA_ENV
        conda env config vars set BOKEH_PRETTY=true -n $CONDA_ENV
        conda env config vars set USE_PYGEOS=0 -n $CONDA_ENV

        # conda env config vars set PYTHONWARNINGS=default

        if [[ $OS == "windows" ]]; then
            rm "$HOME/miniconda3/envs/$CONDA_ENV/Library/usr/bin/cygpath.exe"
        fi
    fi
}

install_package() {

    if [ -d "$p" ]; then
        cd $p

        # Save current branch and stash files
        BRANCH=$(git branch --show-current)
        DIRTY=$(git status -s -uno | wc -l)
        git stash -m "setup script $(date +%Y-%m-%d_%H.%M)"
        git checkout main

        # Update main
        git fetch origin
        git pull origin --tags
        git reset --hard origin/main

        # Clean up
        if [ "$1" == "CLEAN" ]; then git clean -fxd; fi || echo "No clean"
        git fetch --all --prune

        # Go back branch and unstash files
        git checkout $BRANCH
        if (($DIRTY > 0)); then git stash pop; fi

    else
        git clone git@github.com:holoviz/$p.git
        cd $p
        pre-commit install --allow-missing-config
    fi

    # pre-commit initialize
    pre-commit
    cp -a ~/projects/holoviz-tools/scripts/pre-push .git/hooks/pre-push

    # Install the package
    conda uninstall --force --offline --yes $p || echo "already uninstalled"
    # conda develop .  # adding to environments .pth file
    # pwd >> $(python -c "import site; print(site.getsitepackages()[0])")/holoviz.pth

    # This should be removed when packages uses pyproject.toml
    if [[ -f setup.py ]]; then
        SETUPTOOLS_ENABLE_FEATURES=legacy-editable python -m pip install --no-deps -e .
    else
        SETUPTOOLS_ENABLE_FEATURES= python -m pip install --no-deps -e .
    fi
    if [[ "$p" == "holoviews" ]]; then
        # Don't want the holoviews command
        rm $(which holoviews) || echo "already uninstalled"
    fi
    # rm -rf build/
    cd ..
}

run() {
    set +euo pipefail
    (set -euxo pipefail && $1 $2) >"/tmp/holoviz_$p_$(date +%Y-%m-%d_%H.%M).log" 2>&1
    if (($? > 0)); then
        echo "!!! Failed installing $p !!!"
    else
        echo "Finished installing $p"
    fi
    echo -ne "\r" # Clean new line
}

SECONDS=0

# Note need to have drive installed
mkdir -p $HOLOVIZ_REP
cd $HOLOVIZ_REP

# OS and NVIDIA detection
case "$(uname -s)" in
Darwin) OS="mac" ;;
Linux) OS="linux" ;;
CYGWIN* | MINGW32* | MSYS* | MINGW*) OS="windows" ;;
*) OS="other" ;;
esac

if which nvidia-smi &>/dev/null; then NVIDIA=true; else NVIDIA=false; fi

# Add custom packages
if $NVIDIA; then ALL_PACKAGES+=(${NVIDIA_PACKAGES[@]}); fi
if [[ $OS == "linux" || $OS == "mac" ]]; then ALL_PACKAGES+=(${UNIX_PACKAGES}); fi

source $(conda info | grep -i 'base environment' | awk '{print $4}')/etc/profile.d/conda.sh
conda activate base

# Starting up the machine
create_environments $1

# Install packages
conda activate $CONDA_ENV
for p in ${PACKAGES[@]}; do
    run install_package $1 &
done

# Download data
python -m playwright install &>/dev/null &
python -m bokeh sampledata &>/dev/null &

wait

echo -e "\nRun time: $((($SECONDS / 60) % 60)) min and $(($SECONDS % 60)) sec"
