from __future__ import annotations


class RetryableRunError(Exception):
    pass


class NonRetryableRunError(Exception):
    pass


def classify_run_exception(exc: Exception) -> tuple[bool, str]:
    message = str(exc).lower()
    exc_type = exc.__class__.__name__

    non_retryable_markers = [
        "strategy version not found",
        "does not have strategy_version_id",
        "unsupported executor_type",
        "invalid config",
        "validation error",
        "jsonschema",
        "pydantic",
        "keyerror",
        "valueerror",
        "typeerror",
    ]

    retryable_markers = [
        "timeout",
        "temporarily unavailable",
        "temporary failure",
        "connection reset",
        "connection aborted",
        "could not connect",
        "database is locked",
        "broken pipe",
        "i/o error",
        "io error",
        "duckdb",
        "http error",
        "503",
        "502",
        "504",
        "too many requests",
        "rate limit",
        "network",
        "transport",
    ]

    if exc_type in {"NonRetryableRunError"}:
        return False, "NON_RETRYABLE"

    if exc_type in {"RetryableRunError"}:
        return True, "RETRYABLE"

    if any(marker in message for marker in non_retryable_markers):
        return False, "NON_RETRYABLE"

    if any(marker in message for marker in retryable_markers):
        return True, "RETRYABLE"

    return False, "NON_RETRYABLE"