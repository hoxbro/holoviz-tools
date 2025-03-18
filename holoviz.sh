#!/usr/bin/env bash

TOOLS="$(cd -- "$(dirname "$0")" &>/dev/null && pwd -P)/scripts"
cli-py() { "$TOOLS/cli.py" "$@"; }

ccd() {
    if [[ $PWD != $HOLOVIZ_DEV* && $PWD != $HOLOVIZ_REP* ]]; then
        cd "$HOLOVIZ_DEV" || exit 1
    fi
    if [[ $CONDA_DEFAULT_ENV != "holoviz" ]]; then
        # For activating conda environment
        CONDA_INFO=$(cat /tmp/conda_info.json 2>/dev/null || conda info --json | tee /tmp/conda_info.json)
        CONDA_HOME=$(echo "$CONDA_INFO" | jq -r .conda_prefix)
        source "$CONDA_HOME/etc/profile.d/conda.sh"
        conda activate holoviz
    fi
}

if [[ $1 == "lab" ]]; then
    ccd
    shift
    bash "$TOOLS"/lab.sh "$@"
elif [[ $1 == "save" ]]; then
    RESULT=$(cli-py save.py)
    PANEL_SERVE_FILE=$(echo "$RESULT" | grep -E '^/home/')
    export PANEL_SERVE_FILE
elif [[ $1 == "setup" ]]; then
    bash "$TOOLS/setup.sh"
elif [[ $1 == "clean" ]]; then
    ccd
    cli-py cleanup.py
elif [[ $1 == "action-status" ]]; then
    cli-py action_status.py
elif [[ $1 == "version-finder" ]]; then
    cli-py version_finder.py
elif [[ $1 == "artifact-test" ]]; then
    shift
    cli-py pixi/artifact.py "$@"
elif [[ $1 == "artifact-build" ]]; then
    shift
    cli-py build.py "$@"
elif [[ $1 == "changelog" ]]; then
    shift
    cli-py changelog.py "$@"
elif [[ $1 == "deprecate" ]]; then
    shift
    cli-py deprecate.py "$@"
elif [[ $1 == "serve" ]]; then
    shift
    source "$TOOLS/serve.sh" "$@"
elif [[ $1 == "pixi-lock" ]]; then
    shift
    cli-py pixi/lock.py "$@"
elif [[ $1 == "workspace" ]]; then
    shift
    bash "$TOOLS/workspace/$1.sh" "$@"
elif [[ $1 == "bump" ]]; then
    cli-py bump.py "$@"
elif [[ $1 == "python-3.13" ]]; then
    cli-py python-313.py
elif [[ $1 == "bokeh" ]]; then
    shift
    if [[ $1 == "chrome" ]]; then
        cli-py "$TOOLS/bokeh/$1.py" "$@"
    elif [[ $1 == "setup" ]]; then
        bash "$TOOLS/bokeh/$1.sh" "$@"
    else
        printf "\033[0;31m'holoviz bokeh %s' is an invalid command\033[0m\n" "$1"
        return 1
    fi
elif [[ $1 ]]; then
    printf "\033[0;31m'holoviz %s' is an invalid command\033[0m\n" "$1"
    return 1
else
    ccd
fi
