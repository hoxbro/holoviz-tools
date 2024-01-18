#!/usr/bin/env bash

DIR=$HOLOVIZ_DEV/development/
if [ -n "$1" ]; then
    unset PANEL_SERVE_FILE
fi

if [ -z "$PANEL_SERVE_FILE" ]; then
    FILE=$(fd --regex '\d{3,5}.+?\.py$' -t f $DIR |  grep -v 'archive' | sed "s?$DIR??" | grep -e '^dev_' | fzf  --preview  "bat $DIR{} --color always" )
    export PANEL_SERVE_FILE=$DIR$FILE
fi

panel serve $PANEL_SERVE_FILE --autoreload
