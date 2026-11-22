"""Unified subcommand entrypoint (`python -m eval_runner.cli_exec <run|retry|calibrate>`) for the TS API."""

from __future__ import annotations

import sys

from eval_runner.cli import calibrate_cmd, retry_cmd, run_cmd

SUBCOMMANDS = {
    "run": run_cmd,
    "retry": retry_cmd,
    "calibrate": calibrate_cmd,
}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in SUBCOMMANDS:
        print(f"Usage: python -m eval_runner.cli_exec <{'|'.join(SUBCOMMANDS)}> [args]", file=sys.stderr)
        raise SystemExit(2)
    cmd = sys.argv[1]
    sys.argv = [f"eval-{cmd}", *sys.argv[2:]]
    SUBCOMMANDS[cmd]()
