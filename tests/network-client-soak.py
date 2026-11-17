#!/usr/bin/env python3
"""Read-only live libnm descriptor test. Requires python3-gi, libnm and D-Bus.

Run: python3 tests/network-client-soak.py
Does not activate connections or change host networking.
"""
import os
from pathlib import Path
import runpy

module = runpy.run_path(str(Path(__file__).resolve().parents[1] /
                           'userpatches/network/widelapse-network'))
manager = module['Manager']()
client = manager.network_client()
if not client.get_nm_running():
    raise SystemExit('Run with NetworkManager active to exercise the original leak')
GLib, _ = module['bindings']()

def descriptors():
    return len(os.listdir('/proc/self/fd'))

# Warm up lazy library allocations before measuring.
for _ in range(100):
    manager.network_client().get_devices()
baseline = descriptors()
peak = baseline
callbacks = []
for i in range(10000):
    if i % 100 == 0:
        source = GLib.idle_source_new()
        source.set_callback(lambda unused: (callbacks.append(True), False)[1])
        source.attach(client.get_main_context())
    assert manager.network_client() is client
    client.get_devices()
    if i % 100 == 0:
        peak = max(peak, descriptors())
        assert peak <= baseline + 2, (baseline, peak, i)
assert len(callbacks) == 100, 'GLib events were not dispatched'
print(f'PASS: 10000 snapshots, descriptors baseline={baseline}, peak={peak}, '
      f'final={descriptors()}; 100 GLib callbacks dispatched')
