#!/usr/bin/env python3
"""Development-only HTTP file server; exposes only the ignored ota directory."""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('address', help='Laptop IPv4 address reachable from the board')
parser.add_argument('--port', type=int, default=8000)
args = parser.parse_args()
address = str(ipaddress.IPv4Address(args.address))
root = Path(__file__).resolve().parents[1]
directory = root / 'ota'
if not directory.is_dir():
    parser.error('Create a bundle in ota/ first')
handler = partial(SimpleHTTPRequestHandler, directory=str(directory))
with ThreadingHTTPServer((address, args.port), handler) as server:
    print(f'Serving {directory} at http://{address}:{args.port}', flush=True)
    print('Development server, no client authentication. Ctrl-C stops it.', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
