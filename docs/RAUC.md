# Widelapse RAUC development integration

This is a board-specific A/B implementation for **Orange Pi Zero 3, microSD,
Armbian current, U-Boot v2026.07**. It needs a new factory flash. It does not
convert a running single-partition card in place. Back up pictures before
flashing. Do not write the new partition table to your running board.

Host tests are not evidence of successful hardware rollback. Use a spare card
and TTL for the first flash; complete the acceptance procedure below before
remote deployment. Application-only updates are not implemented in this phase.

## Storage layout and capacity

| Region | Size | Purpose |
| --- | --- | --- |
| Reserved beginning | 8 MiB | MBR, Allwinner SPL/U-Boot, two environment copies |
| p1 | 256 MiB | Fixed boot selector, not an OTA target |
| p2 | 3 GiB | System A, including its own `/boot` |
| p3 | 3 GiB | System B, including its own `/boot` |
| p4 | Remainder of card | Persistent `/opt/widelapse` |

The factory image is a sparse 7432 MiB file with an initial 1 GiB data partition.
Before mounting data, `widelapse-grow-data` expands p4 and its ext4 filesystem to
the remaining space. It checks the disk ID, starts, and system-slot sizes before
changing anything. It runs on subsequent boots too, so copying a complete card
onto a larger card also allows expansion. It never shrinks or moves partitions.
No rootfs expansion is allowed; Armbian's root-resize service is masked.

A card reporting 29.7 GiB leaves roughly **23.4 GiB** for data before ext4
metadata. A nominal 64 GB card leaves roughly **53.3 GiB**. Data ext4 uses zero
reserved-block percentage; the gateway must still manage free space and picture
retention. Downloads also need space in `/opt/widelapse/updates`.

The SD must enumerate as Linux `/dev/mmcblk0` and U-Boot `mmc 0`; Linux mmcblk0
was confirmed on this board. U-Boot numbering and the new bootloader still need
verification on hardware. This integration does not modify SPI flash.

Fixed disk ID `574c4150` gives stable PARTUUIDs. Do not attach another card cloned
from this image to the board at the same time: duplicate PARTUUIDs are ambiguous.
Changing this layout or disk ID is a new factory-image ABI, not an ordinary OTA.

## Files

- `userpatches/extensions/widelapse-rauc.sh`: Armbian partition, U-Boot and image
  export hooks. The U-Boot hook participates in Armbian's artifact hash. A final
  image guard verifies that the packaged U-Boot has the new environment layout.
- `userpatches/rauc/boot.cmd`: shared slot selector. Tries the primary slot, then
  the fallback, decrementing and saving attempts before boot. Kernel, initramfs
  and DTB are loaded from the chosen rootfs. The prototype uses the stock board
  DTB and does **not** process Armbian DT overlays or `armbianEnv.txt` overrides.
- `userpatches/rauc/system.conf`: two ext4 slots, signed plain bundles, persistent status.
- `userpatches/rauc/fw_env.config`: redundant 64 KiB environments at 4 MiB and
  4 MiB + 64 KiB, matching the U-Boot configuration.
- `userpatches/rauc/install.sh`: invoked inside the image by customization.
- `scripts/build-rauc-bundle.sh`: signs a rootfs export into an OTA bundle.
- `/usr/local/sbin/widelapse-update` on the board: downloads from your HTTP/HTTPS URL,
  verifies signatures, installs using RAUC; never reboots automatically.

`build-image.sh` stages the integration assets under the temporary build overlay.
The tracked `userpatches/rauc/` directory remains the editable source.

## Signing and provisioning

A development signing key was generated locally at `secrets/rauc-dev.key.pem`.
It is ignored by Git. The corresponding **public** certificate is
`userpatches/overlay/rauc-keyring.pem`, which can be committed and is installed
in every image. On another machine, restore the same signing key securely;
creating a new key will not authorize updates on already-deployed devices.

For a fresh project with no key or certificate:

