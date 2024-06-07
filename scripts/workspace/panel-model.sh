#!/usr/bin/bash
set -euo pipefail

PORT_USED=$(lsof -t -i :5006) || true
if [ -n "$PORT_USED" ]; then
    kill $PORT_USED
    echo "$(date +'%Y-%m-%d %H.%M.%S.%3N') Killed running panel serve on port 5006"
fi

name="serve"
cmd="panel serve example*.py --autoreload"
tmux kill-window -t "$name" &>/dev/null || true
tmux new-window -n "$name" -d
tmux send-keys -t "$name" "$cmd" Enter

name="build"
watch_cmd="panel build panel"
dir="panel/models"
cmd="watchfiles \"sh -c 'tmux rename-window -t $name •$name; $watch_cmd; tmux rename-window -t •$name $name'\" $dir"
tmux kill-window -t "$name" &>/dev/null || true
tmux new-window -n "$name" -d
tmux send-keys -t "$name" "$cmd" Enter
