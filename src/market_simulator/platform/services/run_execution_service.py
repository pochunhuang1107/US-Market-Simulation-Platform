from market_simulator.platform.services.run_dispatcher_service import RunDispatcherService
from market_simulator.platform.services.run_worker_service import (
    RunWorkerService,
    build_worker_id,
)


_dispatcher = RunDispatcherService()
_worker = RunWorkerService()


def dispatch_run(db, run_id: str):
    return _dispatcher.dispatch_run(db, run_id)


def execute_claimed_run(db, run_id: str, *, lease_seconds: int = 300):
    return _worker.execute_claimed_run(db, run_id, lease_seconds=lease_seconds)


def claim_and_execute_next_run(db, *, worker_id: str, lease_seconds: int = 300):
    return _worker.claim_and_execute_next_run(
        db,
        worker_id=worker_id,
        lease_seconds=lease_seconds,
    )


def recover_stale_runs(db):
    return _worker.recover_stale_runs(db)