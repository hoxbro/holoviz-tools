_HOLOVIZ_TOOLS_DIR="$(cd -- "$(dirname "$0")" >/dev/null 2>&1 && pwd -P)"
fpath=($_HOLOVIZ_TOOLS_DIR $fpath)
holoviz() { source $_HOLOVIZ_TOOLS_DIR/holoviz.sh $@ }
