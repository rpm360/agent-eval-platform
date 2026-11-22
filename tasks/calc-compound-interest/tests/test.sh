#!/usr/bin/env bash
set -euo pipefail

python3 - <<'PY'
from pathlib import Path
p = Path("/workspace/answer.txt")
assert p.exists(), "answer.txt not found"
val = float(p.read_text().strip().replace("$", "").replace(",", ""))
expected = 16288.95
assert abs(val - expected) <= 0.01, f"Expected {expected}, got {val}"
print("PASS:", val)
PY
