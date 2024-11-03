#!/usr/bin/env bash

TOOLS="$(cd -- "$(dirname "$0")" >/dev/null 2>&1 && pwd -P)/scripts"

ccd() {
    if [[ $PWD != $HOLOVIZ_DEV* && $PWD != $HOLOVIZ_REP* ]]; then
        cd "$HOLOVIZ_DEV" || exit
    fi
    if [[ $CONDA_DEFAULT_ENV != "holoviz" ]]; then
        # For activating conda environment
        CONDA_DIR=$(conda info --json | jq -r .conda_prefix)
        source "$CONDA_DIR"/etc/profile.d/conda.sh
        conda activate holoviz
    fi
}

if [[ $1 == "lab" ]]; then
    ccd
    shift
    bash "$TOOLS"/lab.sh "$@"
elif [[ $1 == "save" ]]; then
    RESULT=$("$TOOLS"/cli.py save.py)
    PANEL_SERVE_FILE=$(echo "$RESULT" | grep -E '^/home/')
    export PANEL_SERVE_FILE
elif [[ $1 == "setup" ]]; then
    bash "$TOOLS"/setup.sh
elif [[ $1 == "clean" ]]; then
    ccd
    "$TOOLS"/cli.py cleanup.py
elif [[ $1 == "action-status" ]]; then
    "$TOOLS"/cli.py action_status.py
elif [[ $1 == "version-finder" ]]; then
    "$TOOLS"/cli.py version_finder.py
elif [[ $1 == "artifact-test" ]]; then
    shift
    "$TOOLS"/cli.py pixi/artifact.py "$@"
elif [[ $1 == "artifact-build" ]]; then
    shift
    "$TOOLS"/cli.py build.py "$@"
elif [[ $1 == "changelog" ]]; then
    shift
    "$TOOLS"/cli.py changelog.py "$@"
elif [[ $1 == "deprecate" ]]; then
    shift
    "$TOOLS"/cli.py deprecate.py "$@"
elif [[ $1 == "serve" ]]; then
    shift
    source "$TOOLS"/serve.sh "$@"
elif [[ $1 == "pixi-lock" ]]; then
    shift
    "$TOOLS"/cli.py pixi/lock.py "$@"
elif [[ $1 == "workspace" ]]; then
    shift
    bash "$TOOLS"/workspace/"$1".sh "$@"
elif [[ $1 == "bump" ]]; then
    "$TOOLS"/cli.py bump.py "$@"
elif [[ $1 == "python-3.13" ]]; then
    "$TOOLS"/cli.py python-313.py
elif [[ $1 ]]; then
    (exit 1)
else
    ccd
fi
