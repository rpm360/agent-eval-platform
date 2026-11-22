#!/usr/bin/env bash
set -euo pipefail

python3 - <<'PY'
import sqlite3
from pathlib import Path
p = Path("/workspace/schema.sql")
assert p.exists(), "schema.sql not found"
sql = p.read_text()
con = sqlite3.connect(":memory:")
con.executescript(sql)
tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
assert tables == ["tbl_crm__customers"], f"Unexpected tables: {tables}"
cols = {r[1]: (r[2].upper(), r[3]) for r in con.execute("PRAGMA table_info(tbl_crm__customers)")}
assert "id" in cols and "name" in cols, f"Missing id/name: {cols}"
assert "created_at" in cols, f"Missing created_at audit column: {cols}"
assert cols["created_at"][0] == "TIMESTAMP" and cols["created_at"][1] == 1, "created_at must be TIMESTAMP NOT NULL"
print("PASS:", tables, cols)
PY
