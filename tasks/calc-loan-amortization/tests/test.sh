#!/usr/bin/env bash
set -euo pipefail

python3 - <<'PY'
from pathlib import Path
p = Path("/workspace/payment.txt")
assert p.exists(), "payment.txt not found"
val = float(p.read_text().strip().replace("$", "").replace(",", ""))
expected = 1498.88
assert abs(val - expected) <= 0.01, f"Expected {expected}, got {val}"
print("PASS:", val)
PY
