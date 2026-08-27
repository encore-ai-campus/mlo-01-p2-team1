"""Foreground WSL runner for collect, promote, verify, and source-clock wait."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import signal
import sys
from threading import Event
from typing import Callable

from .config import PRODUCTION_COLLECTION, Settings
from .logging_config import StructuredRunLogger
from .main import RunResult, run_once
from .models import ValidationReport
from .mongo_storage import MongoStorage
from .promotion import (
    ProductionPromoter,
    PromotionResult,
    validate_promotion_candidate,
)
from .scheduler import NextRunSchedule


class ServiceCycleError(RuntimeError):
    """One service cycle failed and the process must exit non-zero."""


class GracefulStop(RuntimeError):
    """SIGTERM requested a stop at a safe boundary."""


@dataclass(frozen=True, slots=True)
class ServiceCycleResult:
    run_id: str
    row_count: int
    run_dir: Path
    schedule: NextRunSchedule
    promotion: PromotionResult


def wait_seconds_until(
    schedule: NextRunSchedule, *, now: datetime | None = None
) -> float:
    current = now or datetime.now().astimezone()
    if current.tzinfo is None:
        raise ValueError("now must include a timezone")
    return max(
        0.0,
        schedule.local_run_time.timestamp() - current.timestamp(),
    )


def _verify_ready(storage: MongoStorage, *, run_id: str) -> None:
    ready = storage.runs.find_one({"run_id": run_id, "state": "ready"})
    if not ready:
        raise ServiceCycleError("promoted run is not READY")
    production_run_ids = storage.database[PRODUCTION_COLLECTION].distinct(
        "_ingest.run_id"
    )
    if production_run_ids != [run_id]:
        raise ServiceCycleError("READY run_id does not match production")


def run_cycle(
    settings: Settings,
    *,
    project_root: Path,
    stop_event: Event | None = None,
    collect: Callable[[Settings], RunResult] = run_once,
) -> ServiceCycleResult:
    collected = collect(settings)
    logger = StructuredRunLogger(
        log_root=settings.log_root,
        run_id=collected.run_id,
        source_name=settings.source_name,
    )
    if stop_event is not None and stop_event.is_set():
        logger.event(
            stage="service",
            event="stop_at_post_collection_boundary",
            status="success",
            row_count=collected.row_count,
        )
        raise GracefulStop("stop requested after collection")

    storage = MongoStorage(settings)
    try:
        storage.ping()
        candidate: ValidationReport = validate_promotion_candidate(
            storage,
            run_id=collected.run_id,
            run_dir=collected.data_path,
            project_root=project_root,
        )
        if not candidate.passed:
            raise ServiceCycleError("candidate validation failed")
        logger.event(
            stage="service_promotion",
            event="candidate_validation_passed",
            status="success",
            row_count=collected.row_count,
        )
        promotion = ProductionPromoter(
            storage, state_root=settings.state_root
        ).promote_ready_to_ready(
            run_id=collected.run_id,
            source_name=settings.source_name,
            expected_rows=collected.row_count,
            candidate_report=candidate,
            promotion_time=datetime.now().astimezone(),
        )
        if not promotion.post_validation.passed:
            raise ServiceCycleError("production post-validation failed")
        _verify_ready(storage, run_id=collected.run_id)
        logger.event(
            stage="service_complete",
            event="run_promoted_ready",
            status="success",
            row_count=collected.row_count,
            next_source_time=collected.next_schedule.source_target_time.isoformat(),
            next_local_time=collected.next_schedule.local_run_time.isoformat(),
        )
        return ServiceCycleResult(
            run_id=collected.run_id,
            row_count=collected.row_count,
            run_dir=collected.data_path,
            schedule=collected.next_schedule,
            promotion=promotion,
        )
    except GracefulStop:
        raise
    except Exception as exc:
        logger.event(
            stage="service",
            event="cycle_failed",
            status="error",
            error=type(exc).__name__,
        )
        raise ServiceCycleError("service cycle failed") from exc
    finally:
        storage.close()


def run_service(
    settings: Settings,
    *,
    project_root: Path,
    once: bool,
    stop_event: Event,
    cycle: Callable[..., ServiceCycleResult] = run_cycle,
) -> int:
    while not stop_event.is_set():
        try:
            result = cycle(
                settings,
                project_root=project_root,
                stop_event=stop_event,
            )
        except GracefulStop:
            return 0
        print(
            f"cycle_ready run_id={result.run_id} rows={result.row_count} "
            f"next_local_time={result.schedule.local_run_time.isoformat()}"
        )
        if once or stop_event.is_set():
            return 0
        delay = wait_seconds_until(result.schedule)
        if stop_event.wait(delay):
            return 0
    return 0


def _install_signal_handlers(stop_event: Event) -> None:
    def request_stop(signum: int, frame: object) -> None:
        del signum, frame
        stop_event.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Continuously collect and promote READY Bronze snapshots"
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="collect, promote, verify READY, then exit",
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
        help="project root used to resolve relative manifest artifact paths",
    )
    args = parser.parse_args()
    stop_event = Event()
    _install_signal_handlers(stop_event)
    try:
        return run_service(
            Settings.from_env(),
            project_root=args.project_root.resolve(),
            once=args.once,
            stop_event=stop_event,
        )
    except Exception as exc:
        print(f"service failed: {type(exc).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
