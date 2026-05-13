from __future__ import annotations

import argparse
import json
from typing import Any

from market_simulator.db.session import SessionLocal
from market_simulator.repositories.runs import get_run_queue_health
from market_simulator.settings import get_settings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Print safe operator diagnostics for the run queue."
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the diagnostics payload as JSON.",
    )
    parser.add_argument(
        "--failed-recent-seconds",
        type=int,
        default=86400,
        help="Window used for failed_recent_count. Defaults to 24 hours.",
    )
    parser.add_argument(
        "--recover-command",
        default="python -m market_simulator.platform.worker --recover-stale",
        help="Command shown when stale recovery may be needed.",
    )
    return parser


def fetch_queue_status(*, failed_recent_seconds: int = 86400) -> dict[str, Any]:
    settings = get_settings()
    db = SessionLocal()
    try:
        return get_run_queue_health(
            db,
            running_stale_seconds=settings.running_stale_seconds,
            queue_oldest_warning_seconds=settings.queue_oldest_warning_seconds,
            failed_recent_seconds=failed_recent_seconds,
        )
    finally:
        db.close()


def format_queue_status(
    status: dict[str, Any],
    *,
    recover_command: str,
) -> str:
    lines = [
        "Run queue status",
        (
            "counts: "
            f"pending={status['pending_count']} "
            f"queued={status['queued_count']} "
            f"running={status['running_count']} "
            f"stale_running={status['stale_running_count']} "
            f"failed_recent={status['failed_recent_count']}"
        ),
        (
            "ages: "
            f"oldest_pending={_format_age(status.get('oldest_pending_age_seconds'))} "
            f"oldest_queued={_format_age(status.get('oldest_queued_age_seconds'))} "
            "oldest_running_heartbeat="
            f"{_format_age(status.get('oldest_running_heartbeat_age_seconds'))}"
        ),
        (
            "suspicious: "
            f"old_pending={status['suspicious_old_pending_count']} "
            f"old_queued={status['suspicious_old_queued_count']} "
            f"old_running={status['suspicious_old_running_count']}"
        ),
        (
            "recovery: available"
            if status.get("worker_recovery_available")
            else "recovery: unavailable"
        ),
    ]

    if status.get("stale_running_count", 0) > 0:
        lines.append(f"suggested recovery: {recover_command}")
    elif status.get("suspicious_old_queued_count", 0) > 0:
        lines.append("suggested action: confirm the worker process is running and claiming jobs")
    elif status.get("suspicious_old_pending_count", 0) > 0:
        lines.append("suggested action: check API enqueue logs for pending runs that never entered the queue")
    elif status.get("failed_recent_count", 0) > 0:
        lines.append("suggested action: inspect failed run details and worker logs")
    else:
        lines.append("suggested action: none")

    return "\n".join(lines)


def _format_age(value: int | None) -> str:
    if value is None:
        return "n/a"
    if value < 60:
        return f"{value}s"
    minutes, seconds = divmod(value, 60)
    if minutes < 60:
        return f"{minutes}m{seconds:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m"


def main() -> int:
    args = build_parser().parse_args()
    status = fetch_queue_status(failed_recent_seconds=args.failed_recent_seconds)
    if args.json:
        print(json.dumps(status, sort_keys=True))
    else:
        print(format_queue_status(status, recover_command=args.recover_command))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
