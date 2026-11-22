#!/usr/bin/env bash
set -euo pipefail

python3 - <<'PY'
import json
from pathlib import Path
p = Path("/workspace/active_users.json")
assert p.exists(), "active_users.json not found"
data = json.loads(p.read_text())
expected = [
    {"id": 6, "name": "Fay"},
    {"id": 3, "name": "Cara"},
    {"id": 4, "name": "Dev"},
    {"id": 1, "name": "Ava"},
]
assert data == expected, f"Expected {expected}, got {data}"
print("PASS:", data)
PY
