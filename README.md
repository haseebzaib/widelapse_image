# Widelapse image

Build a minimal Debian 13 (Trixie) Armbian image for the Orange Pi Zero 3.

The current configuration includes a **development RAUC A/B layout**. It requires
fresh flashing; it cannot update the old single-partition layout in place.
Two fixed 3 GiB OS slots leave the remaining SD-card space for `/opt/widelapse`.
The data partition expands automatically on 32 GB and 64 GB cards.
See [RAUC setup, signing, builds, and hardware acceptance](docs/RAUC.md) before building.
For creating and installing an update, follow [the signed OTA walkthrough](docs/OTA.md).
A development signing key is local under ignored `secrets/`; the public
verification certificate is tracked in `userpatches/overlay/rauc-keyring.pem`.

## Repository layout

```text
widelapse_image/
├── README.md
├── .gitignore
├── armbian-build-commit.txt       # Recorded Armbian framework revision
├── build-image.sh                # Copies customizations and starts the build
├── userpatches/                  # Our configuration, patches, and image scripts
│   ├── config-widelapse.conf
│   ├── device-setup/             # Persistent mount and SSH identity setup
│   ├── rauc/                     # OTA configuration and scripts
│   └── network/                  # Ethernet/Wi-Fi/cellular policy and JSON API
└── build/                       # Local Armbian checkout; ignored by Git
```

Edit the top-level `userpatches/` directory, not the copy under
`build/userpatches/`. Only the top-level directory is stored in this repository, excluding the ignored credential inputs.
Armbian's source, downloads, caches, logs, and images stay inside `build/`.
Armbian is a separate upstream checkout, not a submodule of this project.

## Set up a fresh checkout

Install Git, Docker, and Docker Buildx, and ensure `docker info` works.
Run from this repository's root:

```bash
git clone https://github.com/armbian/build.git build
git -C build checkout --detach "$(cat armbian-build-commit.txt)"
cd build
./compile.sh requirements
cd ..
```

Skip cloning if you already have the Armbian checkout. The recorded revision
is this project's baseline; do not change revisions during a running build.
Recording this revision alone does not guarantee byte-for-byte identical images:
external packages and source downloads can change too.

See [connectivity configuration and board tests](userpatches/network/README.md)
for Ethernet → Wi-Fi → cellular selection and the networking-backend transition.

## Build

From this repository's root:

Supply the ignored `userpatches/overlay/authorized_keys` and
`userpatches/overlay/root-password.hash` first. Follow the RAUC guide for signing.

```bash
bash scripts/check-rauc-inputs.sh
bash build-image.sh
```

The script copies our `userpatches/` contents into `build/userpatches/`, then runs
`./compile.sh build widelapse` inside `build/`. Armbian loads
`config-widelapse.conf` because the command selects `widelapse`.
Docker provides the build environment; Armbian manages build dependencies.

Extra command-line settings override the configuration, for example:

```bash
bash build-image.sh BUILD_MINIMAL=no
```

Images appear in `build/output/images/`; logs appear in `build/output/logs/`.
The copy preserves other local files. If you remove or rename a customization,
also remove its old copy from `build/userpatches/` before rebuilding, or use a
fresh checkout. Avoid running two builds in the same checkout at once.

See [device setup and persistent directories](userpatches/device-setup/README.md)
for where to change `/opt/widelapse` initialization.

## Pinned kernel

`userpatches/config-widelapse.conf` pins Linux **6.18.52** to commit
`8f3741e6feb045da5b406df0a80b42a1adfb289b` using `KERNELBRANCH=commit:...`.
This is the revision recorded in the working A/B image's build log and cached
kernel packages (`6.18.52-S8f37-...`). It replaces the moving `linux-6.18.y`
branch. Keep `BRANCH=current` for the existing board configuration and patches.

After interrupting an older build, let cleanup finish before running
`bash build-image.sh` again. The new configuration applies to the next build,
not a process already running. The log should resolve the pinned commit and
select `6.18.52-S8f37-...`; matching cached packages can be reused. A missing or
invalidated package cache may still require a kernel source download/build.

Update this commit deliberately after testing boot, Ethernet, Wi-Fi, USB cellular,
camera and OTA/rollback. Do not leave security updates unreviewed indefinitely.
This pins the kernel source used by image builds; it does not prevent package
updates on a running board, freeze Debian packages or pin the Docker `latest`
image. The Armbian framework revision remains recorded separately in
`armbian-build-commit.txt`.

## Add customizations

Put future customizations under the tracked `userpatches/` directory, preserving
Armbian's expected paths. For example, `customize-image.sh` is an image
customization hook, while `overlay/` can hold files that the hook installs.
Overlay files are not automatically installed just by being there.
Do not commit passwords, private SSH keys, or device-specific credentials.

Armbian's generated example configuration and unmodified customization template
are not included; add a customization hook here when the project needs one.

## Commit and upload

Run from this repository's root:

```bash
git status --short
git add .gitignore README.md armbian-build-commit.txt build-image.sh userpatches/ scripts/ docs/ tests/
git diff --cached --stat
git commit -m "Track Widelapse image configuration and build instructions"
git push -u origin HEAD
```

The existing origin is `https://github.com/haseebzaib/widelapse_image.git`.
The `/build/` ignore rule excludes the entire local Armbian directory.
Do not force-add it with `git add -f`.

## References

- [Armbian build setup](https://docs.armbian.com/build-framework/getting-started/)
- [Orange Pi Zero 3](https://armbian.com/boards/orangepizero3)
