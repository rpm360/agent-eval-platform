#!/usr/bin/env bash
set -euo pipefail

python3 - <<'PY'
from pathlib import Path
p = Path("/workspace/request.sh")
assert p.exists(), "request.sh not found"
cmd = p.read_text()
assert "curl" in cmd, "Not a curl command"
assert "https://api.internal.aep.dev/v3/orders/42" in cmd, "Wrong base URL / path"
assert "X-AEP-Api: 2026-01-preview" in cmd, "Missing required version header"
print("PASS:", cmd.strip())
PY
