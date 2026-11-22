#!/usr/bin/env bash
set -euo pipefail

python3 - <<'PY'
from pathlib import Path
p = Path("/workspace/CHANGELOG.md")
assert p.exists(), "CHANGELOG.md not found"
lines = [l.strip() for l in p.read_text().splitlines() if l.strip()]
required = [
    "## Release 2.4.0 (05.03.2026)",
    "#### Added",
    "- [AEP-799] CSV export for trials (@jon)",
    "#### Fixed",
    "- [AEP-812] Retry loop on 429 responses (@mira)",
]
idx = []
for r in required:
    assert r in lines, f"Missing line: {r!r}\nGot: {lines}"
    idx.append(lines.index(r))
assert idx == sorted(idx), f"Lines out of order: {lines}"
print("PASS")
PY
