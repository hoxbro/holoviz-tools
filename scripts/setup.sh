#!/usr/bin/env bash

CONDA_ENV="holoviz"
PYTHON="python=3.11"
PACKAGES=(panel holoviews hvplot param datashader geoviews lumen colorcet)
ALL_PACKAGES=(
    # Visualization
    bokeh plotly matplotlib seaborn altair

    # Data processing
    numpy pandas xarray polars
    dask-core scikit-image

    # Data loading
    lxml openpyxl fastparquet pooch pyarrow
    intake intake-sql intake-parquet intake-xarray
    s3fs h5netcdf zarr "hdf5!=1.14.1"
    ibis-sqlite "sqlalchemy<2" duckdb

    # Notebook
    "jupyterlab<4" ipywidgets jupyterlab_code_formatter
    "jupyter_bokeh>=3.0.7" "jupyter_client<8" bokeh::ipywidgets_bokeh

    # Testing
    pytest pytest-xdist flaky pytest-benchmark parameterized pytest-asyncio
    nbsmoke nbval microsoft::pytest-playwright

    # Geo
    geopandas rioxarray rasterio spatialpandas
    cartopy pyogrio iris esmpy xesmf geodatasets metpy

    # Dev Tools
    nodejs
    black ruff isort pre-commit
    pyinstrument snakeviz memray psutil py-spy tuna asv
    pyviz::nbsite

    # Misc
    diskcache dash streamz aiohttp
    datashape "pyviz_comms<3" tqdm pyct
    markdown markdown-it-py mdit-py-plugins linkify-it-py
)
GPU_PACKAGES=(
    python=3.10 cupy cudf dask-cudf -c rapidsai --no-channel-priority
)

sync_vscode_settings() {
    SRC=$HOLOVIZ_DEV/.vscode-repos/$p-settings.json

    if [ -f "$SRC" ]; then
        echo "Custom setting file exists for $p"
    else
        echo "Custom setting file does not exists for $p"
        SRC=$HOLOVIZ_DEV/.vscode-repos/settings.json
    fi

    DST=$HOLOVIZ_REP/$p/.vscode/settings.json
    mkdir $(dirname $DST)
    ln -s $SRC $DST
}

create_environments() {
    if [ "$1" == "CLEAN" ]; then
        # Clean up old environment
        conda env list | grep $CONDA_ENV | awk '{print $1}' | xargs -r -L1 conda env remove -n

        # Creating environment (can't clone because they are linked)
        mamba create -n $CONDA_ENV $PYTHON ${ALL_PACKAGES[@]} -y
        mamba create -n $CONDA_ENV"_clean" $PYTHON ${PACKAGES[@]} ${ALL_PACKAGES[@]} -y

        if [[ $OS == "linux" ]] && $NVIDIA; then
            # cudf / dask_cudf pins hard
            mamba create -n $CONDA_ENV"_gpu" ${ALL_PACKAGES[@]} ${GPU_PACKAGES[@]} -y
        fi

    elif [ "$1" == "UPDATE" ]; then
        mamba update --all -n $CONDA_ENV -y
        mamba update --all -n $CONDA_ENV"_clean" -y
        if [[ $OS == "linux" ]] && $NVIDIA; then
            mamba update --all -n $CONDA_ENV"_gpu" -y
        fi

    elif [ "$1" == "SYNC" ]; then
        echo -n ""
    else
        echo "Options for holoviz setup are clean, update, and sync."
        exit 1
    fi

    wait

    conda activate $CONDA_ENV

    if [ "$1" == "CLEAN" ] || [ "$1" == "UPDATE" ]; then
        echo "No custom install"
    fi
    # Environment variables
    if [ "$1" == "CLEAN" ]; then
        # https://docs.bokeh.org/en/latest/docs/dev_guide/setup.html
        conda env config vars set BOKEH_RESOURCES=server -n $CONDA_ENV
        conda env config vars set BOKEH_BROWSER=none -n $CONDA_ENV
        conda env config vars set BOKEH_MINIFIED=false -n $CONDA_ENV
        conda env config vars set BOKEH_PRETTY=true -n $CONDA_ENV
        conda env config vars set SETUPTOOLS_ENABLE_FEATURES=legacy-editable -n $CONDA_ENV
        conda env config vars set USE_PYGEOS=0 -n $CONDA_ENV

        # https://discourse.jupyter.org/t/debugger-warning-it-seems-that-frozen-modules-are-being-used-python-3-11-0
        conda env config vars set  PYDEVD_DISABLE_FILE_VALIDATION=1 -n $CONDA_ENV
        # Crashes pytest https://github.com/microsoft/vscode-python/issues/20259
        # conda env config vars set PYTHONWARNINGS=default

        if [[ $OS == "windows" ]]; then
            rm "$HOME/miniconda3/envs/$CONDA_ENV/Library/usr/bin/cygpath.exe"
        fi
    fi
}

install_package() {
    # This should be removed when packages uses pyproject.toml
    export SETUPTOOLS_ENABLE_FEATURES=legacy-editable

    if [ -d "$p" ]; then
        cd $p

        # Save current branch and stash files
        BRANCH=$(git branch --show-current)
        DIRTY=$(git status -s -uno | wc -l)
        git stash -m "setup script $(date +%Y-%m-%d_%H.%M)"
        git checkout main

        # Update main
        git fetch
        git pull --tags
        git reset --hard origin/main

        # Clean up
        if [ "$1" == "CLEAN" ]; then git clean -fxd; fi
        git fetch --all --prune

        # Go back branch and unstash files
        git checkout $BRANCH
        if (($DIRTY > 0)); then git stash pop; fi

    else
        git clone git@github.com:holoviz/$p.git
        cd $p
        pre-commit install --allow-missing-config
    fi
    # .vscode settings
    sync_vscode_settings

    # pre-commit initialize
    pre-commit

    # Install the package
    conda uninstall --force --offline --yes $p || echo "already uninstalled"
    conda develop .  # adding to environments .pth file
    python -m pip install --no-deps -e .
    if [["$p" == "panel"]]; then
        panel bundle --all &>/dev/null &
    elif [[ "$p" == "holoviews" ]]; then
        # Don't want the holoviews command
        rm $(which holoviews) || echo "already uninstalled"
    fi
    rm -rf build/
    cd ..
}

run() {
    LOGNAME="/tmp/holoviz_$p.log"
    $1 &>$LOGNAME
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

# Setting up OS, Nvidia, folder, and conda
case "$(uname -s)" in # (SO: 3466166)
Darwin) OS="mac" ;;
Linux) OS="linux" ;;
CYGWIN* | MINGW32* | MSYS* | MINGW*) OS="windows" ;;
*) OS="other" ;;
esac

if which nvidia-smi &>/dev/null; then NVIDIA=true; else NVIDIA=false; fi
if $NVIDIA; then ALL_PACKAGES+=(cupy); fi

CONDA_PATH=$(conda info | grep -i 'base environment' | awk '{print $4}')
source $CONDA_PATH/etc/profile.d/conda.sh
conda activate base

# Starting up the machine
create_environments $1

# Install packages
conda activate $CONDA_ENV
for p in ${PACKAGES[@]}; do
    run install_package &
done

if [[ $OS == "linux" ]] && $NVIDIA; then
    wait
    echo "Installing in GPU environment"
    conda activate $CONDA_ENV"_gpu"

    for p in ${PACKAGES[@]}; do
        run install_package &
    done
fi


# Download data
playwright install &>/dev/null &
bokeh sampledata &>/dev/null &

wait

echo -e "\nRun time: $((($SECONDS / 60) % 60)) min and $(($SECONDS % 60)) sec"