```bash
bash scripts/create-rauc-dev-key.sh
```

The script refuses to replace existing trust material. Use a separate protected
production signing process before deployment. Signature verification requires
correct device time. HTTPS download alone is not the authenticity check.
The certificate does not implement secure boot or anti-downgrade protection.
This integration uses RAUC's signed `plain` format: the current Armbian kernel
has `CONFIG_DM_VERITY` disabled. RAUC verifies the whole bundle before installing;
this avoids a kernel rebuild for the initial integration. A future move to
`verity` bundles needs dm-verity enabled on devices **before** sending that format.

Keep supplying the ignored `authorized_keys` and `root-password.hash` inputs as
before. `bash scripts/check-rauc-inputs.sh` validates them without printing them.
The password hash and authorized client keys still belong to the OS image;
manual edits to `/etc`, `/root`, or installed packages are not persisted across
OS replacement. Store device configuration and pictures under `/opt/widelapse`.
SSH **server identity** keys are generated on first boot under
`/opt/widelapse/identity/ssh` and survive subsequent OS updates.

## Build the first factory image

From `widelapse_image/`, use the same working Armbian invocation as before:

```bash
bash build-image.sh
```

The current project configuration enables `widelapse-rauc` by default. Do not
combine it with encryption/LVM or override the partition switches. If your local
checkout still requires a privileged build, first fix the existing ownership
problem or follow your working build-host setup; this wrapper does not silently
escalate permissions.

The changed U-Boot configuration needs a new U-Boot build, not the previous
unmodified binary. Outputs under `build/output/images/` include:

- `...-rauc-ab...img` (possibly compressed): complete **factory** image.
- `...-rauc-ab...rootfs.ext4`: unmounted 3 GiB system filesystem for OTA bundles.

Flash the factory `.img` with Armbian Imager to a backed-up/spare SD card.
Do not flash the `.rootfs.ext4` as a whole SD image.

## Create and install a signed OS update

On a host with RAUC and squashfs-tools installed (e.g. Debian/Ubuntu packages
`rauc squashfs-tools`), using the rootfs export from a new build:

```bash
bash scripts/build-rauc-bundle.sh \
  build/output/images/EXACT-BUILD.rootfs.ext4 \
  0.1.0 \
  userpatches/overlay/rauc-keyring.pem \
  secrets/rauc-dev.key.pem \
  widelapse-0.1.0.raucb
```

Substitute the actual exported filename. The helper refuses whole-disk images,
checks the slot size, and verifies the completed signed bundle. Publish the
`.raucb` at your download URL. On the board:

```bash
widelapse-update https://your-server.example/releases/widelapse-0.1.0.raucb
rauc status
systemctl reboot
```

For a locally transferred bundle, `rauc install /path/to/update.raucb` works too.
An interrupted custom download is retried from scratch; HTTP range-resume,
version policy, scheduling, free-space limits and fleet reporting are future
work for the custom update service. The helper locks its own invocations;
avoid separately calling `rauc install` concurrently.

## Health confirmation and rollback

U-Boot tries each slot up to three times. A 90-second timer checks persistent
storage, the SSH service/config, and boot environment access before calling
`rauc status mark-good booted`. **By default this confirms OS health only.**

Before unattended application deployment, provide an executable
`/usr/local/libexec/widelapse-application-health` in the image and create
`/etc/widelapse/require-application-health`. Then confirmation also requires that
check to succeed within 60 seconds (include gateway service and camera checks).
Do not require access to an external internet endpoint just to accept a healthy
local system. A failed check leaves the slot unconfirmed. It does not immediately
reboot; a manual reboot/watchdog reset is needed to consume the next attempt.

The kernel has `panic=10`. systemd requests a 16-second hardware watchdog after
userspace starts, **if a working watchdog exists**. We have not qualified an early
boot watchdog handoff: a kernel hard hang before systemd may require a manual
power cycle. Do not claim unattended recovery from all failures until tested.
If both slots exhaust attempts, the selector stops at U-Boot for TTL recovery;
it does not silently reset counters and loop forever.

