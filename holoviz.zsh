CURDIR="$(cd -- "$(dirname "$0")" >/dev/null 2>&1 && pwd -P)"
fpath=($CURDIR $fpath)
holoviz() { source $CURDIR/holoviz.sh $@ }
