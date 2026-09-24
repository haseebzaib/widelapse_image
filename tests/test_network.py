"""Offline policy/profile tests: never touch host interfaces, D-Bus or credentials."""
import importlib.machinery
import importlib.util
import json
import shutil
import subprocess
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock

PATH = Path(__file__).resolve().parents[1] / 'userpatches/network/widelapse-network'
loader = importlib.machinery.SourceFileLoader('widelapse_network', str(PATH))
spec = importlib.util.spec_from_loader(loader.name, loader)
n = importlib.util.module_from_spec(spec)
loader.exec_module(n)


class InstallerTests(unittest.TestCase):
    def test_installer_preserves_build_resolver(self):
        # Execute the installer with absolute filesystem paths redirected to a
        # temporary root. Only systemctl and dependency probes are stubbed.
        # Real install/rm/ln operations run, never against host system paths.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            assets = root/'tmp/overlay/widelapse-network'
            shutil.copytree(PATH.parent, assets)
            (root/'etc/systemd/system').mkdir(parents=True)
            resolver = root/'etc/resolv.conf'
            resolver.write_text('nameserver 192.0.2.53\n')
            inode = resolver.stat().st_ino
            stub = root/'stubs'; stub.mkdir()
            for name in ('systemctl', 'getent', 'groupadd', 'nmcli', 'mmcli', 'qmicli', 'rfkill', 'iw'):
                f = stub/name; f.write_text('#!/bin/sh\nexit 0\n'); f.chmod(0o755)
            python = root/'usr/bin/python3'; python.parent.mkdir(parents=True)
            python.write_text('#!/bin/sh\nexit 0\n'); python.chmod(0o755)
            script = (assets/'install.sh').read_text()
            # Single regex pass avoids replacing prefixes in the temporary path.
            import re, os
            script = re.sub(r'/(etc|usr|tmp|run)/', lambda m: td + m.group(0), script)
            subprocess.run(['bash', '-c', script], check=True, capture_output=True,
                           env={**os.environ, 'PATH': str(stub) + ':' + os.environ['PATH']})
            self.assertFalse(resolver.is_symlink())
            self.assertEqual(resolver.stat().st_ino, inode)
            self.assertEqual(resolver.read_text(), 'nameserver 192.0.2.53\n')
            self.assertTrue((root/'usr/local/bin/widelapse-network').exists())
            self.assertTrue((root/'etc/systemd/system/widelapse-network.service').exists())


class ConfigTests(unittest.TestCase):
    def test_missing_config_enables_all_and_requires_no_wifi_credentials(self):
        with tempfile.TemporaryDirectory() as td:
            cfg, source = n.read_config(Path(td)/'absent')
        self.assertEqual(source, 'defaults')
        self.assertTrue(all(cfg[k]['enabled'] for k in n.KINDS))
        self.assertEqual(cfg['wifi']['networks'], [])
        self.assertTrue(cfg['cellular']['allow_roaming'])

    def test_application_owned_config_is_accepted(self):
        from types import SimpleNamespace
        path = MagicMock()
        path.exists.return_value = True
        path.stat.return_value = SimpleNamespace(st_size=2, st_uid=1001, st_mode=0o100664)
        path.read_text.return_value = '{}'
        cfg, source = n.read_config(path)
        self.assertEqual(source, 'file')
        self.assertTrue(cfg['eth']['enabled'])

    def test_nonroot_client_can_query_service(self):
        client = MagicMock(); client.__enter__.return_value = client
        client.recv.return_value = b'{"ready":true}\n'
        with patch.object(n.os, 'geteuid', return_value=1001), patch.object(n.sys, 'argv', ['widelapse-network', '--status']), patch.object(n.socket, 'socket', return_value=client), patch('builtins.print'):
            n.main()
        client.connect.assert_called_once()

    def test_rejects_invalid_input_before_changing_connections(self):
        bad = [[], {'eth': {'enabled': 'false'}}, {'wifi': {'interface': 'bad;name'}},
               {'policy': {'priority': ['eth', 'eth', 'cellular']}},
               {'cellular': {'allow_roaming': 1}}, {'policy': {'failure_threshold': 0}},
               {'wifi': {'networks': [{'ssid': 'test', 'password': 'short'}]}},
               {'cellular': {'sim_pin': 'secret'}}, {'wifi': {'networks': [None]}},
               {'policy': {'probe_targets': [{'address': 'somewhere'}]}},
               {'unexpected': {}}, {'eth': {'interface': 'wlan0'}}]
        for raw in bad:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                n.validate(raw)

    def test_invalid_reload_preserves_config_and_profiles(self):
        manager = n.Manager(); manager.cfg = n.validate({})
        original = manager.cfg
        with patch.object(n, 'read_config', side_effect=ValueError('invalid JSON configuration')), patch.object(n, 'command') as cmd:
            self.assertFalse(manager.request({'command': 'reload'})['ok'])
            cmd.assert_not_called()
        self.assertIs(manager.cfg, original)

    def test_secret_not_in_validation_error(self):
        with self.assertRaises(ValueError) as error:
            n.validate({'wifi': {'networks': [{'ssid': 'test', 'password': 'shhh'}]}})
        self.assertNotIn('shhh', str(error.exception))


