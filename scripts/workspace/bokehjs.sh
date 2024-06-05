#!/usr/bin/bash
set -euo pipefail

cd bokehjs  # Assumes we are in Bokeh root directory

name="server"
cmd="node test/devtools server"
tmux kill-window -t "$name" &>/dev/null || true
tmux new-window -n "$name" -d
tmux send-keys -t "$name" "$cmd" Enter

name="build-src"
cmd="watchfiles \"node make dev\" src"
tmux kill-window -t "$name" &>/dev/null || true
tmux new-window -n "$name" -d
tmux send-keys -t "$name" "$cmd" Enter

name="build-test"
cmd="watchfiles 'node make test:build' test/"
tmux kill-window -t "$name" &>/dev/null || true
tmux new-window -n "$name" -d
tmux send-keys -t "$name" "$cmd" Enter
