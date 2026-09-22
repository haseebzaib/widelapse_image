# Widelapse connectivity

`widelapse-network.service` starts at boot after the persistent mount is verified.
NetworkManager handles Ethernet DHCP, Wi-Fi association and cellular connections;
ModemManager handles the USB modem, SIM and QMI bearer. The Python service handles
internet health, route/DNS priority and the application-facing JSON API.

This supports one Ethernet interface, one Wi-Fi interface, and one USB modem.
The SIM7600 log showing `qmi_wwan` and `cdc-wdm0` already demonstrates a QMI USB
composition. No AT command changes or USB-mode switching are applied. Other modems
must be supported by ModemManager and the image's kernel/firmware; changing modem
models is not a guarantee of compatibility. Do not run qmicli connection commands
or another modem manager concurrently with ModemManager.

## Configuration

The service reads `/opt/widelapse/configs/network.json` at boot and on `--reload`.
It creates `configs/` with mode 700 if absent, but does not create a config file.
Missing config enables all links: Ethernet DHCP, Wi-Fi radio up without an SSID,
and automatic cellular provider settings where the provider database supports
the SIM. Missing APN/PIN/credentials may prevent cellular data; inspect status.
No application data/release folders are created.

Start from the installed example, then edit it on the board:

```bash
install -d -m 700 /opt/widelapse/configs
# Only copy this example if no existing config should be preserved.
install -m 600 /usr/share/widelapse/network.example.json /opt/widelapse/configs/network.json
nano /opt/widelapse/configs/network.json
widelapse-network --validate
widelapse-network --reload
```

An example with credentials (replace placeholders):

```json
{
  "eth": {"enabled": true, "interface": "end0", "ipv4": "dhcp"},
  "wifi": {
    "enabled": true,
    "interface": "wlan0",
    "networks": [{"ssid": "Your Wi-Fi", "password": "Your password"}]
  },
  "cellular": {
    "enabled": true,
    "modem": "auto",
    "apn": "",
    "username": "",
    "password": "",
    "sim_pin": "",
    "allow_roaming": true
  },
  "policy": {
    "priority": ["eth", "wifi", "cellular"],
    "check_interval_seconds": 10,
    "failure_threshold": 3,
    "recovery_threshold": 3
  }
}
```

Omitted options use the defaults in `network.example.json`. Unknown options and
invalid types are rejected. `network.json` must be root-owned and mode 600.
The application should write a complete replacement file with these permissions
and atomically rename it over `network.json`, then call `--reload`.

- Wi-Fi supports open networks (empty password) and WPA personal PSK networks.
  Enterprise authentication and WPA3-only configuration are not implemented.
  Entries earlier in the list have higher autoconnect priority; an already
  connected Wi-Fi network is not forcibly switched to another SSID.
- Empty or omitted APN enables automatic lookup using the installed
  `mobile-broadband-provider-info` database. NetworkManager uses operator
  information supplied by ModemManager to look up provider settings. The database
  is local, so lookup does not require an existing internet connection. It can
  supply APN and authentication defaults. This is a best-effort lookup: missing
  providers, MVNOs and private/enterprise plans may need explicit settings.
- A nonempty `apn` disables automatic provider configuration and uses that APN;
  `username` and `password` are optional explicit carrier credentials. Leave
  `apn` empty to try automatic detection first; set it if the SIM does not connect.
- `allow_roaming: true` is the default, allowing a data connection on either home
  or roaming networks. Set false to restrict cellular to its home network. This
  controls cellular registration/data eligibility, not uplink routing priority.
  An existing config explicitly set to false stays false until edited and reloaded.
- SIM PIN is optional. A PIN unlock failure is recorded in the root-only
  `configs/.failed-sim-pin.json` file; the same modem/PIN combination is not retried
  automatically across reboot. A different PIN may be attempted. PUK unlocking
  is deliberately manual. After checking remaining attempts and the correct PIN,
  an operator can remove that failure file to allow another attempt.
- Credentials stay out of subprocess arguments and status responses. NM profiles
  are mode 600 under `/run/NetworkManager/system-connections/`; JSON is persistent.
  They are not encrypted at rest; fscrypt is not part of this change.

Invalid config during reload leaves the current config/profiles unchanged.
At boot an invalid config falls back to defaults and reports `config_error`.
A backend error while applying a valid config may partially apply changes: inspect
status and the services before retrying. The response does not promise atomic
network changes. Reloading credentials may briefly disconnect the affected link.

## Selection and DNS

All enabled links remain available, including cellular while Ethernet is in use.
Cellular remains connected with its assigned IP when registration/APN setup succeeds;
it is not disconnected merely because Ethernet is selected. Ordinary default-route
internet traffic uses healthy Ethernet, then Wi-Fi, then cellular. Cellular health
probes (and traffic explicitly bound to that interface) still use cellular data;
standby does not mean zero cellular usage.
Health probes establish certificate-verified TLS connections to explicit IPv4
addresses, with the socket bound to the specific network interface. Thus a
standby interface cannot pass its probe using the current preferred interface.
Default targets are Cloudflare (1.1.1.1:443) and Google (8.8.8.8:443). One successful
probe is sufficient. `policy.probe_targets` and `probe_timeout_seconds` can be
changed; every target needs `address`, `port`, and `tls_server_name`.