class PolicyTests(unittest.TestCase):
    def test_failover_and_recovery_hysteresis(self):
        p = n.validate({})['policy']; h = n.Health()
        for _ in range(3):
            for k in n.KINDS: h.update(k, True, True, p)
        self.assertEqual(h.choose(p), 'eth')
        for _ in range(2): h.update('eth', True, False, p)
        self.assertEqual(h.choose(p), 'eth')
        h.update('eth', True, False, p)
        self.assertEqual(h.choose(p), 'wifi')
        h.update('wifi', False, False, p)
        self.assertEqual(h.choose(p), 'cellular')
        for _ in range(2): h.update('eth', True, True, p)
        self.assertEqual(h.choose(p), 'cellular')
        h.update('eth', True, True, p)
        self.assertEqual(h.choose(p), 'eth')

    def test_unplug_and_no_internet(self):
        p = n.validate({})['policy']; h = n.Health()
        self.assertIsNone(h.choose(p))
        for _ in range(3): h.update('cellular', True, True, p)
        h.update('cellular', False, False, p)
        self.assertIsNone(h.choose(p))

    def test_probes_bind_to_standby_device_and_use_literal_ip(self):
        sock = MagicMock(); sock.__enter__.return_value = sock
        context = MagicMock()
        with patch.object(n.socket, 'socket', return_value=sock), patch.object(n.ssl, 'create_default_context', return_value=context):
            self.assertTrue(n.probe('wwu1i5', n.DEFAULT['policy']))
        sock.setsockopt.assert_called_once_with(n.socket.SOL_SOCKET, n.socket.SO_BINDTODEVICE, b'wwu1i5\0')
        sock.connect.assert_called_once_with(('1.1.1.1', 443))
        context.wrap_socket.assert_called_once_with(sock, server_hostname='one.one.one.one')

    def test_failed_routes_are_reported_and_retried(self):
        m = n.Manager(); m.cfg = n.validate({'policy': {'recovery_threshold': 1}})
        rows = {k: {'connected': k == 'eth', 'ip_ready': k == 'eth',
                    'interface': 'end0' if k == 'eth' else None,
                    'control_interface': 'end0', 'uuid': 'test'} for k in n.KINDS}
        with patch.object(m, 'links', return_value=rows), patch.object(m, 'modem', return_value={}), patch.object(n, 'probe', return_value=True), patch.object(m, 'routes', side_effect=RuntimeError('failed')) as route, patch.object(m, 'dns') as dns:
            m.tick(); m.tick()
        self.assertFalse(m.status['routing_applied'])
        self.assertEqual(m.status['route_errors'], ['eth'])
        self.assertEqual(route.call_count, 2)
        dns.assert_not_called()


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.manager = n.Manager()
        self.rows = {'cellular': {'interface': 'wwu1i5', 'addresses': ['10.54.44.102'],
                                 'gateway': '10.54.44.101', 'ip_ready': True, 'dns': ['39.39.39.39']}}

    def test_switch_adds_only_owned_route_never_reapplies_link(self):
        with patch.object(n, 'command', side_effect=['[]', '']) as cmd:
            self.manager.routes(self.rows, 'cellular')
        self.assertEqual(cmd.call_args.args, ('ip', '-4', 'route', 'replace', 'default', 'via',
                          '10.54.44.101', 'dev', 'wwu1i5', 'src', '10.54.44.102',
                          'proto', '242', 'metric', '5', 'onlink'))
        self.assertFalse(any('nmcli' in c.args or 'flush' in c.args or 'address' in c.args for c in cmd.call_args_list))

    def test_route_is_repaired_after_external_removal(self):
        with patch.object(n, 'command', side_effect=['[]', '', '[]', '']) as cmd:
            self.manager.routes(self.rows, 'cellular'); self.manager.routes(self.rows, 'cellular')
        self.assertEqual(sum('replace' in c.args for c in cmd.call_args_list), 2)

    def test_existing_correct_route_is_untouched(self):
        current = [{'dst': 'default', 'metric': 5, 'protocol': '242', 'dev': 'wwu1i5',
                    'gateway': '10.54.44.101', 'prefsrc': '10.54.44.102'}]
        with patch.object(n, 'command', return_value=json.dumps(current)) as cmd:
            self.manager.routes(self.rows, 'cellular')
        cmd.assert_called_once()

    def test_no_healthy_link_removes_only_owned_route(self):
        current = [{'metric': 5, 'protocol': '242', 'dev': 'wwu1i5'},
                   {'metric': 300, 'protocol': 'static', 'dev': 'wwu1i5'}]
        with patch.object(n, 'command', side_effect=[json.dumps(current), '']) as cmd:
            self.manager.routes(self.rows, None)
        self.assertEqual(cmd.call_args.args, ('ip', '-4', 'route', 'del', 'default', 'dev', 'wwu1i5', 'proto', '242', 'metric', '5'))

    def test_foreign_reserved_route_is_not_overwritten(self):
        with patch.object(n, 'command', return_value='[{"metric":5,"protocol":"static"}]') as cmd:
            with self.assertRaises(RuntimeError): self.manager.routes(self.rows, 'cellular')
        cmd.assert_called_once()

    def test_negotiated_gateway_change_replaces_route(self):
        old = [{'metric': 5, 'protocol': '242', 'dev': 'wwu1i5', 'gateway': '10.1.1.1', 'prefsrc': '10.1.1.2'}]
        with patch.object(n, 'command', side_effect=[json.dumps(old), '']) as cmd:
            self.manager.routes(self.rows, 'cellular')
        self.assertIn('10.54.44.102', cmd.call_args.args)

    def test_dns_is_selected_without_nm_reapply_and_retried(self):
        self.rows['eth'] = {'interface': 'end0', 'dns': ['10.42.0.1']}
        with patch.object(Path, 'exists', return_value=True), patch.object(n, 'command', return_value='') as cmd:
            self.assertEqual(self.manager.dns(self.rows, 'cellular'), [])
            self.assertEqual(self.manager.dns(self.rows, 'cellular'), [])
        self.assertTrue(all(c.args[0] == 'resolvectl' for c in cmd.call_args_list))
        self.assertIn(unittest.mock.call('resolvectl', 'dns', 'wwu1i5', '39.39.39.39'), cmd.call_args_list)
        self.assertIn(unittest.mock.call('resolvectl', 'dns', 'end0', ''), cmd.call_args_list)

    def test_kernel_addresses_override_stale_networkmanager_address(self):
        from unittest.mock import MagicMock
        m = self.manager; m.cfg = n.validate({}); m.entries = {'cellular-uuid': None}
        nm = MagicMock(); device = MagicMock()
        nm.Client.new.return_value.get_devices.return_value = [device]
        device.get_iface.return_value = 'cdc-wdm0'
        device.get_ip_iface.return_value = 'wwu1i5'
        device.get_device_type.return_value = nm.DeviceType.MODEM
        device.get_state.return_value = nm.DeviceState.ACTIVATED
        device.get_active_connection.return_value.get_uuid.return_value = 'cellular-uuid'
        device.get_ip4_config.return_value.get_addresses.return_value = [MagicMock()]
        with patch.object(n, 'bindings', return_value=(None, nm)), patch.object(n, 'command', return_value='[{"ifname":"wwu1i5","addr_info":[]}]'):
            row = m.links()['cellular']
        self.assertTrue(row['connected'])
        self.assertFalse(row['ip_ready'])
        self.assertEqual(row['addresses'], [])

    def test_no_ipv4_is_not_probed_or_selected(self):
        m = self.manager; m.cfg = n.validate({})
        rows = {k: {'connected': True, 'ip_ready': False, 'interface': k, 'uuid': k} for k in n.KINDS}
        with patch.object(m, 'links', return_value=rows), patch.object(m, 'modem', return_value={}), patch.object(n, 'probe') as probe, patch.object(m, 'routes') as routes, patch.object(m, 'dns', return_value=[]):
            m.tick()
        probe.assert_not_called(); routes.assert_called_once_with(rows, None)
        self.assertIsNone(m.status['selected'])


