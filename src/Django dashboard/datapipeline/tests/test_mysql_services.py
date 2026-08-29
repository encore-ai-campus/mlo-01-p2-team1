from copy import deepcopy
from datetime import datetime, timedelta, timezone as datetime_timezone
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase

from datapipeline.repository.mysql_repository import PipelineRepositoryError
from datapipeline.service.mysql_services import (
    MySQLDashboardService,
    alert_status,
    build_mysql_dashboard_data,
    build_mysql_load_rate_telemetry,
    evaluate_mysql_alerts,
    percentage,
)
from datapipeline.tests.helpers import FakeMySQLRepository, make_run


FIXED_NOW = datetime(2026, 8, 28, 12, 0, tzinfo=datetime_timezone.utc)


def alert_codes(alerts):
    return {alert["code"] for alert in alerts}


class MySQLServiceRuleTests(SimpleTestCase):
    def test_percentage_and_alert_priority(self):
        self.assertEqual(percentage(1, 3), 33.3)
        self.assertEqual(percentage(0, 0), 0.0)
        self.assertEqual(percentage(0, 0, empty_value=100), 100.0)
        self.assertEqual(alert_status([]), "NORMAL")
        self.assertEqual(alert_status([{"level": "WARNING"}]), "WARNING")
        self.assertEqual(
            alert_status([{"level": "WARNING"}, {"level": "CRITICAL"}]),
            "CRITICAL",
        )

    def test_reconciled_recent_success_has_no_alerts(self):
        run = make_run(now=FIXED_NOW)

        self.assertEqual(evaluate_mysql_alerts(run, [run], now=FIXED_NOW), [])

    def test_terminal_staleness_changes_at_six_and_nine_minutes(self):
        warning_run = make_run(
            now=FIXED_NOW,
            started_at=FIXED_NOW - timedelta(minutes=6),
            completed_at=FIXED_NOW - timedelta(minutes=5, seconds=30),
        )
        critical_run = make_run(
            now=FIXED_NOW,
            started_at=FIXED_NOW - timedelta(minutes=9),
            completed_at=FIXED_NOW - timedelta(minutes=8, seconds=30),
        )

        self.assertIn(
            "PIPELINE_DELAYED",
            alert_codes(evaluate_mysql_alerts(warning_run, now=FIXED_NOW)),
        )
        self.assertIn(
            "PIPELINE_STALE",
            alert_codes(evaluate_mysql_alerts(critical_run, now=FIXED_NOW)),
        )

    def test_running_batch_warns_without_terminal_count_reconciliation(self):
        run = make_run(
            now=FIXED_NOW,
            batch_status="RUNNING",
            started_at=FIXED_NOW - timedelta(minutes=6),
            completed_at=None,
            raw_row_count=16,
            standardization_accepted_count=1,
            standardization_rejected_count=1,
            final_accepted_count=0,
            final_rejected_count=0,
        )

        codes = alert_codes(evaluate_mysql_alerts(run, now=FIXED_NOW))

        self.assertIn("RUN_DELAYED", codes)
        self.assertNotIn("STANDARD_COUNT_MISMATCH", codes)
        self.assertNotIn("FINAL_COUNT_MISMATCH", codes)

    def test_failed_and_repeated_partial_failure_statuses_escalate(self):
        failed = make_run(now=FIXED_NOW, batch_status="FAILED")
        partial = make_run(now=FIXED_NOW, batch_status="PARTIAL_FAILURE")

        self.assertIn("BATCH_FAILED", alert_codes(evaluate_mysql_alerts(failed, now=FIXED_NOW)))
        repeated = evaluate_mysql_alerts(partial, [partial, deepcopy(partial)], now=FIXED_NOW)
        self.assertIn("BATCH_PARTIAL_FAILURE", alert_codes(repeated))
        self.assertIn("REPEATED_PARTIAL_FAILURE", alert_codes(repeated))

    def test_count_mismatches_are_critical(self):
        standard_mismatch = make_run(now=FIXED_NOW, raw_row_count=17)
        final_mismatch = make_run(now=FIXED_NOW, final_accepted_count=12)

        self.assertIn(
            "STANDARD_COUNT_MISMATCH",
            alert_codes(evaluate_mysql_alerts(standard_mismatch, now=FIXED_NOW)),
        )
        self.assertIn(
            "FINAL_COUNT_MISMATCH",
            alert_codes(evaluate_mysql_alerts(final_mismatch, now=FIXED_NOW)),
        )

    def test_rejected_threshold_boundaries(self):
        standard_warning = make_run(
            now=FIXED_NOW,
            standardization_accepted_count=12,
            standardization_rejected_count=4,
            final_accepted_count=11,
            final_rejected_count=1,
        )
        standard_critical = make_run(
            now=FIXED_NOW,
            standardization_accepted_count=8,
            standardization_rejected_count=8,
            final_accepted_count=7,
            final_rejected_count=1,
        )
        final_warning = make_run(
            now=FIXED_NOW,
            final_accepted_count=11,
            final_rejected_count=3,
        )
        final_critical = make_run(
            now=FIXED_NOW,
            final_accepted_count=8,
            final_rejected_count=6,
        )

        self.assertIn(
            "STANDARD_REJECT_HIGH",
            alert_codes(evaluate_mysql_alerts(standard_warning, now=FIXED_NOW)),
        )
        self.assertIn(
            "STANDARD_REJECT_SURGE",
            alert_codes(evaluate_mysql_alerts(standard_critical, now=FIXED_NOW)),
        )
        self.assertIn(
            "FINAL_REJECT_HIGH",
            alert_codes(evaluate_mysql_alerts(final_warning, now=FIXED_NOW)),
        )
        self.assertIn(
            "FINAL_REJECT_SURGE",
            alert_codes(evaluate_mysql_alerts(final_critical, now=FIXED_NOW)),
        )

    def test_success_entity_load_mismatch_is_critical(self):
        run = make_run(now=FIXED_NOW, manager_loaded_count=4)

        alerts = evaluate_mysql_alerts(run, now=FIXED_NOW)

        self.assertIn("SUCCESS_LOAD_MISMATCH", alert_codes(alerts))
        self.assertEqual(alert_status(alerts), "CRITICAL")

    def test_dashboard_data_calculates_rates_and_duration(self):
        run = make_run(now=FIXED_NOW)

        data = build_mysql_dashboard_data(run, [run], now=FIXED_NOW)

        self.assertEqual(data["standardized"]["rate"], 87.5)
        self.assertEqual(data["normalized"]["rate"], 92.9)
        self.assertEqual(data["load"]["loaded"], 13)
        self.assertEqual(data["load"]["expected"], 16)
        self.assertEqual(data["load"]["rate"], 81.2)
        self.assertEqual(data["entity_load"]["rate"], 100.0)
        self.assertEqual(data["recent_batches"][0]["duration"], "00:30")

    def test_load_rate_telemetry_uses_weighted_kst_half_hour_buckets(self):
        kst = ZoneInfo("Asia/Seoul")
        history = [
            make_run(
                started_at=datetime(2026, 8, 28, 10, 29, tzinfo=kst),
                raw_row_count=30,
                final_accepted_count=24,
            ),
            make_run(
                started_at=datetime(2026, 8, 28, 10, 1, tzinfo=kst),
                raw_row_count=10,
                final_accepted_count=5,
            ),
            make_run(
                started_at=datetime(2026, 8, 28, 10, 59, tzinfo=kst),
                raw_row_count=10,
                final_accepted_count=10,
            ),
            make_run(
                started_at=datetime(2026, 8, 28, 10, 30, tzinfo=kst),
                raw_row_count=20,
                final_accepted_count=10,
            ),
        ]

        telemetry = build_mysql_load_rate_telemetry(history)

        self.assertEqual(
            telemetry["labels"],
            ["08-28 10:00", "08-28 10:30"],
        )
        self.assertEqual(telemetry["values"], [72.5, 66.7])


