from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
import tempfile
from threading import Event
import unittest
from unittest.mock import MagicMock, patch

from legacy_crawler.config import Settings
from legacy_crawler.main import RunResult
from legacy_crawler.models import ValidationCheck, ValidationReport
from legacy_crawler.promotion import PromotionResult
from legacy_crawler.scheduler import NextRunSchedule
from legacy_crawler.service import (
    GracefulStop,
    ServiceCycleError,
    ServiceCycleResult,
    run_cycle,
    run_service,
    wait_seconds_until,
)


RUN_ID = "20260827T150000+0900-service"


def passing_report() -> ValidationReport:
    return ValidationReport(
        run_id=RUN_ID,
        checks=(ValidationCheck("pass", True, True, True),),
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
            wait_seconds_until(
                schedule, now=now + timedelta(seconds=20)
            ),
            0.0,
        )

    def test_mock_cycle_reuses_collection_validation_and_promotion(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            settings = replace(
                Settings.from_env({}),
                data_root=root / "data",
                backup_root=root / "backup",
                log_root=root / "logs",
                state_root=root / "state",
            )
            now = datetime.fromisoformat("2026-08-27T15:00:00+09:00")
            schedule = NextRunSchedule(now, now + timedelta(seconds=30), 0.0)
            collected = RunResult(
                run_id=RUN_ID,
                row_count=3,
                page_count=1,
                data_path=root / "run",
                backup_path=root / "backup-run",
                staging_collection="legacy_records_staging_service",
                next_schedule=schedule,
            )
            collect = MagicMock(return_value=collected)
            storage = MagicMock()
            storage.runs.find_one.return_value = {
                "run_id": RUN_ID,
                "state": "ready",
            }
            storage.database.__getitem__.return_value.distinct.return_value = [
                RUN_ID
            ]
            promotion = PromotionResult(
                run_id=RUN_ID,
                previous_run_ids=("old-run",),
                backup_collection="legacy_records_backup_old_run",
                production_collection="legacy_records",
                post_validation=passing_report(),
                ready_at=now.isoformat(),
            )
            promoter = MagicMock()
            promoter.promote_ready_to_ready.return_value = promotion

            with (
                patch("legacy_crawler.service.MongoStorage", return_value=storage),
                patch(
                    "legacy_crawler.service.validate_promotion_candidate",
                    return_value=passing_report(),
                ) as validate,
                patch(
                    "legacy_crawler.service.ProductionPromoter",
                    return_value=promoter,
                ),
            ):
                result = run_cycle(
                    settings,
                    project_root=root,
                    stop_event=Event(),
                    collect=collect,
                )

            self.assertEqual(result.run_id, RUN_ID)
            self.assertIs(result.schedule, schedule)
            collect.assert_called_once_with(settings)
            validate.assert_called_once_with(
                storage,
                run_id=RUN_ID,
                run_dir=collected.data_path,
                project_root=root,
            )
            promoter.promote_ready_to_ready.assert_called_once()
            storage.close.assert_called_once_with()

    def test_failed_candidate_exits_cycle_without_promotion(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            settings = replace(
                Settings.from_env({}),
                log_root=root / "logs",
                state_root=root / "state",
            )
            now = datetime.fromisoformat("2026-08-27T15:00:00+09:00")
            collected = RunResult(
                run_id=RUN_ID,
                row_count=1,
                page_count=1,
                data_path=root / "run",
                backup_path=root / "backup-run",
                staging_collection="legacy_records_staging_service",
                next_schedule=NextRunSchedule(now, now, 0.0),
            )
            failed = ValidationReport(
                run_id=RUN_ID,
                checks=(ValidationCheck("failed", False, True, False),),
            )
            storage = MagicMock()
            promoter_class = MagicMock()

            with (
                patch("legacy_crawler.service.MongoStorage", return_value=storage),
                patch(
                    "legacy_crawler.service.validate_promotion_candidate",
                    return_value=failed,
                ),
                patch(
                    "legacy_crawler.service.ProductionPromoter", promoter_class
                ),
            ):
                with self.assertRaises(ServiceCycleError):
                    run_cycle(
                        settings,
                        project_root=root,
                        collect=MagicMock(return_value=collected),
                    )

            promoter_class.assert_not_called()
            storage.close.assert_called_once_with()
            error_log = root / "logs" / "errors" / "crawler_error_2026-08-27.log"
            self.assertTrue(error_log.is_file())
            self.assertNotIn("API", error_log.read_text(encoding="utf-8"))

    def test_once_returns_after_ready_cycle_without_waiting(self) -> None:
        settings = Settings.from_env({})
        stop_event = MagicMock()
        stop_event.is_set.return_value = False
        now = datetime.now().astimezone()
        result = ServiceCycleResult(
            run_id=RUN_ID,
            row_count=2,
            run_dir=Path("run"),
            schedule=NextRunSchedule(now, now + timedelta(seconds=10), 0.0),
            promotion=PromotionResult(
                run_id=RUN_ID,
                previous_run_ids=("old",),
                backup_collection="backup",
                production_collection="legacy_records",
                post_validation=passing_report(),
                ready_at=now.isoformat(),
            ),
        )
        cycle = MagicMock(return_value=result)

        exit_code = run_service(
            settings,
            project_root=Path.cwd(),
            once=True,
            stop_event=stop_event,
            cycle=cycle,
        )

        self.assertEqual(exit_code, 0)
        cycle.assert_called_once()
        stop_event.wait.assert_not_called()

    def test_stop_after_collection_does_not_enter_promotion(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            settings = replace(
                Settings.from_env({}),
                log_root=root / "logs",
                state_root=root / "state",
            )
            now = datetime.now().astimezone()
            collected = RunResult(
                run_id=RUN_ID,
                row_count=1,
                page_count=1,
                data_path=root / "run",
                backup_path=root / "backup-run",
                staging_collection="legacy_records_staging_service",
                next_schedule=NextRunSchedule(now, now, 0.0),
            )
            stop_event = Event()
            stop_event.set()
            with patch("legacy_crawler.service.MongoStorage") as storage_class:
                with self.assertRaises(GracefulStop):
                    run_cycle(
                        settings,
                        project_root=root,
                        stop_event=stop_event,
                        collect=MagicMock(return_value=collected),
                    )
            storage_class.assert_not_called()

    def test_continuous_runner_waits_until_dynamic_schedule_or_stop(self) -> None:
        settings = Settings.from_env({})
        stop_event = MagicMock()
        stop_event.is_set.side_effect = [False, False]
        stop_event.wait.return_value = True
        now = datetime.now().astimezone()
        result = ServiceCycleResult(
            run_id=RUN_ID,
            row_count=2,
            run_dir=Path("run"),
            schedule=NextRunSchedule(now, now + timedelta(seconds=30), 0.0),
            promotion=PromotionResult(
                run_id=RUN_ID,
                previous_run_ids=("old",),
                backup_collection="backup",
                production_collection="legacy_records",
                post_validation=passing_report(),
                ready_at=now.isoformat(),
            ),
        )
        cycle = MagicMock(return_value=result)
        with patch("legacy_crawler.service.wait_seconds_until", return_value=17.25):
            exit_code = run_service(
                settings,
                project_root=Path.cwd(),
                once=False,
                stop_event=stop_event,
                cycle=cycle,
            )

        self.assertEqual(exit_code, 0)
        stop_event.wait.assert_called_once_with(17.25)


if __name__ == "__main__":
    unittest.main()
