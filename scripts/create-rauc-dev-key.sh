#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
key=secrets/rauc-dev.key.pem
cert=userpatches/overlay/rauc-keyring.pem
[[ ! -e $key && ! -e $cert ]] || { echo 'Key or certificate already exists; refusing to replace trust.' >&2; exit 1; }
umask 077
mkdir -p secrets userpatches/overlay
openssl req -x509 -newkey rsa:3072 -sha256 -nodes -days 3650 \
    -subj '/CN=Widelapse development OTA/' \
    -addext 'basicConstraints=critical,CA:TRUE' \
    -addext 'keyUsage=critical,digitalSignature,keyCertSign,cRLSign' \
    -keyout "$key" -out "$cert"
chmod 644 "$cert"
echo 'Development signing key created in ignored secrets/. Back it up securely.'
