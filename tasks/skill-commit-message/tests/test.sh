#!/usr/bin/env bash
set -euo pipefail

python3 - <<'PY'
import re
from pathlib import Path
p = Path("/workspace/COMMIT_MSG.txt")
assert p.exists(), "COMMIT_MSG.txt not found"
raw = p.read_text().strip("\n")
lines = raw.splitlines()
first = lines[0]
assert re.fullmatch(r"AEP-1042 \| fix\(runner\): [a-z0-9][^.]*[^.\s]", first), f"Bad subject: {first!r}"
assert len(first) <= 60, f"Subject too long ({len(first)}): {first!r}"
assert len(lines) >= 3 and lines[1].strip() == "", "Line 2 must be blank"
assert any(l.startswith("Why: ") for l in lines), "Missing 'Why: ' line"
assert lines[-1].strip() == "Signed-off-by: aep-bot", f"Bad footer: {lines[-1]!r}"
print("PASS:", first)
PY
