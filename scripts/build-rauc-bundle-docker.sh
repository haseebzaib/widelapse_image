#!/usr/bin/env bash
set -euo pipefail
[[ $# == 2 ]] || { echo 'Usage: bash scripts/build-rauc-bundle-docker.sh ROOTFS.ext4 VERSION' >&2; exit 2; }
project_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
rootfs=$(realpath "$1")
version=$2
[[ $version =~ ^[A-Za-z0-9._+-]+$ ]] || { echo 'Invalid version' >&2; exit 2; }
[[ -f $rootfs && $rootfs == *.ext4 ]] || { echo 'Supply the exported .rootfs.ext4 file' >&2; exit 2; }
cert="$project_dir/userpatches/overlay/rauc-keyring.pem"
key="$project_dir/secrets/rauc-dev.key.pem"
test -s "$cert"
test -s "$key"
mkdir -p "$project_dir/ota"
name="widelapse-$version.raucb"
[[ ! -e "$project_dir/ota/$name" ]] || { echo "Bundle already exists: ota/$name" >&2; exit 2; }
docker build -t widelapse-rauc-bundler:local -f "$project_dir/scripts/rauc-bundler.Dockerfile" "$project_dir/scripts"
docker run --rm --network none \
    --mount "type=bind,source=$rootfs,target=/input/rootfs.ext4,readonly" \
    --mount "type=bind,source=$cert,target=/input/cert.pem,readonly" \
    --mount "type=bind,source=$key,target=/input/key.pem,readonly" \
    --mount "type=bind,source=$project_dir/scripts,target=/scripts,readonly" \
    --mount "type=bind,source=$project_dir/ota,target=/out" \
    widelapse-rauc-bundler:local -c '
        set -euo pipefail
        # Verify plain bundles on the container filesystem before exporting.
        bash /scripts/build-rauc-bundle.sh /input/rootfs.ext4 "$1" \
            /input/cert.pem /input/key.pem "/tmp/$2"
        cp "/tmp/$2" "/out/$2"
        chown "$3:$4" "/out/$2"
    ' bundle "$version" "$name" "$(id -u)" "$(id -g)"
(cd "$project_dir/ota" && sha256sum "$name" > "$name.sha256")
printf 'Created and verified: %s\n' "$project_dir/ota/$name"
