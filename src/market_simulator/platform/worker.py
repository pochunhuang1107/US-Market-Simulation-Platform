from __future__ import annotations

import argparse
import logging
import time

from market_simulator.db.session import SessionLocal
from market_simulator.platform.services.run_worker_service import (
    RunWorkerService,
    build_worker_id,
)


def configure_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def run_worker(
    *,
    worker_id: str,
    poll_seconds: float,
    lease_seconds: int,
    recover_stale: bool,
):
    service = RunWorkerService()
    logger = logging.getLogger(__name__)
    logger.info("starting worker | %s", {"worker_id": worker_id})

    while True:
        db = SessionLocal()
        try:
            if recover_stale:
                recovered = service.recover_stale_runs(db)
                if recovered["recovered_count"] > 0:
                    logger.info(
                        "recovered stale runs | %s",
                        {
                            "worker_id": worker_id,
                            "recovered_count": recovered["recovered_count"],
                            "run_ids": recovered["run_ids"],
                        },
                    )

            result = service.claim_and_execute_next_run(
                db,
                worker_id=worker_id,
                lease_seconds=lease_seconds,
            )

            if result is None:
                time.sleep(poll_seconds)
                continue

            logger.info(
                "completed run | %s",
                {
                    "worker_id": worker_id,
                    "run_id": result["run_id"],
                    "status": result["status"],
                },
            )

        except KeyboardInterrupt:
            logger.info("stopping worker | %s", {"worker_id": worker_id})
            raise
        except Exception as exc:
            logger.exception(
                "worker loop error | %s",
                {
                    "worker_id": worker_id,
                    "error": str(exc),
                },
            )
            time.sleep(poll_seconds)
        finally:
            db.close()


def main():
    configure_logging()

    parser = argparse.ArgumentParser()
    parser.add_argument("--worker-id", default=None)
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--lease-seconds", type=int, default=300)
    parser.add_argument("--recover-stale", action="store_true")
    args = parser.parse_args()

    worker_id = args.worker_id or build_worker_id()

    run_worker(
        worker_id=worker_id,
        poll_seconds=args.poll_seconds,
        lease_seconds=args.lease_seconds,
        recover_stale=args.recover_stale,
    )


if __name__ == "__main__":
    main()