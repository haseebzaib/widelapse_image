# Signed OS OTA: create, transfer, install, verify

Run laptop commands from `widelapse_image/`. Board commands run as root.
This guide assumes the new four-partition factory image boots successfully,
`rauc status` works, and the boot-health service has marked slot A good.
Keep TTL connected for the first test. Do not reflash to install a `.raucb`.

## What the first bundle contains

`ota/widelapse-0.1.1.raucb` is signed with the existing development signing key
and contains the latest built 3 GiB rootfs export. Version `0.1.1` adds the missing `squashfs-tools` package and an update helper
that accepts local HTTP URLs. The first `0.1.0` bundle lacked that package; use
`0.1.1` for the first installation. The test proves installation and A-to-B boot.
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
  0.1.1
```

The helper builds a local Docker tool image with RAUC, mounts the rootfs and
signing inputs read-only, creates the bundle, verifies its signature, and writes:

```text
ota/widelapse-0.1.1.raucb
ota/widelapse-0.1.1.raucb.sha256
```

The signing container runs without network access. `ota/` is ignored by Git.
The helper refuses to overwrite a bundle. This first bundle already exists;
use a new version such as `0.1.2` when making the next one. Version numbers do
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

For the first factory image, install the extraction utility before either
transfer method. The corrected 0.1.1 OS includes it for subsequent updates:

```bash
apt-get update
apt-get install -y squashfs-tools
```

```bash
systemctl --failed --no-pager
rauc status
df -h /opt/widelapse
date -u
mkdir -p /opt/widelapse/data /opt/widelapse/rauc/updates
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
  ota/widelapse-0.1.1.raucb ota/widelapse-0.1.1.raucb.sha256 \
  root@10.42.0.34:/opt/widelapse/rauc/updates/
```

On the board:

```bash
cd /opt/widelapse/rauc/updates
sha256sum -c widelapse-0.1.1.raucb.sha256
rauc --keyring=/etc/rauc/keyring.pem info widelapse-0.1.1.raucb
rauc install /opt/widelapse/rauc/updates/widelapse-0.1.1.raucb
```

The checksum checks transfer integrity; RAUC's signature check authenticates
the update. Wait for installation to succeed. If it fails, do not reboot;
capture the error and `journalctl -u rauc.service --no-pager -n 100`.

## 3B. Alternative: simple local HTTP download

Use this instead of 3A. On the laptop, from `widelapse_image/`:

```bash
python3 scripts/serve-ota.py 10.42.0.1
```

This starts a Python HTTP server on the laptop at `http://10.42.0.1:8000`.
It serves files from `ota/` only. Keep its terminal open; Ctrl-C stops it.
`10.42.0.1` is the laptop's Ethernet address, not a cloud server. Use
`ip -br address` if the address changes. This development server is for the
trusted test LAN: HTTP has no transport encryption or server authentication,
but RAUC still requires a valid bundle signature. No HTTPS CA is needed.

On the board, if using the first factory image, install the missing extraction
utility before the first OTA (the corrected 0.1.1 OS includes it):

```bash
apt-get update
apt-get install -y squashfs-tools
```

The first factory image's `widelapse-update` only accepts HTTPS. For this first
HTTP update, download and install explicitly:

```bash
cd /opt/widelapse/rauc/updates
curl --fail --location --output widelapse-0.1.1.raucb \
  http://10.42.0.1:8000/widelapse-0.1.1.raucb
rauc --keyring=/etc/rauc/keyring.pem info widelapse-0.1.1.raucb
rauc install /opt/widelapse/rauc/updates/widelapse-0.1.1.raucb
```

Run these sequentially and stop if any command fails. After booting the corrected
OS, the installed helper accepts HTTP as well as HTTPS:

```bash
widelapse-update http://10.42.0.1:8000/widelapse-0.1.2.raucb
```

Use an actually built bundle version in that URL. The helper downloads, verifies,
installs, and removes its temporary download; it does not reboot automatically.
HTTPS URLs still use normal certificate verification. No TLS configuration is
required for the local HTTP route.

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
host identity should also stay the same. The kernel and login banner are unchanged in this update; use slot status to
verify the switch and `command -v unsquashfs` to verify the added utility.

This verifies one OTA direction, not automatic rollback. Test B-to-A and then a
controlled failed-candidate rollback separately, following [RAUC.md](RAUC.md).
Do not mark your known-good fallback slot bad. Keep power connected during the
first installation and capture TTL if boot fails.

Reference: [RAUC bundle creation, installation, and status](https://rauc.readthedocs.io/en/v1.13/using.html).
