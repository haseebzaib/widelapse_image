#!/bin/bash
set -euo pipefail
assets=/tmp/overlay/widelapse-network
install -d /usr/local/bin /usr/share/widelapse /etc/NetworkManager/conf.d /etc/sysctl.d
install -m 755 "$assets/widelapse-network" /usr/local/bin/widelapse-network
install -m 644 "$assets/widelapse-network.service" /etc/systemd/system/widelapse-network.service
install -m 644 "$assets/network.example.json" /usr/share/widelapse/network.example.json
install -m 644 "$assets/90-widelapse.conf" /etc/NetworkManager/conf.d/90-widelapse.conf
# This image uses NetworkManager directly; Netplan/networkd must not own the links.
# Only image-root configuration is removed, never persistent board configuration.
rm -f /etc/netplan/*.yaml /etc/netplan/*.yml
rm -f /etc/systemd/system/apt-daily-upgrade.service.d/armbian-exec-correct-service.conf
install -d /etc/network
printf 'auto lo\niface lo inet loopback\n' > /etc/network/interfaces
systemctl mask systemd-networkd.service systemd-networkd.socket systemd-networkd-wait-online.service networking.service NetworkManager-wait-online.service
# Loose reverse-path filtering is required for replies on standby uplinks.
printf 'net.ipv4.conf.all.rp_filter=2\nnet.ipv4.conf.default.rp_filter=2\n' > /etc/sysctl.d/90-widelapse-network.conf
ln -sfn /run/systemd/resolve/stub-resolv.conf /etc/resolv.conf
systemctl enable NetworkManager.service ModemManager.service systemd-resolved.service systemd-timesyncd.service widelapse-network.service
for tool in nmcli mmcli qmicli rfkill iw; do
    command -v "$tool" >/dev/null
done
/usr/bin/python3 -c 'import gi; gi.require_version("NM", "1.0"); from gi.repository import NM'
