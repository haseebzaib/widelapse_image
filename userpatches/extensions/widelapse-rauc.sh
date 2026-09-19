# Widelapse Orange Pi Zero 3 SD-card A/B integration (U-Boot v2026.07).
# Keep layout constants in sync with the runtime layout guard and tests.
function user_config__widelapse_rauc() {
    [[ $BOARD == orangepizero3 && $BRANCH == current ]] || exit_with_error "RAUC supports orangepizero3/current only"
    declare -g ROOTFS_TYPE=ext4 IMAGE_PARTITION_TABLE=msdos
    declare -g OFFSET=8 BOOTSIZE=256 BOOTFS_TYPE=ext4 UEFISIZE=0
    declare -g FIXED_IMAGE_SIZE=7432 USE_HOOK_FOR_PARTITION=yes
    EXTRA_IMAGE_SUFFIXES+=("-rauc-ab")
    add_packages_to_image rauc rauc-service dbus squashfs-tools u-boot-tools libubootenv-tool cloud-guest-utils curl ca-certificates python3 e2fsprogs util-linux
}

function post_config_uboot_target__widelapse_rauc() {
    [[ $BOOTBRANCH == tag:v2026.07 ]] || exit_with_error "Re-audit RAUC environment offsets for this U-Boot version"
    # Explicitly select a redundant raw MMC environment, outside SPL/U-Boot.
    python3 - <<'PYCONFIG'
from pathlib import Path
settings = {
 'ENV_IS_IN_MMC':'y', 'ENV_IS_NOWHERE':'n', 'ENV_IS_IN_FAT':'n',
 'ENV_IS_IN_EXT4':'n', 'ENV_IS_IN_SPI_FLASH':'n', 'ENV_REDUNDANT':'y',
 'ENV_SIZE':'0x10000', 'ENV_OFFSET':'0x400000', 'ENV_OFFSET_REDUND':'0x410000',
 'ENV_MMC_DEVICE_INDEX':'0', 'ENV_MMC_EMMC_HW_PARTITION':'0',
 'ENV_MMC_USE_DT':'n', 'ENV_MMC_USE_SW_PARTITION':'n',
 'ENV_OFFSET_RELATIVE_END':'n', 'ENV_OFFSET_REDUND_RELATIVE_END':'n',
 'CMD_SAVEENV':'y', 'CMD_EXT4':'y', 'CMD_PART':'y', 'CMD_SETEXPR':'y',
 'CMD_FS_GENERIC':'y', 'CMD_BOOTI':'y', 'CMD_SOURCE':'y', 'HUSH_PARSER':'y',
 'USE_BOOTCOMMAND':'y',
 'BOOTCOMMAND':'"if load mmc 0:1 ${scriptaddr} /boot.scr; then source ${scriptaddr}; fi"',
}
p=Path('.config')
lines=p.read_text().splitlines()
for key,value in settings.items():
    name='CONFIG_'+key
    lines=[line for line in lines if not line.startswith(name+'=') and line != '# '+name+' is not set']
    lines.append('# '+name+' is not set' if value=='n' else name+'='+value)
p.write_text('\n'.join(lines)+'\n')
PYCONFIG
}

function uboot_make_config__widelapse_rauc_validate() {
    # Check olddefconfig actually retained our critical settings.
    local setting
    for setting in CONFIG_ENV_IS_IN_MMC=y CONFIG_ENV_REDUNDANT=y \
        CONFIG_ENV_OFFSET=0x400000 CONFIG_ENV_OFFSET_REDUND=0x410000 \
        CONFIG_ENV_SIZE=0x10000 CONFIG_ENV_MMC_DEVICE_INDEX=0 \
        CONFIG_CMD_FS_GENERIC=y CONFIG_CMD_BOOTI=y CONFIG_CMD_SOURCE=y CONFIG_HUSH_PARSER=y; do
        grep -qxF "$setting" .config || exit_with_error "U-Boot rejected RAUC setting: $setting"
    done
    grep -q '^CONFIG_BOOTCOMMAND=.*mmc 0:1.*boot.scr' .config || exit_with_error "Missing RAUC boot command"
}

function prepare_image_size__widelapse_rauc() {
    (( rootfs_size < 2600 )) || exit_with_error "Rootfs too large for 3 GiB RAUC slots (2600 MiB build limit)"
}

