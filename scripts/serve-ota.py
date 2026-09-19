#!/usr/bin/env python3
"""Development-only HTTPS file server; exposes only the ignored ota directory."""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
from pathlib import Path
import ssl
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('address', help='Laptop IPv4 address reachable from the board')
parser.add_argument('--port', type=int, default=8443)
args = parser.parse_args()
address = str(ipaddress.IPv4Address(args.address))
root = Path(__file__).resolve().parents[1]
directory = root / 'ota'
if not directory.is_dir():
    parser.error('Create a bundle in ota/ first')
tls = root / 'secrets' / ('ota-tls-' + address)
tls.mkdir(parents=True, exist_ok=True, mode=0o700)
cert, key = tls / 'server.crt', tls / 'server.key'
if cert.exists() != key.exists():
    parser.error('Incomplete TLS key/certificate pair; restore it before serving')
if not cert.exists():
    subprocess.run([
        'openssl', 'req', '-x509', '-newkey', 'rsa:3072', '-nodes', '-days', '30',
        '-keyout', str(key), '-out', str(cert), '-subj', '/CN=Widelapse LAN OTA',
        '-addext', 'subjectAltName=IP:' + address,
        '-addext', 'basicConstraints=critical,CA:TRUE',
        '-addext', 'keyUsage=critical,digitalSignature,keyEncipherment,keyCertSign',
        '-addext', 'extendedKeyUsage=serverAuth',
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    key.chmod(0o600)
    cert.chmod(0o644)
context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
context.load_cert_chain(certfile=cert, keyfile=key)
handler = partial(SimpleHTTPRequestHandler, directory=str(directory))
with ThreadingHTTPServer((address, args.port), handler) as server:
    server.socket = context.wrap_socket(server.socket, server_side=True)
    print(f'Serving {directory} at https://{address}:{args.port}', flush=True)
    print(f'Copy this PUBLIC certificate to the board: {cert}', flush=True)
    print('Development server, no client authentication. Ctrl-C stops it.', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
