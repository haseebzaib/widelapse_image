#!/usr/bin/env bash
set -euo pipefail
[[ $# == 5 ]] || { echo 'Usage: build-rauc-bundle.sh ROOTFS.ext4 VERSION CERT.pem KEY.pem OUTPUT.raucb' >&2; exit 2; }
rootfs=$(realpath "$1"); version=$2; cert=$(realpath "$3"); key=$(realpath "$4"); output=$(realpath -m "$5")
[[ $version =~ ^[A-Za-z0-9._+-]+$ ]] || { echo 'Invalid version' >&2; exit 2; }
[[ -f $rootfs && ! -e $output && $rootfs == *.ext4 ]] || { echo 'Expected an exported .ext4 image and a new output path' >&2; exit 2; }
[[ $(stat -c %s "$rootfs") == 3221225472 ]] || { echo 'Expected the 3 GiB RAUC rootfs export, not a whole-disk .img' >&2; exit 2; }
command -v rauc >/dev/null
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
cp --reflink=auto --sparse=always "$rootfs" "$work/rootfs.ext4"
cat > "$work/manifest.raucm" <<EOF
[update]
compatible=widelapse-orangepizero3-ab-v1
version=$version

[bundle]
format=plain

[image.rootfs]
filename=rootfs.ext4
EOF
rauc --cert="$cert" --key="$key" bundle "$work" "$output"
rauc --keyring="$cert" info "$output"
