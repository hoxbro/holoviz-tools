#!/usr/bin/env bash

set -euo pipefail

cd ~/projects/bokeh/

echo "Creating environment: bkdev"

source "$CONDA_HOME/etc/profile.d/conda.sh"
conda activate base

conda env remove -n bkdev -y >/dev/null || true
conda env create -n bkdev -f conda/environment-test-3.11.yml -y
conda env config vars set BOKEH_RESOURCES=server -n bkdev
conda env config vars set BOKEH_CHROME=~/.cache/bokeh/chrome -n bkdev
conda activate bkdev

./scripts/ci/install_node_modules.sh

pip install -ve .