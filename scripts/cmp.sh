#!/usr/bin/env bash
set -euo pipefail

# TODO:
# - Allow script files instead of code
# - Allow to specify other dependencies

# ----------------------------------------
# Colors
# ----------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m' # No Color

# ----------------------------------------
# Usage / Args
# ----------------------------------------
if (($# < 4)); then
    echo -e "${RED}Usage:${NC} $0 <package> <good_version> <bad_version> \"<test command>\""
    exit 1
fi

PKG="$1"
GOOD="$2"
BAD="$3"
shift 3
TEST_CMD="$*"

# ----------------------------------------
# Setup
# ----------------------------------------
ts=$(date +%s)
LOG="/tmp/conda_cmp_${PKG}_${ts}.txt"

CONDA_INFO=$(cat /tmp/conda_info.json 2>/dev/null || conda info --json | tee /tmp/conda_info.json)
CONDA_HOME=$(echo "$CONDA_INFO" | jq -r .conda_prefix)
source "$CONDA_HOME/etc/profile.d/conda.sh"

# ----------------------------------------
# Test a specific version
# ----------------------------------------
test_version() {
    local version="$1"
    # shellcheck disable=SC2155
    local ev="$(echo "$version" | tr . _)"
    local env="tmp_${ts}_${ev}"

    {
        echo "  Creating environment: ${env}"
        mamba create -y -n "${env}" "${PKG}=${version}" --offline
        conda activate "${env}"
        python -c "${TEST_CMD}"
        local rc=$?
        conda deactivate
    } >>"$LOG" 2>&1
    return $rc
}

# ----------------------------------------
# Step 1: List versions
# ----------------------------------------
echo -e "${YELLOW}[+] Getting all versions of '${PKG}'${NC}"
# shellcheck disable=SC2207
all_versions=($(mamba search "${PKG}" --json --offline | jq -r ".result.pkgs.[].version" | sort -V | uniq))

g_idx=-1
b_idx=-1
for i in "${!all_versions[@]}"; do
    [[ "${all_versions[i]}" == "$GOOD" ]] && g_idx=$i
    [[ "${all_versions[i]}" == "$BAD" ]] && b_idx=$i
done

if ((g_idx < 0 || b_idx < 0)); then
    echo -e "${RED}Error:${NC} Either $GOOD or $BAD was not found"
    exit 1
fi

# Determine bisection direction
if ((g_idx < b_idx)); then
    versions=("${all_versions[@]:g_idx:b_idx-g_idx+1}")
    direction="forward"
else
    versions=("${all_versions[@]:b_idx:g_idx-b_idx+1}")
    # shellcheck disable=SC2207
    versions=($(printf "%s\n" "${versions[@]}" | tac)) # reverse
    direction="backward"
fi

echo -e "    ${GREEN}Found ${#versions[@]} versions between $GOOD and $BAD (${direction})${NC}"

# ----------------------------------------
# Step 2: Verify good/bad
# ----------------------------------------
echo -e "${YELLOW}[+] Verifying baseline versions${NC}"

if test_version "$GOOD"; then
    echo -e "${GREEN}    $GOOD passed${NC}"
else
    echo -e "${RED}    $GOOD failed. It must pass. Exiting.${NC}"
    exit 1
fi

if test_version "$BAD"; then
    echo -e "${RED}    $BAD passed. It must fail. Exiting.${NC}"
    exit 1
else
    echo -e "${GREEN}    $BAD failed as expected${NC}"
fi

# ----------------------------------------
# Step 3: Bisect
# ----------------------------------------
echo -e "${YELLOW}[+] Starting bisection${NC}"

left=0
right=$((${#versions[@]} - 1))

while ((right - left > 1)); do
    mid=$(((left + right) / 2))
    ver="${versions[mid]}"
    echo -n "    Testing $ver..."

    if test_version "$ver"; then
        echo -e "${GREEN} passed${NC}"
        left=$mid
    else
        echo -e "${RED} failed${NC}"
        right=$mid
    fi
done

problem="${versions[right]}"

# ----------------------------------------
# Step 4: Done
# ----------------------------------------
echo -e "${YELLOW}[+] Done${NC}"
echo -e "    ${GREEN}First failing version is: $problem${NC}"
