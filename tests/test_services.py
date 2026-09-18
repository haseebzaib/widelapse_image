"""Validate unit syntax and ordering with a synthetic, unprivileged system root."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ASSETS=Path(__file__).resolve().parents[1]/'userpatches/rauc'

@unittest.skipUnless(shutil.which('systemd-analyze'), 'systemd-analyze unavailable')
class ServiceTests(unittest.TestCase):
    def test_systemd_dependency_graph(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); units=root/'etc/systemd/system'; units.mkdir(parents=True)
            names=['widelapse-grow-data.service','widelapse-storage.service',
                   'widelapse-rauc-confirm.service','widelapse-rauc-confirm.timer']
            for name in names:
                (units/name).write_text((ASSETS/name).read_text())
            for name in ['sysinit.target','basic.target','shutdown.target','timers.target','multi-user.target','local-fs.target']:
                (units/name).write_text('[Unit]\nDescription=Test stub\nDefaultDependencies=no\n')
            for name in ['ssh.service','rauc.service','systemd-remount-fs.service']:
                (units/name).write_text('[Unit]\nDescription=Test stub\nDefaultDependencies=no\n[Service]\nExecStart=/bin/true\n')
            (units/'opt-widelapse.mount').write_text('[Mount]\nWhat=/dev/mmcblk0p4\nWhere=/opt/widelapse\nType=ext4\n')
            for unit, dropin in [('ssh.service','storage-dependency.conf'),('rauc.service','storage-dependency.conf'),('opt-widelapse.mount','data-mount.conf')]:
                directory=units/(unit+'.d'); directory.mkdir()
                (directory/'widelapse.conf').write_text((ASSETS/dropin).read_text())
            for name in ['usr/local/sbin/widelapse-grow-data','usr/local/sbin/widelapse-storage','usr/local/sbin/widelapse-rauc-confirm','bin/true']:
                p=root/name; p.parent.mkdir(parents=True,exist_ok=True)
                p.write_text('#!/bin/sh\nexit 0\n'); p.chmod(0o755)
            result=subprocess.run(['systemd-analyze','verify','--man=no','--root='+td]+names,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
