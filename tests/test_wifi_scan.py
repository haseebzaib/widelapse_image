"""Scan behavior without touching hardware or changing connections."""
import json
import unittest
from unittest.mock import MagicMock, patch
from test_network import n


class WifiScanTests(unittest.TestCase):
    def setUp(self):
        self.manager = n.Manager()
        self.manager.cfg = n.validate({})
        self.nm = MagicMock()
        self.device = MagicMock()
        self.device.get_device_type.return_value = self.nm.DeviceType.WIFI
        self.client = MagicMock()
        self.client.get_device_by_iface.return_value = self.device
        self.device.get_last_scan.side_effect = [10, 11]
        self.device.get_access_points.return_value = []
        self.device.get_active_access_point.return_value = None
        self.device.request_scan_finish.return_value = True
        self.device.request_scan_async.side_effect = lambda cancel, cb, data: cb(self.device, object(), data)
        self.binding = patch.object(n, 'bindings', return_value=(None, self.nm))
        self.binding.start(); self.addCleanup(self.binding.stop)
        self.reader = patch.object(self.manager, 'network_client', return_value=self.client)
        self.reader.start(); self.addCleanup(self.reader.stop)

    def ap(self, raw, bssid, strength, wpa=0, rsn=0, flags=0):
        ap = MagicMock()
        ap.get_ssid.return_value.get_data.return_value = raw
        ap.get_bssid.return_value = bssid
        ap.get_strength.return_value = strength
        ap.get_frequency.return_value = 2412
        ap.get_flags.return_value = flags
        ap.get_wpa_flags.return_value = wpa
        ap.get_rsn_flags.return_value = rsn
        ap.get_path.return_value = '/ap/' + bssid
        return ap

    def test_json_preserves_names_and_duplicate_ssids_sorted_by_strength(self):
        raw = 'Cafe: WiFi\\ "雪"\n'.encode()
        weak = self.ap(raw, 'AA:01', 20)
        strong = self.ap(raw, 'AA:02', 90, rsn=256, flags=1)
        self.device.get_access_points.return_value = [weak, strong]
        self.device.get_active_access_point.return_value = strong
        result = json.loads(json.dumps(self.manager.request({'command': 'wifi-scan'})))
        self.assertTrue(result['ok'])
        rows = result['networks']
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['ssid'], raw.decode())
        self.assertTrue(rows[0]['connected'])
        self.assertFalse(rows[1]['connected'])
        self.assertEqual(rows[0]['security'], 'RSN')
        self.assertEqual(rows[1]['security'], 'OPEN')
        self.assertEqual(rows[0]['ssid_hex'], raw.hex())

    def test_hidden_and_non_utf8_names(self):
        hidden = self.ap(b'', 'AA:01', 1)
        hidden.get_ssid.return_value = None
        invalid = self.ap(b'\xff', 'AA:02', 2)
        self.device.get_access_points.return_value = [hidden, invalid]
        rows = self.manager.wifi_scan()['networks']
        self.assertEqual(rows[0]['ssid_hex'], 'ff')
        self.assertTrue(rows[1]['hidden'])
        self.assertEqual(rows[1]['ssid'], '')

    def test_empty_scan_is_success(self):
        self.assertEqual(self.manager.wifi_scan()['networks'], [])

    def test_disabled_does_not_scan_or_enable_radio(self):
        self.manager.cfg['wifi']['enabled'] = False
        self.assertEqual(self.manager.wifi_scan()['error'], 'wifi-disabled')
        self.device.request_scan_async.assert_not_called()

    def test_missing_interface(self):
        self.client.get_device_by_iface.return_value = None
        self.assertEqual(self.manager.wifi_scan()['error'], 'wifi-interface-unavailable')

    def test_radio_blocked(self):
        self.client.wireless_hardware_get_enabled.return_value = False
        self.assertEqual(self.manager.wifi_scan()['error'], 'wifi-radio-disabled')
        self.device.request_scan_async.assert_not_called()

    def test_rejection_is_not_reported_as_empty_success(self):
        self.device.request_scan_finish.side_effect = RuntimeError('busy')
        self.assertEqual(self.manager.wifi_scan()['error'], 'wifi-scan-rejected')

    def test_acceptance_alone_is_not_completion(self):
        self.device.get_last_scan.side_effect = None
        self.device.get_last_scan.return_value = 10
        with patch.object(n.time, 'monotonic', side_effect=[0, 1, 16]), patch.object(n.time, 'sleep'):
            result = self.manager.wifi_scan()
        self.assertEqual(result['error'], 'wifi-scan-timeout')
        self.device.get_access_points.assert_not_called()
        cancel = self.device.request_scan_async.call_args.args[0]
        self.assertTrue(cancel.is_cancelled())

    def test_cli_sends_scan_request_and_prints_json(self):
        endpoint = MagicMock()
        endpoint.recv.return_value = b'{"ok":true,"networks":[]}\n'
        with patch.object(n.sys, 'argv', ['widelapse-network', '--wifi-scan']), patch.object(n.socket, 'socket') as sock, patch('builtins.print') as output:
            sock.return_value.__enter__.return_value = endpoint
            n.main()
        request = json.loads(endpoint.sendall.call_args.args[0])
        self.assertEqual(request['command'], 'wifi-scan')
        self.assertEqual(json.loads(output.call_args.args[0]), {'ok': True, 'networks': []})
