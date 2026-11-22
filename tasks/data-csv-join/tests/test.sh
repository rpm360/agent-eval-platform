#!/usr/bin/env bash
set -euo pipefail

python3 - <<'PY'
import csv
from pathlib import Path
p = Path("/workspace/report.csv")
assert p.exists(), "report.csv not found"
with p.open(newline="") as f:
    reader = csv.DictReader(f)
    assert reader.fieldnames == ["country", "total_amount"], f"Bad header: {reader.fieldnames}"
    rows = [(r["country"].strip(), float(r["total_amount"])) for r in reader]
expected = [("FR", 200.00), ("US", 170.75), ("DE", 99.99)]
assert len(rows) == len(expected), f"Expected {len(expected)} rows, got {rows}"
for (c, v), (ec, ev) in zip(rows, expected):
    assert c == ec and abs(v - ev) <= 0.01, f"Expected {expected}, got {rows}"
print("PASS:", rows)
PY
