#!/bin/bash
set -euo pipefail
# Executed inside the image by customize-image.sh, with assets staged in overlay.
assets=/tmp/overlay/widelapse-rauc
install -d /etc/rauc /etc/widelapse /usr/local/bin
install -m 644 "$assets/system.conf" /etc/rauc/system.conf
install -m 644 "$assets/fw_env.config" /etc/fw_env.config
install -m 644 /tmp/overlay/rauc-keyring.pem /etc/rauc/keyring.pem
rm -f /usr/local/sbin/widelapse-update /usr/local/sbin/widelapse-rauc-confirm /etc/systemd/system/rauc.service.d/storage.conf
for name in widelapse-init-ota widelapse-rauc-confirm widelapse-update; do
    install -m 755 "$assets/$name" "/usr/local/bin/$name"
done
for name in widelapse-init-ota.service widelapse-rauc-confirm.service widelapse-rauc-confirm.timer; do
    install -m 644 "$assets/$name" "/etc/systemd/system/$name"
done
install -d /etc/systemd/system/rauc.service.d
install -m 644 "$assets/ota-dependency.conf" /etc/systemd/system/rauc.service.d/ota.conf
systemctl enable widelapse-init-ota.service widelapse-rauc-confirm.timer
# RAUC is D-Bus activated and requires persistent OTA directories.
test -f /usr/lib/systemd/system/rauc.service
test -f /usr/lib/systemd/system/dbus.socket
command -v unsquashfs >/dev/null
systemctl add-wants sockets.target dbus.socket
install -d /etc/systemd/system.conf.d
# sunxi-wdt supports a maximum hardware timeout of 16 seconds.
printf '[Manager]\nRuntimeWatchdogSec=16s\nRebootWatchdogSec=16s\n' > /etc/systemd/system.conf.d/widelapse-watchdog.conf
