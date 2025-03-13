#!/usr/bin/env bash

set -euo pipefail

cd ~/projects/bokeh/

echo "Creating environment: bkdev"

source "$CONDA_HOME/etc/profile.d/conda.sh"
conda activate base

conda env remove -n bkdev -y >/dev/null || true
mamba env create -n bkdev -f conda/environment-test-3.11.yml -y
conda uninstall --force --offline -y pre-commit || true
conda env config vars set BOKEH_RESOURCES=server-dev -n bkdev
conda env config vars set BOKEH_CHROME=~/.local/bin/chrome-dev -n bkdev
conda activate bkdev

(cd bokehjs && npm ci)
(cd bokehjs && node make dev)

pip install -ve .
