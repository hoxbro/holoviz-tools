#!/bin/bash

fetch_main() {
    git --git-dir=$PACKAGE/.git --work-tree=$PACKAGE fetch origin main &>/dev/null
    COUNT=$(git --git-dir="$PACKAGE/.git" --work-tree="$PACKAGE" rev-list --count main..origin/main)
    if (($COUNT > 0)); then
        echo "Fetched origin main of $(basename $PACKAGE), which is $COUNT commit behind."
    fi
}

for PACKAGE in $(ls -d $HOLOVIZ_REP/*/); do
    fetch_main &
done

wait
