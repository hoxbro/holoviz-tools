#compdef holoviz
local -a subcmds
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
)
_describe 'command' subcmds
