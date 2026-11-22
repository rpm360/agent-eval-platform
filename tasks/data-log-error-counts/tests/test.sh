#!/usr/bin/env bash
set -euo pipefail

python3 - <<'PY'
import json
from pathlib import Path
p = Path("/workspace/errors.json")
assert p.exists(), "errors.json not found"
data = {k: int(v) for k, v in json.loads(p.read_text()).items()}
expected = {"auth": 3, "billing": 2, "search": 1}
assert data == expected, f"Expected {expected}, got {data}"
print("PASS:", data)
PY
