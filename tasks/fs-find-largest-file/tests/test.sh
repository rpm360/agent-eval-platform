#!/usr/bin/env bash
set -euo pipefail

python3 - <<'PY'
from pathlib import Path
p = Path("/workspace/LARGEST.txt")
assert p.exists(), "LARGEST.txt not found"
val = p.read_text().strip().removeprefix("/workspace/").removeprefix("./")
assert val == "project/.cache/build.log", f"Unexpected path: {val!r}"
print("PASS:", val)
PY
