# Fixed selector on SD p1. Kernel/initramfs/DTB live inside each rootfs slot.
# No automatic fallback to distro_bootcmd: exhausted slots require recovery.
if test -z "${BOOT_ORDER}"; then
    setenv BOOT_ORDER "A B"
    setenv BOOT_A_LEFT 3
    setenv BOOT_B_LEFT 3
fi
for slot in ${BOOT_ORDER}; do
    setenv slotpart
    if test "${slot}" = "A"; then
        if test "${BOOT_A_LEFT}" -gt 0; then
            setexpr BOOT_A_LEFT ${BOOT_A_LEFT} - 1
            setenv slotpart 2
        fi
    fi
    if test "${slot}" = "B"; then
        if test "${BOOT_B_LEFT}" -gt 0; then
            setexpr BOOT_B_LEFT ${BOOT_B_LEFT} - 1
            setenv slotpart 3
        fi
    fi
    if test -n "${slotpart}"; then
        if saveenv; then
            echo "Widelapse: trying slot ${slot} on mmc 0:${slotpart}"
            if part uuid mmc 0:${slotpart} rootuuid; then
                setenv bootargs "root=PARTUUID=${rootuuid} rootwait rootfstype=ext4 console=ttyS0,115200 console=tty1 loglevel=4 panic=10 rauc.slot=${slot} cgroup_enable=memory"
                if load mmc 0:${slotpart} ${kernel_addr_r} /boot/Image; then
                    if load mmc 0:${slotpart} ${ramdisk_addr_r} /boot/uInitrd; then
                        if load mmc 0:${slotpart} ${fdt_addr_r} /boot/dtb/allwinner/sun50i-h618-orangepi-zero3.dtb; then
                            booti ${kernel_addr_r} ${ramdisk_addr_r} ${fdt_addr_r}
                        fi
                    fi
                fi
            fi
        else
            echo "Widelapse: environment write failed; refusing untracked boot"
            exit
        fi
    fi
 done
 echo "Widelapse: no bootable slot. Use TTL recovery or reflash."
