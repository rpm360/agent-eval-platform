#!/usr/bin/env bash
set -euo pipefail

python3 - <<'PY'
import re
from pathlib import Path

p = Path("/workspace/TAG.txt")
assert p.exists(), "TAG.txt not found"
val = p.read_text().strip()
assert re.fullmatch(r"aep-rel-20260305-a1b2c3", val), f"Unexpected tag: {val!r}"
print("PASS:", val)
PY
