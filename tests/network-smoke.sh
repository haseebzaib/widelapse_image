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
# Real NM activation and independent policy routing, on isolated dummy interfaces.
for pair in 'wltest0 10.240.0.2/24 10.240.0.1 100' 'wltest1 10.241.0.2/24 10.241.0.1 200'; do
    read -r iface address gateway metric <<< "$pair"
    nmcli connection add type dummy ifname "$iface" con-name "$iface" ipv4.method manual ipv4.addresses "$address" ipv4.gateway "$gateway" ipv4.dns 1.1.1.1 ipv4.route-metric "$metric" ipv6.method disabled >/dev/null
    nmcli --wait 10 connection up "$iface" >/dev/null
done
# This container has no systemd to prepare the service runtime directory.
chown systemd-resolve:systemd-resolve /run/systemd/resolve
/usr/lib/systemd/systemd-resolved >/tmp/resolved.log 2>&1 &
sleep 1
python3 - <<'PYTEST'
import json, subprocess, runpy
m=runpy.run_path('/usr/local/bin/widelapse-network')
manager=m['Manager']()
rows={kind: {'interface': iface, 'addresses': [address], 'gateway': gateway,
             'ip_ready': True, 'dns': ['1.1.1.1']}
      for kind,iface,address,gateway in [('eth','wltest0','10.240.0.2','10.240.0.1'),
                                         ('cellular','wltest1','10.241.0.2','10.241.0.1')]}
def read(*args):
    return json.loads(subprocess.check_output(['ip','-N','-j','-4',*args]))
before=read('address','show')
for chosen in ['eth','cellular','eth','cellular',None]:
    manager.routes(rows,chosen)
    assert not manager.dns(rows,chosen)
    routes=read('route','show','default')
    owned=[r for r in routes if r.get('metric') == 5]
    assert len(owned) == (1 if chosen else 0), routes
    if chosen:
        assert owned[0]['dev'] == rows[chosen]['interface'], routes
        assert str(owned[0]['protocol']) == '242', routes
    for iface,metric in [('wltest0',100),('wltest1',200)]:
        assert any(r.get('dev') == iface and r.get('metric') == metric for r in routes), routes
    assert read('address','show') == before, 'Policy changed interface addresses'
print('PASS: repeated route/DNS switching preserves addresses and NM defaults')
PYTEST
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
