# Information

Tools I use for the development of the different Holoviz repos. They are made available here in case they are
useful to others, but no support is provided.

### Installation

1. Clone this repository into `$ZSH_CUSTOM/plugins` (by default `~/.oh-my-zsh/custom/plugins`)

   ```sh
   git clone https://github.com/Hoxbro/holoviz-tools ${ZSH_CUSTOM:-~/.oh-my-zsh/custom}/plugins/holoviz
   ```

2. Add the plugin to the list of plugins for Oh My Zsh to load (inside `~/.zshrc`):

   ```sh
   plugins=(
       # other plugins...
       holoviz
   )
   ```

### Environment variables

`$HOLOVIZ_DEV` is the path to the directory where you have development files. Could be a synchronized folder
like Dropbox or Google Drive.

`$HOLOVIZ_REP` is the path to the directory where you have cloned the different repos.

`$GITHUB_TOKEN` is the token you get from GitHub to access the API. You can get one from your GitHub account
settings
[here](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens#creating-a-fine-grained-personal-access-token).
