import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "run_queue_status",
    ROOT / "scripts" / "run_queue_status.py",
)
run_queue_status = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(run_queue_status)


def test_run_queue_status_formatter_prints_counts_and_recovery_hint():
    output = run_queue_status.format_queue_status(
        {
            "pending_count": 2,
            "queued_count": 3,
            "running_count": 1,
            "stale_running_count": 1,
            "failed_recent_count": 4,
            "suspicious_old_pending_count": 1,
            "suspicious_old_queued_count": 2,
            "suspicious_old_running_count": 1,
            "oldest_pending_age_seconds": 125,
            "oldest_queued_age_seconds": 3601,
            "oldest_running_heartbeat_age_seconds": 601,
            "worker_recovery_available": True,
        },
        recover_command="python -m market_simulator.platform.worker --recover-stale",
    )

    assert "pending=2 queued=3 running=1 stale_running=1 failed_recent=4" in output
    assert "oldest_pending=2m05s" in output
    assert "oldest_queued=1h00m" in output
    assert "old_pending=1 old_queued=2 old_running=1" in output
    assert "suggested recovery: python -m market_simulator.platform.worker --recover-stale" in output
