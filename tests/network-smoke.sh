#!/bin/bash
# Only run inside a disposable container with NET_ADMIN; never on a board/host.
# Usage: network-smoke.sh /path/to/userpatches/network
set -euo pipefail
test -f /.dockerenv
assets=$(realpath "$1")
export DEBIAN_FRONTEND=noninteractive
if ! command -v nmcli >/dev/null; then
apt-get update -qq
apt-get install -y -qq --no-install-recommends network-manager modemmanager python3-gi gir1.2-nm-1.0 dbus iproute2 libqmi-utils mobile-broadband-provider-info wpasupplicant iw rfkill systemd-resolved systemd-timesyncd ca-certificates >/tmp/network-packages.log 2>&1
fi
mkdir -p /tmp/overlay/widelapse-network
cp -a "$assets/." /tmp/overlay/widelapse-network/
bash /tmp/overlay/widelapse-network/install.sh
python3 - <<'PY'
import runpy
m=runpy.run_path('/usr/local/bin/widelapse-network')
c=m['validate']({'wifi': {'networks': [{'ssid': 'smoke; test', 'password': 'example123'}]}})
assert len(m['profiles'](c)) == 3
PY
mkdir -p /run/dbus
dbus-daemon --system --fork
NetworkManager --no-daemon >/tmp/nm.log 2>&1 &
for _ in $(seq 1 40); do
    if nmcli general status >/dev/null 2>&1; then break; fi
    sleep 0.25
done
# Real NM activation and route reapply, on isolated dummy interfaces.
for pair in 'wltest0 10.240.0.2/24 10.240.0.1 100' 'wltest1 10.241.0.2/24 10.241.0.1 200'; do
    read -r iface address gateway metric <<< "$pair"
    nmcli connection add type dummy ifname "$iface" con-name "$iface" ipv4.method manual ipv4.addresses "$address" ipv4.gateway "$gateway" ipv4.dns 1.1.1.1 ipv4.route-metric "$metric" ipv6.method disabled >/dev/null
    nmcli --wait 10 connection up "$iface" >/dev/null
done
nmcli device modify wltest0 ipv4.route-metric 30000 ipv4.dns-priority 100 >/dev/null
nmcli device modify wltest1 ipv4.route-metric 50 ipv4.dns-priority -50 >/dev/null
python3 - <<'PY'
import json,subprocess
routes=json.loads(subprocess.check_output(['ip','-j','-4','route','show','default']))
assert any(r.get('dev') == 'wltest0' and r.get('metric') == 30000 for r in routes), routes
assert any(r.get('dev') == 'wltest1' and r.get('metric') == 50 for r in routes), routes
import gi
gi.require_version('NM','1.0')
from gi.repository import NM
c=NM.Client.new(None)
d=c.get_device_by_iface('wltest1')
assert d.get_ip_iface() == 'wltest1'
assert d.get_state() == NM.DeviceState.ACTIVATED
PY
# Bring policy profiles up and exercise daemon/client over its real Unix socket.
mkdir -p /opt/widelapse/configs
printf '{"eth":{"interface":"wltest0"},"wifi":{"enabled":false},"cellular":{"enabled":false}}\n' > /opt/widelapse/configs/network.json
chmod 600 /opt/widelapse/configs/network.json
nmcli connection delete wltest0 wltest1 >/dev/null
/usr/local/bin/widelapse-network --daemon >/tmp/policy.log 2>&1 &
pid=$!
trap 'kill "$pid" 2>/dev/null || true' EXIT
for _ in $(seq 1 40); do
    if test -S /run/widelapse-network/control.sock; then break; fi
    if ! kill -0 "$pid" 2>/dev/null; then cat /tmp/policy.log; exit 1; fi
    sleep 0.25
done
/usr/local/bin/widelapse-network --status > /tmp/status.json
/usr/local/bin/widelapse-network --reload > /tmp/reload.json
python3 - <<'PY'
import json
assert json.load(open('/tmp/status.json'))['ready']
assert json.load(open('/tmp/reload.json'))['ok']
PY
printf 'PASS: Trixie installer, real NetworkManager profiles/routes, daemon and JSON reload API\n'
