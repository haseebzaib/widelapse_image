#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$project_dir"

if [[ ! -f build/compile.sh ]]; then
    echo "Armbian checkout missing. Follow the setup steps in README.md." >&2
    exit 1
fi

mkdir -p build/userpatches
cp -a userpatches/. build/userpatches/
cd build
exec ./compile.sh build widelapse "$@"
