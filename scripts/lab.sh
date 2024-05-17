#!/usr/bin/env bash

set -euo pipefail

if [[ $(jupyter server list 2>&1 | grep -o "localhost:8888" | wc -l) -eq 0 ]]; then
    BOKEH_RESOURCES=inline jupyter lab --port 8888 $HOLOVIZ_DEV  &>/tmp/jupyter_server.log & disown
else
    if [[ $# -gt 0 ]]; then
        options=$(fd ".ipynb" $HOLOVIZ_DEV -L | sed "s|$HOLOVIZ_DEV||")
        file=$(echo "$options" | fzf-tmux -w --select-1 --query "'$(echo "$@" | sed "s| | '|")")
        firefox "http://localhost:8888/lab/workspaces/auto-W/tree/$file"
    else
        firefox "http://localhost:8888/lab/workspaces/auto-W/"
    fi
fi
