"""Shared domain constants and StrEnums for the evaluation runner."""

from __future__ import annotations

from enum import StrEnum


class TrialStatus(StrEnum):
    """Execution outcome status for an individual evaluation trial."""

    COMPLETED = "completed"
    INFRA_ERROR = "infra_error"


class GraderType(StrEnum):
    """Supported trial verification strategies."""

    DETERMINISTIC = "deterministic"
    LLM_JUDGE = "llm_judge"


class CalibrationVerdict(StrEnum):
    """Trust gate outcome when evaluating an LLM judge against human labels."""

    TRUSTED = "TRUSTED"
    UNTRUSTED = "UNTRUSTED"


# Wire-protocol prefix parsed by the Web UI SSE job log consumer (`web/src/App.tsx`).
TRIAL_STREAM_PREFIX = "[AEP_TRIAL]"

# Process / container exit codes
INFRA_ERROR_EXIT_CODE = 2
TIMEOUT_EXIT_CODES: frozenset[int] = frozenset({124, 137})

# Default runner & container limits
DEFAULT_CONCURRENCY = 2
DEFAULT_RANDOM_SEED = 42
DEFAULT_JUDGE_MODEL_ID = "gemini-flash"
DEFAULT_CALIBRATION_REPEATS = 3
DETERMINISTIC_GRADER_TIMEOUT_SEC = 120
CONTAINER_KILL_AFTER_SEC = 5
CONTAINER_WATCHDOG_GRACE_SEC = 15
MAX_CONTAINER_ARCHIVE_BYTES = 20 * 1024 * 1024  # 20 MB cap when pulling files from containers
TOKENS_PER_MILLION = 1_000_000.0

# Truncation & formatting caps
MAX_ARTIFACT_CHARS = 8000
MAX_STDIO_TAIL_CHARS = 2000
MAX_REWARD_REASONING_CHARS = 1000
HASH_HEX_PREFIX_LEN = 12
SLUG_ITEM_DISPLAY_LIMIT = 2

# Statistical power & failure classification thresholds
MIN_POWERED_SHARED_TASKS = 10
MIN_POWERED_TRIALS_PER_TASK = 3
HIGH_INFRA_ERROR_RATE_THRESHOLD = 0.10
SATURATED_SCORE_HIGH = 0.999
SATURATED_SCORE_LOW = 0.001
MAJORITY_PASS_SCORE_THRESHOLD = 0.5
BORDERLINE_SCORE_MARGIN = 0.1
LOOP_CONSECUTIVE_CALL_THRESHOLD = 3
MAX_FAILURE_EXAMPLES_PER_CATEGORY = 3

# Ordered column schema for CSV trial exports (mirrored by `api/src/server.ts`)
EXPORT_CSV_COLUMNS: tuple[str, ...] = (
    "trial_id",
    "config_name",
    "config_hash",
    "harness",
    "model",
    "task_id",
    "trial_index",
    "status",
    "score",
    "passed",
    "runtime_sec",
    "input_tokens",
    "output_tokens",
    "cost_usd",
    "steps",
    "failure_category",
    "error_message",
)