## Hardware acceptance procedure

1. Capture TTL from power-on. Confirm new U-Boot, successful `saveenv`, and
   `Widelapse: trying slot A`.
2. Check layout, root selection, data growth, and service health:

   ```bash
   lsblk -o NAME,SIZE,FSTYPE,MOUNTPOINTS
   cat /proc/cmdline
   findmnt /opt/widelapse
   df -h /opt/widelapse
   fw_printenv BOOT_ORDER BOOT_A_LEFT BOOT_B_LEFT
   rauc status
   systemctl status widelapse-grow-data widelapse-storage --no-pager
   systemctl status widelapse-rauc-confirm.timer --no-pager
   ```

3. Wait 90 seconds; inspect `journalctl -u widelapse-rauc-confirm`. Confirm the
   active slot is good. Check root password and key-only SSH still work.
4. Create `/opt/widelapse/data/ota-survival-test`. Record its checksum and the SSH
   host-key fingerprint. Install a signed second build, reboot, confirm slot B,
   and verify both are unchanged. Repeat B-to-A.
5. Build a test candidate containing `require-application-health` and a health
   script that exits 1. Install it. Reboot three failed attempts (TTL/manual
   power cycling as needed). The fourth boot should use the previous good slot.
   **Do not mark the known-good fallback bad.**
6. Verify unsigned, corrupted, wrong-signer and wrong-compatible bundles are
   rejected without changing the active slot. Run controlled power-cut tests
   during inactive-slot writes and environment updates, on a spare card.
7. Verify p4 grows on both 32 GB and 64 GB cards and the root slot sizes never
   change. Inspect `wdctl` and test watchdog recovery on the actual board.

TTL recovery for exhausted counters, only after confirming the custom U-Boot is
running and its environment offsets match this layout:

```text
setenv BOOT_ORDER 'A B'
setenv BOOT_A_LEFT 3
setenv BOOT_B_LEFT 3
saveenv
reset
```

Do not run environment-writing commands on the old single-partition image.
If SPI U-Boot supersedes the SD bootloader or environment access fails, stop and
capture the full TTL log; do not guess new raw offsets.

## Scope and limitations

OS OTA replaces the inactive rootfs including its kernel and DTB. It does not
update the partition table, shared selector, SPL/U-Boot, SPI flash, or data.
The selector and bootloader are a fixed factory ABI in this prototype.

The factory selector enables verbose kernel and systemd startup output on
`ttyS0` at 115200 baud. This is stored in p1's `boot.scr`, so an OS-only bundle
cannot enable it on an older factory image. Reflashing the updated factory
image installs the new selector but erases existing card data. A separate
maintenance update to the selector is not an A/B-protected RAUC update.

Keep application releases and mutable data separate under `/opt/widelapse`.
An OS rollback does not roll back shared application files or database schemas.
RAUC application artifacts and service activation/rollback will be a separate
integration after OS A/B boot works; the current bundle helper is OS-only.

Host verification: `python3 -m unittest discover -s tests -v`. The additional
`tests/container-smoke.sh` was run in an isolated Debian Trixie container with
RAUC 1.13 and libubootenv: signing, system-config parsing, wrong-signer and
corruption rejection, and redundant-environment read/write all passed using
regular temporary files (no block devices). The Python suite checks actual
MBR generation in a sparse regular file, safe growth/idempotence for 32/64 GB,
package hook execution and selector behavior with mocked bootloader commands.
It does not replace executing the selector in U-Boot or flashing a board.

References: [RAUC integration](https://rauc.readthedocs.io/en/v1.13/integration.html),
[RAUC reference](https://rauc.readthedocs.io/en/v1.13/reference.html),
[Armbian hooks](https://docs.armbian.com/build-framework/extensions/hooks/).
