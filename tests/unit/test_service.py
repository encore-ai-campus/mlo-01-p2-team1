from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from threading import Event
import unittest
from unittest.mock import MagicMock, patch

from legacy_crawler.append_pipeline import PageAppendResult
from legacy_crawler.config import Settings
from legacy_crawler.scheduler import NextRunSchedule
from legacy_crawler.service import (
    GracefulStop,
    ServiceCycleError,
    run_cycle,
    run_service,
    wait_seconds_until,
)


RUN_ID = "20260828T100000+0900-page"


def result() -> PageAppendResult:
    now = datetime.now().astimezone()
    return PageAppendResult(
        last_run_id=RUN_ID,
        appended_rows=15,
        page_count=1,
        production_rows=10015,
        next_schedule=NextRunSchedule(now, now + timedelta(seconds=30), 0.0),
        backup_collection=None,
    )


class ServiceUnitTests(unittest.TestCase):
    def test_wait_seconds_uses_schedule_local_timestamp(self) -> None:
        now = datetime.fromisoformat("2026-08-27T15:00:00+09:00")
        schedule = NextRunSchedule(
            source_target_time=now + timedelta(seconds=20),
            local_run_time=now + timedelta(seconds=12.5),
            clock_offset_seconds=7.5,
        )
        self.assertEqual(wait_seconds_until(schedule, now=now), 12.5)
        self.assertEqual(
            wait_seconds_until(schedule, now=now + timedelta(seconds=20)), 0.0
        )

    def test_cycle_calls_page_append_with_initialization_flag(self) -> None:
        collect = MagicMock(return_value=result())
        actual = run_cycle(
            Settings.from_env({}),
            project_root=Path.cwd(),
            initialize=True,
            collect=collect,
        )
        self.assertEqual(actual.last_run_id, RUN_ID)
        collect.assert_called_once()
        self.assertTrue(collect.call_args.kwargs["initialize"])

    def test_cycle_failure_exits_nonzero_path(self) -> None:
        with self.assertRaises(ServiceCycleError):
            run_cycle(
                Settings.from_env({}),
                project_root=Path.cwd(),
                collect=MagicMock(side_effect=RuntimeError("failed")),
            )

    def test_stop_before_cycle_does_not_collect(self) -> None:
        stop = Event()
        stop.set()
        collect = MagicMock()
        with self.assertRaises(GracefulStop):
            run_cycle(
                Settings.from_env({}),
                project_root=Path.cwd(),
                stop_event=stop,
                collect=collect,
            )
        collect.assert_not_called()

    def test_once_returns_without_waiting(self) -> None:
        stop = MagicMock()
        stop.is_set.return_value = False
        cycle = MagicMock(return_value=result())
        code = run_service(
            Settings.from_env({}),
            project_root=Path.cwd(),
            once=True,
            initialize=True,
            stop_event=stop,
            cycle=cycle,
        )
        self.assertEqual(code, 0)
        self.assertTrue(cycle.call_args.kwargs["initialize"])
        stop.wait.assert_not_called()

    def test_continuous_runner_waits_for_dynamic_schedule(self) -> None:
        stop = MagicMock()
        stop.is_set.side_effect = [False, False]
        stop.wait.return_value = True
        cycle = MagicMock(return_value=result())
        with patch("legacy_crawler.service.wait_seconds_until", return_value=17.25):
            code = run_service(
                Settings.from_env({}),
                project_root=Path.cwd(),
                once=False,
                initialize=False,
                stop_event=stop,
                cycle=cycle,
            )
        self.assertEqual(code, 0)
        stop.wait.assert_called_once_with(17.25)


if __name__ == "__main__":
    unittest.main()
