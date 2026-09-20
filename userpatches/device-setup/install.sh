#!/bin/bash
set -euo pipefail
assets=/tmp/overlay/widelapse-device-setup
install -d /usr/local/bin /etc/systemd/system /etc/ssh/sshd_config.d
install -d -m 755 /opt/widelapse
# Remove obsolete image-side files, never persistent data.
rm -f /etc/systemd/system/multi-user.target.wants/widelapse-storage.service /etc/systemd/system/widelapse-storage.service /etc/systemd/system/ssh.service.d/storage.conf /usr/local/sbin/widelapse-storage /usr/local/sbin/widelapse-grow-data
for name in widelapse-grow-data widelapse-init-directories widelapse-init-identity; do
    install -m 755 "$assets/$name" "/usr/local/bin/$name"
    install -m 644 "$assets/$name.service" "/etc/systemd/system/$name.service"
done
install -d /etc/systemd/system/opt-widelapse.mount.d /etc/systemd/system/ssh.service.d
install -m 644 "$assets/data-mount.conf" /etc/systemd/system/opt-widelapse.mount.d/grow.conf
install -m 644 "$assets/identity-dependency.conf" /etc/systemd/system/ssh.service.d/identity.conf
install -m 644 "$assets/00-widelapse-hostkey.conf" /etc/ssh/sshd_config.d/00-widelapse-hostkey.conf
# Only data may grow; OS slots stay fixed.
systemctl mask armbian-resize-filesystem.service
systemctl enable widelapse-init-directories.service widelapse-init-identity.service