Three successful rounds qualify a link; three failures disqualify it. Physical
disconnection disqualifies it immediately when detected. Ethernet wins over Wi-Fi,
which wins over cellular, including when a preferred link recovers. Checks run
roughly every 10 seconds plus probe/inspection time; failover is not instantaneous.
A new interface/connection must qualify again. TLS requires a reasonably correct
system clock. Probes test those endpoints, not every website or your application's
server; they don't independently test the uplink's DNS service. Blocked probe
endpoints can report a usable network unhealthy. Configure suitable endpoints for
your deployment. Standby cellular probes consume data.

The selected connection gets metric 50 and exclusive DNS priority via
systemd-resolved. Standby defaults get metrics 30000+. LAN-connected routes stay
available, including Ethernet SSH even if Ethernet has no internet. When none
qualifies, status says `selected: null`; high-metric routes remain for recovery
and bootstrap. This is not a traffic-blocking policy or a bandwidth aggregator.
Existing TCP sessions may disconnect on a switch. Clients must reconnect.

This first version manages **IPv4 only**. Managed profiles disable IPv6 so IPv6
cannot bypass the selected uplink. Static addresses and multiple modems are not
supported. `modem: auto` avoids dependence on modem index or names such as
`wwu1i5`; NetworkManager supplies the associated data interface.

## Application commands

Run as root (the control socket is root-only). Queries return JSON and use the
latest polling snapshot; `updated_at` is a Unix timestamp.

```bash
widelapse-network --status
widelapse-network --network
widelapse-network --rssi wifi
widelapse-network --rssi cellular
widelapse-network --rssi eth
widelapse-network --validate
widelapse-network --reload
# --update is an alias for --reload
```

RSSI uses dBm when the driver/modem provides it. Signal percentage is a separate
field; it is not converted to fabricated dBm. Ethernet and unavailable radio
measurements return null. Cellular status includes operator, SIM lock state,
registration, access technology and signal. ModemManager extended signal polling
is requested at 30-second intervals if supported. PIN/PSK/APN passwords are never
returned. `routing_applied: false` means the requested route change failed and
will be retried; do not treat `selected` alone as proof that routing was applied.

## Build and first board test

Rebuild the image and sign its new rootfs export following `docs/OTA.md`. This
change uses the existing partition layout and can be installed through OTA.
No board commands, image build, or bundle creation are run by this implementation.

The image installer removes image-side Netplan YAML and masks networkd/ifupdown;
NetworkManager becomes the sole interface manager. `NETWORKING_STACK=none`
prevents Armbian from layering another networking configuration over this one;
our installer enables NetworkManager, systemd-resolved and systemd-timesyncd. Existing YAML Wi-Fi credentials
will not be imported. Prepare the persistent JSON before OTA if Wi-Fi is needed.
Keep Ethernet and UART available for the first boot with this networking change.

```bash
systemctl --failed --no-pager
systemctl status widelapse-network NetworkManager ModemManager --no-pager
widelapse-network --status
nmcli device status
mmcli --list-modems
ip -4 route
resolvectl status
journalctl -u widelapse-network -u NetworkManager -u ModemManager -b --no-pager -n 100
```

Test missing config, valid config, invalid reload, SIM absent/PIN-required, USB
modem unplug/replug, and reboot. Verify Ethernet first, then remove Ethernet's
upstream internet while retaining its LAN link. Wi-Fi should become selected;
remove Wi-Fi internet to test cellular. Restore Ethernet and wait for recovery.
Compare `ip -4 route` and `resolvectl status` with JSON status. Test returning to
Ethernet while modem data remains connected. The host tests do not replace these
SIM7600/driver/physical network checks. RAUC's existing health confirmation checks
SSH, not all three uplinks; perform these tests before remote deployment.

## References

- [NetworkManager nmcli](https://networkmanager.pages.freedesktop.org/NetworkManager/NetworkManager/nmcli.html)
- [NetworkManager GSM settings](https://www.networkmanager.dev/docs/api/latest/settings-gsm.html)
- [NetworkManager IPv4 DNS and route settings](https://www.networkmanager.dev/docs/api/latest/settings-ipv4.html)

## Host verification

From the project root, run `python3 -m unittest discover -s tests -v`.
Real profile parsing tests require host `python3-gi` and `gir1.2-nm-1.0`.
The disposable Trixie smoke test installs packages only inside its container and
checks the installer, actual route-metric reapplication, and the Unix-socket API:

```bash
docker run --rm --cap-add NET_ADMIN --cap-add NET_RAW \
  -v "$PWD/userpatches/network:/assets:ro" \
  -v "$PWD/tests/network-smoke.sh:/smoke.sh:ro" \
  --entrypoint bash \
  ghcr.io/armbian/docker-armbian-build:armbian-debian-trixie-latest \
  /smoke.sh /assets
```

This uses Docker's isolated network, never host networking. The test skips only
replacement of Docker's bind-mounted `/etc/resolv.conf`; real image installation
sets the systemd-resolved stub symlink normally.
