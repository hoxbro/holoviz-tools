# Information

Tools I use for the development of the different Holoviz repos. They are made available here in case they are
useful to others, but no support is provided.

## Installation

### Zsh

1. Clone this repository somewhere on your machine. This guide will assume `~/.holoviz-tools`.

   ```sh
   git clone https://github.com/Hoxbro/holoviz-tools ~/.holoviz-tools
   ```

2. Add the following to the end of your `~/.zshrc`:

   ```sh
   source ~/.holoviz-tools/holoviz-tools.zsh
   ```

3. Optional: Run the following lines after the previous line to enable autocompletion for the `holoviz` command:
   ```sh
   autoload -U compinit
   compinit
   ```

### Oh My Zsh

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

The folder structure I use is:

```sh
> tree -d -L 2 $HOLOVIZ_DEV
$HOLOVIZ_DEV
├── development
│   ├── dev_datashader
│   ├── dev_geoviews
│   ├── dev_holoviews
│   ├── dev_hvplot
│   ├── dev_lumen
│   ├── dev_panel
│   ├── dev_param
│   ├── discourse
└── repos -> $HOLOVIZ_REP
```

`$GITHUB_TOKEN` is the token you get from GitHub to access the API. You can get one from your GitHub account
settings
[here](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens#creating-a-fine-grained-personal-access-token).
