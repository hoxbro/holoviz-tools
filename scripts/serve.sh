#!/usr/bin/env bash

DIR=$HOLOVIZ_DEV/development/
if [ -n "$1" ]; then
    unset PANEL_SERVE_FILE
fi

if [ -z "$PANEL_SERVE_FILE" ]; then
    UNSORTED_FILES=$(fd --regex '\d{3,5}.+?\.py$' -t f $DIR --print0)
    SORTED_FILES=$(echo $UNSORTED_FILES | xargs -0 stat -c "%Y %N" 2>/dev/null  | sort -r | awk '{print $2}' | tr -d "'" | grep -v 'archive' | sed "s?$DIR??" | grep -e '^dev_')
    FILE=$(echo $SORTED_FILES | fzf  --preview  "bat $DIR{} --color always")
    export PANEL_SERVE_FILE=$DIR$FILE
fi

PORT_USED=$(lsof -t -i :5006)
if [ -n "$PORT_USED" ]; then
    kill $PORT_USED
    echo "$(date +'%Y-%m-%d %H.%M.%S.%3N') Killed running panel serve on port 5006"
fi

panel serve $PANEL_SERVE_FILE --autoreload
