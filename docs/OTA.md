# Signed OS OTA: create, transfer, install, verify

Run laptop commands from `widelapse_image/`. Board commands run as root.
This guide assumes the new four-partition factory image boots successfully,
`rauc status` works, and the boot-health service has marked slot A good.
Keep TTL connected for the first test. Do not reflash to install a `.raucb`.

## What the first bundle contains

`ota/widelapse-0.1.0.raucb` is signed with the existing development signing key
and contains the latest built 3 GiB rootfs export. It contains the same OS as
the corrected factory image; version `0.1.0` is bundle metadata, not a claim
of additional OS changes. The first test proves installation and A-to-B boot.
The bundle uses compressed SquashFS, so its download size is smaller than 3 GiB.

OTA replaces the inactive system slot: kernel, initramfs, DTB, packages, and
system services. It preserves `/opt/widelapse` and does not update U-Boot,
the shared boot selector (including UART arguments), or the partition table.
Applications stored in `/opt/widelapse` are not replaced by this OS bundle.

## 1. Create a signed bundle on the laptop

For future OS changes, first edit the tracked `userpatches/` files and run:

```bash
bash build-image.sh
```

For this first test, the corrected image is already built. Use its export:

```bash
bash scripts/build-rauc-bundle-docker.sh \
  build/output/images/Armbian-unofficial_26.11.0-trunk_Orangepizero3_trixie_current_6.18.52-rauc-ab_minimal.rootfs.ext4 \
  0.1.0
```

The helper builds a local Docker tool image with RAUC, mounts the rootfs and
signing inputs read-only, creates the bundle, verifies its signature, and writes:

```text
ota/widelapse-0.1.0.raucb
ota/widelapse-0.1.0.raucb.sha256
```

The signing container runs without network access. `ota/` is ignored by Git.
The helper refuses to overwrite a bundle. This first bundle already exists;
use a new version such as `0.1.1` when making the next one. Version numbers do
not enforce anti-downgrade protection in this setup.

The inputs are:

- Exported `.rootfs.ext4`: one system slot, never the full factory `.img`.
- `userpatches/overlay/rauc-keyring.pem`: public certificate already trusted by
  the board.
- `secrets/rauc-dev.key.pem`: private signing key, ignored by Git. Keep it on the
  laptop and back it up securely. Do not regenerate it for each update or copy
  it to the board/server directory.

If RAUC and squashfs-tools are installed directly on your laptop, you can use
the original helper instead:

```bash
mkdir -p ota
bash scripts/build-rauc-bundle.sh \
  build/output/images/Armbian-unofficial_26.11.0-trunk_Orangepizero3_trixie_current_6.18.52-rauc-ab_minimal.rootfs.ext4 \
  0.1.1 userpatches/overlay/rauc-keyring.pem secrets/rauc-dev.key.pem \
  ota/widelapse-0.1.1.raucb
```

## 2. Check the board and create a persistence test

```bash
systemctl --failed --no-pager
rauc status
df -h /opt/widelapse
date -u
printf 'Widelapse OTA persistence test\n' > /opt/widelapse/data/ota-survival-test
sha256sum /opt/widelapse/data/ota-survival-test
```

Record the checksum. Confirm the booted slot is A and there is space for the
bundle in `/opt/widelapse` (allow at least 2 GiB for this initial test).
Correct device time is required for certificate checks. If the clock is wrong,
fix time synchronization before installing; do not disable signature checks.

## 3A. First test: transfer over SSH

On the laptop (replace the board IP if it changed):

```bash
scp -i ~/.ssh/widelapse_ed25519 \
  ota/widelapse-0.1.0.raucb ota/widelapse-0.1.0.raucb.sha256 \
  root@10.42.0.34:/opt/widelapse/updates/
```

On the board:

```bash
cd /opt/widelapse/updates
sha256sum -c widelapse-0.1.0.raucb.sha256
rauc --keyring=/etc/rauc/keyring.pem info widelapse-0.1.0.raucb
rauc install /opt/widelapse/updates/widelapse-0.1.0.raucb
```

The checksum checks transfer integrity; RAUC's signature check authenticates
the update. Wait for installation to succeed. If it fails, do not reboot;
capture the error and `journalctl -u rauc.service --no-pager -n 100`.

## 3B. Alternative: local HTTPS download

Use this instead of 3A to test the installed `widelapse-update` helper.
No fleet server is required: the laptop serves the signed file, and you trigger
the update on the board. This development server has no client authentication;
run it on your trusted test LAN, serve only `ota/`, and stop it after testing.

On the laptop, choose its LAN IP reachable from the board. For the existing
shared-network setup this may be `10.42.0.1`; check with `ip -br address`.

```bash
python3 scripts/serve-ota.py 10.42.0.1
```

Keep that terminal open. The helper generates a separate 30-day self-signed TLS
certificate under `secrets/ota-tls-10.42.0.1/`. This HTTPS certificate is unrelated
to the RAUC signing certificate. It is reused on later runs for the same IP.
If it expires, archive that certificate/key pair, generate a fresh pair, and
copy the new public certificate to the board. A new laptop IP needs a matching
certificate and a new copy on the board.

In a second laptop terminal, transfer only the public TLS certificate over SSH:

```bash
scp -i ~/.ssh/widelapse_ed25519 \
  secrets/ota-tls-10.42.0.1/server.crt \
  root@10.42.0.34:/opt/widelapse/config/ota-lan-server.crt
```

On the board:

```bash
CURL_CA_BUNDLE=/opt/widelapse/config/ota-lan-server.crt \
  widelapse-update https://10.42.0.1:8443/widelapse-0.1.0.raucb
```

This trusts the LAN TLS certificate only for this command; it does not disable
HTTPS verification or replace the RAUC trust store. The helper downloads to
persistent storage, verifies the bundle, installs it, then removes its temporary
download. It does not reboot automatically. If the server cannot be reached,
check the laptop IP, TCP port 8443, and laptop firewall. Do not use `curl -k`.

## 4. Reboot and verify slot B

Only after successful installation:

```bash
rauc status
systemctl reboot
```

Before reboot, A is still running and B should be activated for next boot.
Reconnect via SSH after boot, wait at least 90 seconds for health confirmation:

```bash
rauc status
cat /proc/cmdline
findmnt -n -o SOURCE /
systemctl --failed --no-pager
journalctl -b -u widelapse-rauc-confirm.service --no-pager
sha256sum /opt/widelapse/data/ota-survival-test
df -h /opt/widelapse
```

Expected: `rootfs.1 (B)` booted, root on `/dev/mmcblk0p3`, `rauc.slot=B`, health
confirmation marks B good, and the persistence checksum is unchanged. The SSH
host identity should also stay the same. Since this bundle contains the same OS,
`uname` and the login banner are expected to be unchanged.

This verifies one OTA direction, not automatic rollback. Test B-to-A and then a
controlled failed-candidate rollback separately, following [RAUC.md](RAUC.md).
Do not mark your known-good fallback slot bad. Keep power connected during the
first installation and capture TTL if boot fails.

Reference: [RAUC bundle creation, installation, and status](https://rauc.readthedocs.io/en/v1.13/using.html).