function create_partition_table__widelapse_rauc() {
    # MBR leaves Allwinner SPL at sector 16 intact. Fixed disk ID is the ABI.
    sfdisk "${SDCARD}.raw" <<'PARTITIONS'
label: dos
label-id: 0x574c4150
unit: sectors

start=16384, size=524288, type=83, bootable
start=540672, size=6291456, type=83
start=6832128, size=6291456, type=83
start=13123584, size=2097152, type=83
PARTITIONS
}

function format_partitions__widelapse_rauc() {
    # Armbian exposes p1/p2 itself; Docker also needs nodes for our extra slots.
    check_loop_device "${LOOP}p3"
    check_loop_device "${LOOP}p4"
    run_host_command_logged mkfs.ext4 -F -m 0 -L widelapse-data "${LOOP}p4"
    # Never use filesystem UUIDs for interchangeable slots.
    cat > "$SDCARD/etc/fstab" <<'FSTAB'
/dev/root / ext4 defaults,noatime 0 0
PARTUUID=574c4150-04 /opt/widelapse ext4 defaults,noatime 0 0
tmpfs /tmp tmpfs defaults,nosuid 0 0
FSTAB
}

function pre_umount_final_image__widelapse_rauc() {
    local cfg binary
    cfg=$(find "$MOUNT/usr/lib" -name 'u-boot-config-target-*' -type f -print -quit)
    [[ -n $cfg ]] || exit_with_error "Missing packaged U-Boot config; cannot verify RAUC environment"
    grep -qx 'CONFIG_ENV_OFFSET=0x400000' "$cfg" || exit_with_error "Cached U-Boot lacks RAUC environment layout"
    grep -qx 'CONFIG_ENV_OFFSET_REDUND=0x410000' "$cfg" || exit_with_error "U-Boot lacks redundant environment"
    grep -qx 'CONFIG_ENV_REDUNDANT=y' "$cfg" || exit_with_error "U-Boot lacks redundant environment support"
    binary=$(find "$MOUNT/usr/lib" -name 'u-boot-sunxi-with-spl.bin' -type f -print -quit)
    [[ -n $binary ]] || exit_with_error "Missing U-Boot binary for reserved-space check"
    (( $(stat -c %s "$binary") + 8192 < 4194304 )) || exit_with_error "U-Boot overlaps RAUC environment"
    test -s "$MOUNT/boot/Image" || exit_with_error "Missing slot kernel"
    test -s "$MOUNT/boot/uInitrd" || exit_with_error "Missing slot initramfs"
    test -s "$MOUNT/boot/dtb/allwinner/sun50i-h618-orangepi-zero3.dtb" || exit_with_error "Unexpected DTB path"
    local work="$MOUNT/.widelapse-image-work"
    mkdir -p "$work/kernel"
    # Armbian assembled /boot on p1; relocate it into each system slot.
    cp -a "$MOUNT/boot/." "$work/kernel/"
    umount "$MOUNT/boot"
    cp -a "$work/kernel/." "$MOUNT/boot/"
    rm -rf "$work/kernel"
    mkdir -p "$work/selector" "$work/data"
    mount "${LOOP}p1" "$work/selector"
    # Clear only this freshly generated selector filesystem, not a host path.
    find "$work/selector" -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
    mkimage -A arm -T script -C none -n 'Widelapse A/B v1' \
        -d "$USERPATCHES_PATH/rauc/boot.cmd" "$work/selector/boot.scr"
    umount "$work/selector"
    mount "${LOOP}p4" "$work/data"
    cp -a "$MOUNT/opt/widelapse/." "$work/data/"
    umount "$work/data"
    rmdir "$work/selector" "$work/data" "$work"
    # The immutable selector owns boot arguments; do not use old slot UUIDs.
    rm -f "$MOUNT/boot/boot.scr" "$MOUNT/boot/boot.cmd"
    sync
}

function post_umount_final_image__widelapse_rauc() {
    # Both slot filesystems must be unmounted before copying/exporting them.
    dd if="${LOOP}p2" of="${LOOP}p3" bs=4M conv=fsync status=progress
    tune2fs -U random "${LOOP}p3"
    mkdir -p "$DESTIMG"
    dd if="${LOOP}p2" of="$DESTIMG/${version}.rootfs.ext4" bs=4M conv=sparse,fsync status=progress
}
