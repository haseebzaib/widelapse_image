#!/bin/bash
set -euo pipefail
# Executed inside the image by customize-image.sh, with assets staged in overlay.
assets=/tmp/overlay/widelapse-rauc
install -d /etc/rauc /etc/widelapse /usr/local/sbin
install -m 644 "$assets/system.conf" /etc/rauc/system.conf
install -m 644 "$assets/fw_env.config" /etc/fw_env.config
install -m 644 /tmp/overlay/rauc-keyring.pem /etc/rauc/keyring.pem
for name in widelapse-grow-data widelapse-storage widelapse-rauc-confirm widelapse-update; do
    install -m 755 "$assets/$name" "/usr/local/sbin/$name"
done
for name in widelapse-grow-data.service widelapse-storage.service widelapse-rauc-confirm.service widelapse-rauc-confirm.timer; do
    install -m 644 "$assets/$name" "/etc/systemd/system/$name"
done
install -d /etc/systemd/system/opt-widelapse.mount.d \
    /etc/systemd/system/rauc.service.d /etc/systemd/system/ssh.service.d
install -m 644 "$assets/data-mount.conf" /etc/systemd/system/opt-widelapse.mount.d/grow.conf
for unit in ssh rauc; do
    install -m 644 "$assets/storage-dependency.conf" "/etc/systemd/system/$unit.service.d/storage.conf"
done
install -m 644 "$assets/00-widelapse-hostkey.conf" /etc/ssh/sshd_config.d/00-widelapse-hostkey.conf
# This is a different resize policy: rootfs slot boundaries must NEVER grow.
systemctl mask armbian-resize-filesystem.service
systemctl enable widelapse-storage.service widelapse-rauc-confirm.timer
# RAUC is D-Bus activated; ssh/rauc require the persistent storage service.
install -d /etc/systemd/system.conf.d
printf '[Manager]\nRuntimeWatchdogSec=30s\nRebootWatchdogSec=2min\n' > /etc/systemd/system.conf.d/widelapse-watchdog.conf
