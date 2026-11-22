#!/usr/bin/env bash
set -euo pipefail

python3 - <<'PY'
import json
from pathlib import Path

p = Path("/workspace/summary.json")
assert p.exists(), "summary.json not found"
data = json.loads(p.read_text())
expected = {"north": 200.0, "south": 100.0, "east": 300.0}
for k, v in expected.items():
    assert k in data, f"Missing region {k}"
    assert abs(float(data[k]) - v) <= 0.01, f"Region {k}: expected {v}, got {data[k]}"
print("PASS:", data)
PY