class MySQLDashboardServiceTests(SimpleTestCase):
    def test_service_uses_injected_repository_and_builds_chart_contract(self):
        run = make_run()
        repository = FakeMySQLRepository(run, [run])

        context = MySQLDashboardService(mysql_repository=repository).get_dashboard(run["run_id"])

        self.assertEqual(repository.summary_calls, [run["run_id"]])
        self.assertEqual(repository.history_calls, [60])
        self.assertEqual(context["mysql"]["run"]["run_id"], run["run_id"])
        self.assertEqual(context["chart_payload"]["mysqlLoadTrend"]["type"], "line")

    def test_all_run_repository_failure_becomes_critical_alert(self):
        repository = FakeMySQLRepository(
            all_error=PipelineRepositoryError("offline")
        )

        context = MySQLDashboardService(mysql_repository=repository).get_dashboard()

        self.assertEqual(context["overall_status"], "CRITICAL")
        self.assertIn("MYSQL_UNAVAILABLE", alert_codes(context["alerts"]))

    def test_history_failure_keeps_current_kpi_and_adds_warning(self):
        run = make_run()
        repository = FakeMySQLRepository(
            run,
            history_error=PipelineRepositoryError("history unavailable"),
        )

        context = MySQLDashboardService(mysql_repository=repository).get_dashboard(
            run["run_id"]
        )

        self.assertEqual(context["mysql"]["run"]["run_id"], run["run_id"])
        self.assertEqual(context["mysql"]["standardized"]["accepted"], 14)
        self.assertIn("MYSQL_HISTORY_UNAVAILABLE", alert_codes(context["alerts"]))
        self.assertEqual(context["overall_status"], "WARNING")

    def test_default_dashboard_aggregates_all_mysql_view_runs(self):
        latest = make_run(run_id="run-latest")
        previous = make_run(run_id="run-previous")
        repository = FakeMySQLRepository(latest, [latest, previous])

        context = MySQLDashboardService(mysql_repository=repository).get_dashboard()

        self.assertEqual(repository.all_calls, 1)
        self.assertEqual(context["aggregation_scope"], "ALL_RUNS")
        self.assertEqual(context["aggregated_run_count"], 2)
        self.assertEqual(context["mysql"]["run"]["run_id"], "ALL-RUNS")
        self.assertEqual(context["mysql"]["standardized"]["input"], 32)
        self.assertEqual(context["mysql"]["standardized"]["accepted"], 28)
