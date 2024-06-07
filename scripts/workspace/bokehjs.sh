#!/usr/bin/bash
set -euo pipefail

cd bokehjs  # Assumes we are in Bokeh root directory

name="server"
cmd="node test/devtools server"
tmux kill-window -t "$name" &>/dev/null || true
tmux new-window -n "$name" -d
tmux send-keys -t "$name" "$cmd" Enter

name="build-src"
watch_cmd="node make dev"
dir="src"
cmd="watchfiles \"sh -c 'tmux rename-window -t $name •$name; $watch_cmd; tmux rename-window -t •$name $name'\" $dir"
tmux kill-window -t "$name" &>/dev/null || true
tmux new-window -n "$name" -d
tmux send-keys -t "$name" "$cmd" Enter

name="build-test"
watch_cmd="node make test:build"
dir="test"
cmd="watchfiles \"sh -c 'tmux rename-window -t $name •$name; $watch_cmd; tmux rename-window -t •$name $name'\" $dir"
tmux kill-window -t "$name" &>/dev/null || true
tmux new-window -n "$name" -d
tmux send-keys -t "$name" "$cmd" Enter
