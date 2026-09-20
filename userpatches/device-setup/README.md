# Device setup

Edit this directory for device initialization; OTA-specific setup stays in
`../rauc/`. `build-image.sh` stages both components into the build overlay and
`customize-image.sh` runs their installers inside the image.

## Responsibilities

- `install.sh`: creates the empty `/opt/widelapse` mountpoint in the OS image,
  installs scripts under `/usr/local/bin`, and installs/enables systemd units.
- `widelapse-grow-data`: grows partition 4 and its filesystem before mounting it.
  The fixed A/B partition layout remains defined by the RAUC build extension.
- `widelapse-init-directories`: verifies the mounted device and PARTUUID. Add
  application directory creation here when needed; none is currently created.
- `widelapse-init-identity`: creates `identity/ssh/` on persistent storage and
  generates a host key only when missing. SSH requires this service to succeed.
- `../rauc/widelapse-init-ota`: creates `rauc/` and `rauc/updates/`. RAUC requires
  this service to succeed. Bundle downloads use `rauc/updates/`.

Boot ordering is growth → data mount → mount verification → identity/OTA setup
→ SSH/RAUC. Unit files remain in `/etc/systemd/system`; executable scripts live
in `/usr/local/bin`. No fscrypt setup is included.

## Persistent layout

```text
/opt/widelapse/
├── identity/ssh/    # Unique SSH host key retained across OTA
├── rauc/           # RAUC slot status
│   └── updates/    # Temporary downloaded bundles
└── lost+found/     # Created by ext4
```

`config`, `data`, and `releases` are not automatically created. Existing folders
and files survive OTA unchanged, including the former top-level `updates/`.
No persistent data is deleted or migrated by this refactor. The existing SSH
host key and RAUC status paths are unchanged. Old image-side service/script
files are removed by the installers if present in the build rootfs.

Rebuild the image and sign its new rootfs export using `docs/OTA.md`. This change
can be installed through the existing updater; it does not change partition
boundaries, U-Boot, or the shared boot script. After reboot, check:

```bash
systemctl --failed --no-pager
systemctl status widelapse-init-directories widelapse-init-identity widelapse-init-ota --no-pager
command -v widelapse-update
rauc status
```

The updater should resolve to `/usr/local/bin/widelapse-update`. Confirm SSH still
recognizes the board's host key. Rollback boots the old OS's initialization
scripts, which can recreate its previous default directories.
