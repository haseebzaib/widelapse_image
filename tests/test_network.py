"""Offline policy/profile tests: never touch host interfaces, D-Bus or credentials."""
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock

PATH = Path(__file__).resolve().parents[1] / 'userpatches/network/widelapse-network'
loader = importlib.machinery.SourceFileLoader('widelapse_network', str(PATH))
spec = importlib.util.spec_from_loader(loader.name, loader)
n = importlib.util.module_from_spec(spec)
loader.exec_module(n)


class ConfigTests(unittest.TestCase):
    def test_missing_config_enables_all_and_requires_no_wifi_credentials(self):
        with tempfile.TemporaryDirectory() as td:
            cfg, source = n.read_config(Path(td)/'absent')
        self.assertEqual(source, 'defaults')
        self.assertTrue(all(cfg[k]['enabled'] for k in n.KINDS))
        self.assertEqual(cfg['wifi']['networks'], [])
        self.assertTrue(cfg['cellular']['allow_roaming'])

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
        m = n.Manager(); m.cfg = n.validate({})
        rows = {k: {'connected': k == 'eth', 'interface': 'end0' if k == 'eth' else None,
                    'control_interface': 'end0', 'uuid': 'test'} for k in n.KINDS}
        with patch.object(m, 'links', return_value=rows), patch.object(m, 'modem', return_value={}), patch.object(n, 'probe', return_value=True), patch.object(n, 'command', side_effect=RuntimeError('failed')):
            m.tick()
        self.assertFalse(m.status['routing_applied'])
        self.assertEqual(m.status['route_errors'], ['eth'])
        self.assertNotIn('eth', m.applied)


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
