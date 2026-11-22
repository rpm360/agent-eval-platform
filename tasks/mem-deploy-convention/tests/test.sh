#!/usr/bin/env bash
set -euo pipefail

python3 - <<'PY'
import re
from pathlib import Path

p = Path("/workspace/DEPLOY_TARGET.txt")
assert p.exists(), "DEPLOY_TARGET.txt not found"
val = p.read_text().strip()
assert re.fullmatch(r"prod-eu-west-payments-v2", val), f"Unexpected target: {val!r}"
print("PASS:", val)
PY
