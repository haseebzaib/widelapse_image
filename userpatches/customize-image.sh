#!/bin/bash
set -euo pipefail

# Set the local console login banner.
printf 'Widelapse Gateway \\l\n\n' > /etc/issue

# Stop the build if required provisioning inputs are missing.
test -s /tmp/overlay/authorized_keys
test -s /tmp/overlay/root-password.hash
test -s /tmp/overlay/00-widelapse-ssh.conf

# Install the public key with SSH-compatible permissions.
ssh-keygen -l -f /tmp/overlay/authorized_keys >/dev/null

install -d -m 700 -o root -g root /root/.ssh
install -m 600 -o root -g root \
    /tmp/overlay/authorized_keys /root/.ssh/authorized_keys

# Install SSH authentication policy.
install -d -m 755 /etc/ssh/sshd_config.d
install -m 644 -o root -g root \
    /tmp/overlay/00-widelapse-ssh.conf \
    /etc/ssh/sshd_config.d/00-widelapse-ssh.conf

# Set root's local password from the supplied hash.
# Do not enable shell tracing here: it could expose the hash.
set +x
root_hash="$(cat /tmp/overlay/root-password.hash)"
[[ "$root_hash" == '$6$'* ]]
printf 'root:%s\n' "$root_hash" | chpasswd -e
unset root_hash

# Credentials are already provisioned; skip the first-login wizard.
rm -f /root/.not_logged_in_yet

# Remove Armbian's standard console autologin overrides.
rm -f /etc/systemd/system/getty@.service.d/override.conf
rm -f /etc/systemd/system/serial-getty@.service.d/override.conf

# Enable SSH for the image's next boot.
systemctl enable ssh

# Check SSH configuration syntax inside the image.
mkdir -p /run/sshd
chown root:root /run/sshd
chmod 0755 /run/sshd
/usr/sbin/sshd -t


bash /tmp/overlay/widelapse-device-setup/install.sh
bash /tmp/overlay/widelapse-rauc/install.sh
