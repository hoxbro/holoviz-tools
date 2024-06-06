#!/usr/bin/bash
set -euo pipefail

PORT_USED=$(lsof -t -i :5006) || echo 0
if ( $PORT_USED -neq 0 ); then
    kill $PORT_USED
    echo "$(date +'%Y-%m-%d %H.%M.%S.%3N') Killed running panel serve on port 5006"
fi

name="serve"
cmd="panel serve example*.py --autoreload"
tmux kill-window -t "$name" &>/dev/null || true
tmux new-window -n "$name" -d
tmux send-keys -t "$name" "$cmd" Enter

name="build"
cmd="watchfiles \"panel build panel\" panel/models/"
tmux kill-window -t "$name" &>/dev/null || true
tmux new-window -n "$name" -d
tmux send-keys -t "$name" "$cmd" Enter
