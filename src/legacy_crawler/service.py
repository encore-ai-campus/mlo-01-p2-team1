"""Foreground WSL runner for cursor continuation and page-run appends."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import signal
import sys
from threading import Event
from typing import Callable

from .append_pipeline import PageAppendResult, run_page_append_cycle
from .config import Settings
from .scheduler import NextRunSchedule


class ServiceCycleError(RuntimeError):
    """One service cycle failed and the process must exit non-zero."""


class GracefulStop(RuntimeError):
    """SIGTERM requested a stop at a safe boundary."""


ServiceCycleResult = PageAppendResult


def wait_seconds_until(
    schedule: NextRunSchedule, *, now: datetime | None = None
) -> float:
    current = now or datetime.now().astimezone()
    if current.tzinfo is None:
        raise ValueError("now must include a timezone")
    return max(0.0, schedule.local_run_time.timestamp() - current.timestamp())


def run_cycle(
    settings: Settings,
    *,
    project_root: Path,
    stop_event: Event | None = None,
    initialize: bool = False,
    collect: Callable[..., PageAppendResult] = run_page_append_cycle,
) -> PageAppendResult:
    del project_root
    if stop_event is not None and stop_event.is_set():
        raise GracefulStop("stop requested before collection")
    try:
        return collect(settings, initialize=initialize)
    except GracefulStop:
        raise
    except Exception as exc:
        raise ServiceCycleError("service cycle failed") from exc


def run_service(
    settings: Settings,
    *,
    project_root: Path,
    once: bool,
    initialize: bool,
    stop_event: Event,
    cycle: Callable[..., PageAppendResult] = run_cycle,
) -> int:
    first_cycle = True
    while not stop_event.is_set():
        try:
            result = cycle(
                settings,
                project_root=project_root,
                stop_event=stop_event,
                initialize=initialize and first_cycle,
            )
        except GracefulStop:
            return 0
        print(
            f"cycle_ready last_run_id={result.last_run_id} "
            f"appended_rows={result.appended_rows} "
            f"production_rows={result.production_rows} "
            f"next_local_time={result.next_schedule.local_run_time.isoformat()}"
        )
        first_cycle = False
        if once or stop_event.is_set():
            return 0
        delay = wait_seconds_until(result.next_schedule)
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
        description="Continuously append signed-cursor pages to legacy_records"
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="run one cursor collection cycle and exit",
    )
    parser.add_argument(
        "--initialize",
        action="store_true",
        help="backup legacy_records and perform the one-time full pagination",
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
        help="project root (retained for CLI compatibility)",
    )
    args = parser.parse_args()
    if args.initialize and not args.once:
        parser.error("--initialize requires --once")
    stop_event = Event()
    _install_signal_handlers(stop_event)
    try:
        return run_service(
            Settings.from_env(),
            project_root=args.project_root.resolve(),
            once=args.once,
            initialize=args.initialize,
            stop_event=stop_event,
        )
    except Exception as exc:
        print(f"service failed: {type(exc).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
