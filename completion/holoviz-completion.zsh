#compdef holoviz
local -a subcmds state
subcmds=(
  'setup:Setup a Holoviz environment'
  'sync:Sync Git repo in Holoviz environment'
  'update:Update environment and sync repos'
  'code:Open VSCode with Holoviz workspace'
  'lab:Open JupyterLab with Holoviz environment'
  'autocomplete:Install autocomplete for holoviz command'
  'version-finder:Find versions of packages'
  'action-status:Check status of Holoviz Github Actions'
  'fetch:Fetch latest versions of Git repos'
  'changelog:Generate changelog for Holoviz repos'
)

_arguments '1: :->subcmds' && return

case "$state" in
  subcmds)
    _describe 'command' subcmds
    ;;
esac
