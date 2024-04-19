#!/usr/bin/env bash

TOOLS=${ZSH_CUSTOM:-~/.oh-my-zsh/custom}/plugins/holoviz/scripts

ccd() {
    if [[ $PWD != $HOLOVIZ_DEV* && $PWD != $HOLOVIZ_REP* ]]; then
        cd $HOLOVIZ_DEV
    fi
    if [[ $CONDA_DEFAULT_ENV != "holoviz" ]]; then
        # For activating conda environment
        CONDA_PATH=$(conda info | grep -i 'base environment' | awk '{print $4}')
        source $CONDA_PATH/etc/profile.d/conda.sh
        conda activate holoviz
    fi
}

if [[ -z $1 || $1 == "nvim" || $1 == "vim" ]]; then
    ccd
    nvim $HOLOVIZ_DEV
elif [[ $1 == "lab" ]]; then
    ccd
    shift
    bash $TOOLS/lab.sh $@
elif [[ $1 == "save" ]]; then
    RESULT=$(PYTHONPATH=$TOOLS python $TOOLS/save.py)
    echo $(echo $RESULT | grep -v '^/home/')
    export PANEL_SERVE_FILE=$(echo $RESULT | grep -E '^/home/')
elif [[ $1 == "fetch" ]]; then
    bash $TOOLS/fetch.sh
elif [[ $1 == "setup" ]]; then
    bash $TOOLS/setup.sh "CLEAN"
elif [[ $1 == "sync" ]]; then
    bash $TOOLS/setup.sh "SYNC"
elif [[ $1 == "clean" ]]; then
    ccd
    PYTHONPATH=$TOOLS python $TOOLS/cleanup.py
elif [[ $1 == "action-status" ]]; then
    PYTHONPATH=$TOOLS python $TOOLS/action_status.py
elif [[ $1 == "version-finder" ]]; then
    PYTHONPATH=$TOOLS python $TOOLS/version_finder.py
elif [[ $1 == "artifact-test" ]]; then
    shift
    PYTHONPATH=$TOOLS python $TOOLS/pixi/artifact.py $@
elif [[ $1 == "artifact-build" ]]; then
    shift
    PYTHONPATH=$TOOLS python $TOOLS/build.py $@
elif [[ $1 == "changelog" ]]; then
    shift
    PYTHONPATH=$TOOLS python $TOOLS/changelog.py $@
elif [[ $1 == "deprecate" ]]; then
    shift
    PYTHONPATH=$TOOLS python $TOOLS/deprecate.py $@
elif [[ $1 == "serve" ]]; then
    shift
    source $TOOLS/serve.sh $@
elif [[ $1 == "pixi-lock" ]]; then
    shift
    PYTHONPATH=$TOOLS python $TOOLS/pixi/lock.py $@
elif [[ $1 ]]; then
    (exit 1)
else
    ccd
fi
