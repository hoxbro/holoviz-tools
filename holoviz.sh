#!/usr/bin/env bash

TOOLS="$(cd -- "$(dirname "$0")" &>/dev/null && pwd -P)/scripts"
cli_py="$TOOLS/cli.py"

ccd() {
    if [[ $PWD != $HOLOVIZ_DEV* && $PWD != $HOLOVIZ_REP* ]]; then
        cd "$HOLOVIZ_DEV" || exit 1
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
    RESULT=$($cli_py save.py)
    PANEL_SERVE_FILE=$(echo "$RESULT" | grep -E '^/home/')
    export PANEL_SERVE_FILE
elif [[ $1 == "setup" ]]; then
    bash "$TOOLS"/setup.sh
elif [[ $1 == "clean" ]]; then
    ccd
    $cli_py cleanup.py
elif [[ $1 == "action-status" ]]; then
    $cli_py action_status.py
elif [[ $1 == "version-finder" ]]; then
    $cli_py version_finder.py
elif [[ $1 == "artifact-test" ]]; then
    shift
    $cli_py pixi/artifact.py "$@"
elif [[ $1 == "artifact-build" ]]; then
    shift
    $cli_py build.py "$@"
elif [[ $1 == "changelog" ]]; then
    shift
    $cli_py changelog.py "$@"
elif [[ $1 == "deprecate" ]]; then
    shift
    $cli_py deprecate.py "$@"
elif [[ $1 == "serve" ]]; then
    shift
    source "$TOOLS"/serve.sh "$@"
elif [[ $1 == "pixi-lock" ]]; then
    shift
    $cli_py pixi/lock.py "$@"
elif [[ $1 == "workspace" ]]; then
    shift
    bash "$TOOLS"/workspace/"$1".sh "$@"
elif [[ $1 == "bump" ]]; then
    $cli_py bump.py "$@"
elif [[ $1 == "python-3.13" ]]; then
    $cli_py python-313.py
elif [[ $1 ]]; then
    printf "\033[0;31mholoviz %s is an invalid command\033[0m\n" "$1"
    (exit 1)
else
    ccd
fi