class SimTests(unittest.TestCase):
    def test_failed_pin_is_not_retried(self):
        try:
            from gi.repository import Gio
        except ImportError:
            self.skipTest('Gio is required')
        m = n.Manager(); m.cfg = n.validate({'cellular': {'sim_pin': '1234'}})
        generic = {'device-identifier': 'test-modem', 'sim': '/org/freedesktop/ModemManager1/SIM/0'}
        with tempfile.TemporaryDirectory() as td, patch.object(n, 'CONFIG', Path(td)/'network.json'), patch.object(Gio, 'bus_get_sync', side_effect=RuntimeError('failure')) as bus:
            first = {}; second = {}
            m.unlock_sim(generic, first)
            m.unlock_sim(generic, second)
            bus.assert_called_once()
            self.assertEqual(first['pin_status'], 'unlock-failed')
            self.assertEqual(second['pin_status'], 'previous-attempt-failed')
            self.assertNotIn('1234', (Path(td)/'.failed-sim-pin.json').read_text())

    def test_rssi_unavailable_is_null(self):
        m = n.Manager()
        self.assertIsNone(m.request({'command': 'rssi', 'kind': 'eth'})['rssi_dbm'])


class ProfileTests(unittest.TestCase):
    def setUp(self):
        try:
            self.GLib, self.NM = n.bindings()
        except (ImportError, ValueError):
            self.skipTest('libnm introspection is required for real profile validation')

    def connections(self, config):
        result = {}
        for name, text, kind in n.profiles(n.validate(config)).values():
            keyfile = self.GLib.KeyFile(); keyfile.load_from_data(text, len(text.encode()), self.GLib.KeyFileFlags.NONE)
            conn = self.NM.keyfile_read(keyfile, '/', self.NM.KeyfileHandlerFlags.NONE, None, None)
            conn.verify()
            result[kind] = conn
        return result

    def test_real_nm_profiles_and_escaping(self):
        ssid = ' café; test '
        password = 'pass;word \\ with spaces '
        c = self.connections({'wifi': {'networks': [{'ssid': ssid, 'password': password}]},
                              'cellular': {'apn': 'internet', 'username': 'user', 'password': password, 'sim_pin': '1234'}})
        self.assertEqual(bytes(c['wifi'].get_setting_wireless().get_ssid().get_data()), ssid.encode())
        self.assertEqual(c['wifi'].get_setting_wireless_security().get_psk(), password)
        self.assertEqual(c['cellular'].get_setting_gsm().get_password(), password)
        self.assertIsNone(c['cellular'].get_setting_gsm().get_pin())
        self.assertIsNone(c['cellular'].get_setting_connection().get_interface_name())
        self.assertFalse(c['cellular'].get_setting_gsm().get_home_only())
        self.assertEqual(c['eth'].get_setting_ip4_config().get_dns_search(0), '~.')
        self.assertEqual(c['eth'].get_setting_ip6_config().get_method(), 'disabled')

    def test_disabled_links_produce_no_profiles(self):
        self.assertEqual(self.connections({k: {'enabled': False} for k in n.KINDS}), {})

    def test_apn_auto_config_and_roaming(self):
        c = self.connections({'cellular': {'allow_roaming': True}})['cellular'].get_setting_gsm()
        self.assertTrue(c.get_auto_config()); self.assertFalse(c.get_home_only())

    def test_explicit_apn_overrides_database(self):
        connection = self.connections({'cellular': {'apn': 'private.example',
                                       'username': 'carrier-user', 'password': 'carrier-password'}})['cellular']
        gsm = connection.get_setting_gsm()
        self.assertFalse(gsm.get_auto_config())
        self.assertEqual(gsm.get_apn(), 'private.example')
        self.assertEqual(gsm.get_username(), 'carrier-user')
        self.assertEqual(gsm.get_password(), 'carrier-password')
        self.assertTrue(connection.get_setting_connection().get_autoconnect())

    def test_missing_or_empty_apn_is_unset_for_database_lookup(self):
        for cellular in ({}, {'apn': ''}):
            gsm = self.connections({'cellular': cellular})['cellular'].get_setting_gsm()
            self.assertTrue(gsm.get_auto_config())
            self.assertIsNone(gsm.get_apn())
            self.assertFalse(gsm.get_home_only())

    def test_explicit_home_only_is_preserved(self):
        gsm = self.connections({'cellular': {'allow_roaming': False}})['cellular'].get_setting_gsm()
        self.assertTrue(gsm.get_home_only())

    def test_failed_profile_load_restores_previous_files(self):
        m = n.Manager()
        with tempfile.TemporaryDirectory() as td, patch.object(n, 'PROFILES', Path(td)), patch.object(n, 'command', side_effect=RuntimeError('failed')):
            old = Path(td)/'widelapse-eth.nmconnection'; old.write_text('old profile')
            with self.assertRaises(RuntimeError):
                m.apply(n.validate({}), 'test')
            self.assertEqual(old.read_text(), 'old profile')
            self.assertFalse((Path(td)/'widelapse-cellular.nmconnection').exists())
            self.assertIsNone(m.cfg)


if __name__ == '__main__':
    unittest.main()
