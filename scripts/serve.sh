#!/usr/bin/env bash

DIR=$HOLOVIZ_DEV/development/
if [ -n "$1" ]; then
    unset PANEL_SERVE_FILE
fi

if [ -z "$PANEL_SERVE_FILE" ]; then
    SORTED_FILES=$(fd --regex '\d{3,5}.+?\.py$' -t f "$DIR" -X stat -c "%Y %N" 2>/dev/null | sort -r | awk '{print $2}' | tr -d "'" | grep -v 'archive' | sed "s?$DIR??" | grep '^dev_')
    if [ -z "$1" ]; then
        FILE=$(echo "$SORTED_FILES" | fzf --preview "bat $DIR{} --color always") || return 1
    else
        FILE=$(echo "$SORTED_FILES" | fzf --preview "bat $DIR{} --color always" --select-1 --query "$1") || return 1
    fi
    export PANEL_SERVE_FILE=$DIR$FILE
fi

PORT_USED=$(lsof -t -i :5006)
if [ -n "$PORT_USED" ]; then
    kill "$PORT_USED"
    echo "$(date +'%Y-%m-%d %H.%M.%S.%3N') Killed running panel serve on port 5006"
fi

panel serve "$PANEL_SERVE_FILE" --autoreload
