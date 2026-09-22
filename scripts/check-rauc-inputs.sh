#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
for file in authorized_keys root-password.hash rauc-keyring.pem; do
    test -s "userpatches/overlay/$file" || {
        echo "Missing userpatches/overlay/$file. See docs/RAUC.md." >&2
        exit 1
    }
done
ssh-keygen -l -f userpatches/overlay/authorized_keys >/dev/null
openssl x509 -in userpatches/overlay/rauc-keyring.pem -noout -checkend 0 >/dev/null
# Never print credential contents.
python3 - <<'PY'
from pathlib import Path
import re
value=Path('userpatches/overlay/root-password.hash').read_text().strip()
if not re.fullmatch(r'\$6\$(?:rounds=\d+\$)?[^$\s]{1,16}\$[./0-9A-Za-z]{86}',value):
    raise SystemExit('Invalid SHA-512 root password hash')
PY
bash -n userpatches/config-widelapse.conf
bash -n userpatches/customize-image.sh
bash -n userpatches/extensions/widelapse-rauc.sh

# Check custom installers and the networking daemon before starting a build.
bash -n userpatches/device-setup/install.sh
bash -n userpatches/rauc/install.sh
bash -n userpatches/network/install.sh
python3 - <<'PYTHON'
import ast
from pathlib import Path
ast.parse(Path('userpatches/network/widelapse-network').read_text())
PYTHON
