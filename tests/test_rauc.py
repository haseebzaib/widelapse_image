"""Host-side tests; never access block devices or print provisioning secrets."""
import configparser
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / 'userpatches/extensions/widelapse-rauc.sh'
ASSETS = ROOT / 'userpatches/rauc'

class LayoutTests(unittest.TestCase):
    def test_real_partition_table_on_sparse_regular_file(self):
        sfdisk = shutil.which('sfdisk') or '/usr/sbin/sfdisk'
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / 'factory.raw'
            with target.open('wb') as f:
                f.truncate(7432 * 1024**2)
            subprocess.run(['bash', '-c', 'source "$1"; create_partition_table__widelapse_rauc',
                            'test', str(EXT)], env={**os.environ, 'SDCARD': str(target)[:-4],
                            'PATH': '/usr/sbin:' + os.environ['PATH']}, check=True, capture_output=True)
            table = json.loads(subprocess.check_output([sfdisk, '--json', str(target)]))['partitiontable']
            self.assertEqual(table['id'], '0x574c4150')
            parts = table['partitions']
            self.assertEqual([p['start'] for p in parts], [16384, 540672, 6832128, 13123584])
            self.assertEqual(parts[1]['size'], parts[2]['size'])
            self.assertEqual(parts[-1]['start'] + parts[-1]['size'], target.stat().st_size // 512)
            for prev, nxt in zip(parts, parts[1:]):
                self.assertLessEqual(prev['start'] + prev['size'], nxt['start'])
            self.assertLess(0x410000 + 0x10000, parts[0]['start'] * 512)
            self.assertEqual(parts[1]['size'] * 512, 3 * 1024**3)

    def test_package_hook_executes_as_one_command(self):
        code = 'enable_extension() { :; }; add_packages_to_image() { printf "%s\\n" "$@"; }; source "$1"; user_config__widelapse_packages'
        result = subprocess.check_output(['bash', '-c', code, 'test', str(ROOT/'userpatches/config-widelapse.conf')], text=True)
        self.assertEqual(result.splitlines(), ['net-tools', 'openssh-server', 'fail2ban'])

    def test_rauc_does_not_target_persistent_data_or_selector(self):
        cfg = configparser.ConfigParser()
        cfg.read(ASSETS/'system.conf')
        slots = [cfg[s]['device'] for s in cfg.sections() if s.startswith('slot.')]
        self.assertEqual(slots, ['/dev/disk/by-partuuid/574c4150-02', '/dev/disk/by-partuuid/574c4150-03'])
        self.assertTrue(cfg['system']['statusfile'].startswith('/opt/widelapse/'))

    def test_boot_script_compiles(self):
        with tempfile.TemporaryDirectory() as td:
            subprocess.run(['mkimage', '-A', 'arm', '-T', 'script', '-C', 'none', '-d', str(ASSETS/'boot.cmd'), td+'/boot.scr'], check=True, capture_output=True)

class GrowTests(unittest.TestCase):
    def run_grow(self, table, message='CHANGED: partition=4', status=0, fsck_status=0):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)
            (path/'table.json').write_text(json.dumps(table))
            commands={
                'sfdisk': '#!/bin/sh\ncat "$FAKE/table.json"\n',
                'growpart': '#!/bin/sh\nprintf "%s\\n" "$GROW_MESSAGE"\nexit "$GROW_STATUS"\n',
                'udevadm': '#!/bin/sh\nexit 0\n',
                'e2fsck': '#!/bin/sh\nfor arg in "$@"; do\n  if [ "$arg" = -f ]; then touch "$FAKE/forced-check"; fi\ndone\nexit "$FSCK_STATUS"\n',
                'resize2fs': '#!/bin/sh\n[ -f "$FAKE/forced-check" ] || exit 1\necho resize >> "$FAKE/actions"\n',
            }
            for name, body in commands.items():
                (path/name).write_text(body); (path/name).chmod(0o755)
            env={**os.environ, 'PATH':td+':'+os.environ['PATH'], 'FAKE':td,
                 'GROW_MESSAGE':message, 'GROW_STATUS':str(status), 'FSCK_STATUS':str(fsck_status)}
            result=subprocess.run(['bash',str(ROOT/'userpatches/device-setup/widelapse-grow-data')], env=env, capture_output=True)
            return result.returncode, (path/'actions').exists()

    def table(self):
        return {'partitiontable':{'label':'dos','id':'0x574c4150','sectorsize':512,'partitions':[
            {'node':'/dev/mmcblk0p1','start':16384,'size':524288},
            {'node':'/dev/mmcblk0p2','start':540672,'size':6291456},
            {'node':'/dev/mmcblk0p3','start':6832128,'size':6291456},
            {'node':'/dev/mmcblk0p4','start':13123584,'size':2097152}]}}

    def test_resize_after_growth(self):
        self.assertEqual(self.run_grow(self.table()), (0, True))

    def test_already_grown_is_idempotent(self):
        for sectors in (32000000000//512, 64000000000//512):
            table=self.table(); table['partitiontable']['partitions'][3]['size']=sectors-13123584
            self.assertEqual(self.run_grow(table, 'NOCHANGE: partition 4 is size ...', 1), (0, True))

    def test_fsck_corrected_errors_can_resize(self):
        self.assertEqual(self.run_grow(self.table(),fsck_status=1), (0, True))

    def test_fsck_uncorrected_errors_stop_resize(self):
        rc,resized=self.run_grow(self.table(),fsck_status=4)
        self.assertEqual(rc,4); self.assertFalse(resized)

    def test_wrong_disk_is_rejected(self):
        table=self.table(); table['partitiontable']['id']='0xdeadbeef'
        rc,resized=self.run_grow(table)
        self.assertNotEqual(rc,0); self.assertFalse(resized)

    def test_wrong_slot_boundary_is_rejected(self):
        table=self.table(); table['partitiontable']['partitions'][1]['size']+=2048
        rc,resized=self.run_grow(table)
        self.assertNotEqual(rc,0); self.assertFalse(resized)

    def test_failed_growth_never_resizes(self):
        rc,resized=self.run_grow(self.table(),'FAILED: I/O error',2)
        self.assertEqual(rc,2); self.assertFalse(resized)

class BootSelectionTests(unittest.TestCase):
    # Exercise the actual selector's control flow using Bash implementations of
    # U-Boot commands. This does not replace a Hush/U-Boot hardware test.
    def boot(self, a, b, order='A B', failpart='', saveok=True):
        shim=r'''
setenv() { local name=$1; shift; printf -v "$name" '%s' "$*"; }
setexpr() { printf -v "$1" '%s' "$(($2 - $4))"; }
saveenv() {
    printf '%s %s\n' "$BOOT_A_LEFT" "$BOOT_B_LEFT" > "$STATE"
    test "$SAVEOK" = yes
}
part() { setenv rootuuid "574c4150-0${slotpart}"; }
load() { test "$2" != "0:$FAILPART"; }
booti() { echo "BOOTED:$slot:$bootargs"; exit 0; }
source "$SELECTOR"
'''
        with tempfile.TemporaryDirectory() as td:
            env={**os.environ,'BOOT_A_LEFT':str(a),'BOOT_B_LEFT':str(b),'BOOT_ORDER':order,
                 'STATE':td+'/state','SAVEOK':'yes' if saveok else 'no','FAILPART':failpart,
                 'SELECTOR':str(ASSETS/'boot.cmd')}
            p=subprocess.run(['bash','-c',shim],env=env,capture_output=True,text=True)
            state=Path(td+'/state').read_text().strip() if Path(td+'/state').exists() else None
            return p.stdout,state

    def test_candidate_tries_decrement_before_boot(self):
        output,state=self.boot(3,3,'B A')
        self.assertIn('BOOTED:B:root=PARTUUID=574c4150-03',output)
        self.assertIn('rauc.slot=B',output)
        self.assertEqual(state,'3 2')

    def test_exhausted_candidate_falls_back(self):
        output,state=self.boot(3,0,'B A')
        self.assertIn('BOOTED:A:',output); self.assertEqual(state,'2 0')

    def test_failed_kernel_load_tries_other_slot(self):
        output,state=self.boot(3,3,'B A','3')
        self.assertIn('BOOTED:A:',output); self.assertEqual(state,'2 2')

    def test_no_boot_when_both_exhausted(self):
        output,state=self.boot(0,0)
        self.assertNotIn('BOOTED:',output)

    def test_env_write_failure_does_not_boot(self):
        output,state=self.boot(3,3,saveok=False)
        self.assertNotIn('BOOTED:',output)

if __name__=='__main__':
    unittest.main()
