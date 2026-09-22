#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$project_dir"

if [[ ! -f build/compile.sh ]]; then
    echo "Armbian checkout missing. Follow the setup steps in README.md." >&2
    exit 1
fi

# Validate provisioning inputs before invoking the privileged build framework.
bash scripts/check-rauc-inputs.sh
mkdir -p build/userpatches
cp -a userpatches/. build/userpatches/
# Keep integration assets separate from public-key/password overlay inputs.
for component in device-setup rauc network; do
    # Refresh generated assets without touching provisioning inputs.
    rm -rf "build/userpatches/overlay/widelapse-$component"
    mkdir -p "build/userpatches/overlay/widelapse-$component"
    cp -a "userpatches/$component/." "build/userpatches/overlay/widelapse-$component/"
done
cd build
exec ./compile.sh build widelapse "$@"
