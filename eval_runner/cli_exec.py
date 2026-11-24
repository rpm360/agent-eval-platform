"""Unified subcommand entrypoint (`python -m eval_runner.cli_exec <run|retry|calibrate>`) for the TS API."""

from __future__ import annotations

import sys
from collections.abc import Callable

from eval_runner.cli import calibrate_cmd, retry_cmd, run_cmd
from eval_runner.constants import INFRA_ERROR_EXIT_CODE

SUBCOMMANDS: dict[str, Callable[[], None]] = {
    "run": run_cmd,
    "retry": retry_cmd,
    "calibrate": calibrate_cmd,
}


def main() -> None:
    """Dispatch `eval_runner.cli_exec <subcommand>` to the corresponding Typer CLI command."""
    if len(sys.argv) < 2 or sys.argv[1] not in SUBCOMMANDS:
        valid_choices = "|".join(SUBCOMMANDS)
        sys.stderr.write(f"Usage: python -m eval_runner.cli_exec <{valid_choices}> [args]\n")
        raise SystemExit(INFRA_ERROR_EXIT_CODE)
    subcommand = sys.argv[1]
    sys.argv = [f"eval-{subcommand}", *sys.argv[2:]]
    SUBCOMMANDS[subcommand]()


if __name__ == "__main__":
    main()
