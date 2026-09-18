#!/bin/bash
# Run only in a disposable Debian container with rauc, squashfs-tools,
# u-boot-tools, libubootenv-tool, openssl and e2fsprogs installed.
# Arguments: repository scripts directory, RAUC assets directory.
set -euo pipefail
scripts=$(realpath "$1")
assets=$(realpath "$2")
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
cd "$work"
openssl req -x509 -newkey rsa:2048 -nodes -days 1 -subj /CN=RAUC-test/ \
    -keyout key.pem -out cert.pem >/dev/null 2>&1
truncate -s 3G rootfs.ext4
mkfs.ext4 -q -F rootfs.ext4
bash "$scripts/build-rauc-bundle.sh" rootfs.ext4 test cert.pem key.pem update.raucb
rauc --conf="$assets/system.conf" --keyring="$work/cert.pem" info update.raucb >/dev/null
openssl req -x509 -newkey rsa:2048 -nodes -days 1 -subj /CN=wrong-signer/ \
    -keyout wrong.key -out wrong.pem >/dev/null 2>&1
if rauc --keyring=wrong.pem info update.raucb >wrong.log 2>&1; then
    echo 'ERROR: wrong signer accepted' >&2; exit 1
fi
cp update.raucb corrupt.raucb
python3 - <<'PY'
with open('corrupt.raucb','r+b') as f:
    f.seek(1024); b=f.read(1); f.seek(1024); f.write(bytes([b[0]^1]))
PY
if rauc --keyring=cert.pem info corrupt.raucb >corrupt.log 2>&1; then
    echo 'ERROR: corrupted bundle accepted' >&2; exit 1
fi
# Test the real userspace U-Boot tools against a regular file, never a device.
truncate -s 8M disk.raw
printf 'BOOT_ORDER=A B\nBOOT_A_LEFT=3\nBOOT_B_LEFT=3\n' > env.txt
mkenvimage -r -s 0x10000 -o env.bin env.txt
dd if=env.bin of=disk.raw bs=65536 seek=64 conv=notrunc status=none
dd if=env.bin of=disk.raw bs=65536 seek=65 conv=notrunc status=none
printf '%s 0x400000 0x10000\n%s 0x410000 0x10000\n' "$work/disk.raw" "$work/disk.raw" > fw_env.config
fw_setenv -c fw_env.config BOOT_ORDER 'B A'
[[ $(fw_printenv -c fw_env.config -n BOOT_ORDER) == 'B A' ]]
fw_setenv -c fw_env.config BOOT_B_LEFT 2
[[ $(fw_printenv -c fw_env.config -n BOOT_B_LEFT) == 2 ]]
echo 'PASS: signed bundle, system config, wrong-signer rejection, corruption rejection, redundant environment read/write'
