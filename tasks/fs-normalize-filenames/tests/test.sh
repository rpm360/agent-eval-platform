#!/usr/bin/env bash
set -euo pipefail

python3 - <<'PY'
from pathlib import Path
d = Path("/workspace/docs")
assert d.is_dir(), "docs/ directory missing"
expected = {
    "annual_report_2025.txt": "Revenue grew 12% year over year.\n",
    "meeting_notes.txt": "Discussed Q2 hiring plan.\n",
    "q1_budget_final.txt": "Total budget: 1.2M\n",
    "data_export.csv": "id,value\n1,42\n",
}
names = {p.name for p in d.iterdir() if p.is_file()}
assert names == set(expected), f"Expected files {sorted(expected)}, got {sorted(names)}"
for name, content in expected.items():
    got = (d / name).read_text()
    assert got == content, f"Content of {name} changed: {got!r}"
print("PASS:", sorted(names))
PY
