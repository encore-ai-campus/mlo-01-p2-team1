from datetime import datetime
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase

from datapipeline.repository.mongodb_repository import MongoRepositoryError
from datapipeline.repository.mysql_repository import PipelineRepositoryError
from datapipeline.service.main_services import MainDashboardService
from datapipeline.tests.helpers import (
    FakeMongoRepository,
    FakeMySQLRepository,
    make_mongo_facts,
    make_run,
)


class MainDashboardServiceTests(SimpleTestCase):
    def test_main_reconciles_every_mysql_run_id_and_aggregates_row_units(self):
        latest = make_run(run_id="run-latest")
        previous = make_run(run_id="run-previous")
        runs = [latest, previous]
        facts = make_mongo_facts(
            "ALL-RUNS",
            standard_rows=4,
            normalization_rows=2,
        )
        facts["run_ids"] = [run["run_id"] for run in runs]
        facts["run_count"] = len(runs)
        facts["stages"]["standardization"]["run_counts"] = {
            run["run_id"]: {"rejected_rows": 2, "error_occurrences": 2}
            for run in runs
        }
        facts["stages"]["normalization"]["run_counts"] = {
            run["run_id"]: {"rejected_rows": 1, "error_occurrences": 1}
            for run in runs
        }
        mysql_repository = FakeMySQLRepository(latest, runs)
        mongo_repository = FakeMongoRepository(facts)

        context = MainDashboardService(
            mysql_repository=mysql_repository,
            mongodb_repository=mongo_repository,
        ).get_dashboard()

        self.assertEqual(mysql_repository.all_calls, 1)
        self.assertEqual(
            mongo_repository.multi_summary_calls,
            [["run-latest", "run-previous"]],
        )
        self.assertEqual(mongo_repository.summary_calls, [])
        self.assertEqual(context["legacy"]["total_received"], 32)
        self.assertEqual(context["legacy"]["run_count"], 2)
        self.assertEqual(context["legacy"]["latest_batch"], "run-latest")
        self.assertEqual(context["total_loaded"], 32)
        self.assertEqual(context["overall_load_rate"], 100.0)
        self.assertEqual(context["pending_rows"], 0)
        self.assertEqual(context["scene_payload"]["mongoLoaded"], 6)
        self.assertEqual(context["scene_payload"]["goldManagers"], 10)
        self.assertEqual(context["legacy"]["input_rate"], 100.0)
        self.assertEqual(context["database_shares"]["mysql"]["rate"], 81.2)
        self.assertEqual(context["database_shares"]["mongodb"]["rate"], 18.8)
        self.assertEqual(
            context["chart_payload"]["qualityDistribution"]["centerText"],
            "81.2%",
        )
        self.assertNotEqual(context["total_loaded"], 40 + 6)

    def test_hourly_ingestion_groups_recent_raw_counts_in_kst(self):
        kst = ZoneInfo("Asia/Seoul")
        latest = make_run(
            started_at=datetime(2026, 8, 28, 10, 20, tzinfo=kst),
        )
        same_hour = make_run(
            started_at=datetime(2026, 8, 28, 10, 5, tzinfo=kst),
        )
        previous_hour = make_run(
            started_at=datetime(2026, 8, 28, 9, 55, tzinfo=kst),
        )
        history = [latest, same_hour, previous_hour]
        facts = make_mongo_facts(latest["run_id"])
        mysql_repository = FakeMySQLRepository(latest, history)

        context = MainDashboardService(
            mysql_repository=mysql_repository,
            mongodb_repository=FakeMongoRepository(facts),
        ).get_dashboard()

        chart = context["chart_payload"]["hourlyIngestionVolume"]
        self.assertEqual(mysql_repository.all_calls, 1)
        self.assertEqual(chart["labels"], ["08-28 09:00", "08-28 10:00"])
        self.assertEqual(chart["datasets"][0]["values"], [16, 32])

    def test_main_warns_when_one_mysql_run_id_has_no_matching_mongo_rows(self):
        latest = make_run(run_id="run-latest")
        missing = make_run(run_id="run-missing")
        facts = make_mongo_facts(latest["run_id"])

        context = MainDashboardService(
            mysql_repository=FakeMySQLRepository(latest, [latest, missing]),
            mongodb_repository=FakeMongoRepository(facts),
        ).get_dashboard()

        alert = next(
            item
            for item in context["alerts"]
            if item["code"] == "MONGODB_RUN_ID_RECONCILIATION_MISMATCH"
        )
        self.assertEqual(alert["affected_run_count"], 1)
        self.assertEqual(alert["affected_run_ids"], ["run-missing"])
        self.assertEqual(context["overall_status"], "CRITICAL")

    def test_main_status_uses_critical_over_warning(self):
        run = make_run()
        facts = make_mongo_facts(
            run["run_id"],
            duplicate_document_count=1,
            error_codes=[
                {
                    "code": "MISSING_REQUIRED",
                    "label": "필수값 누락",
                    "occurrence_count": 3,
                    "affected_row_count": 2,
                }
            ],
        )

        context = MainDashboardService(
            mysql_repository=FakeMySQLRepository(run, [run]),
            mongodb_repository=FakeMongoRepository(facts),
        ).get_dashboard()

        self.assertEqual(context["overall_status"], "CRITICAL")
        self.assertEqual(context["pipeline_events"][0]["tone"], "red")
        self.assertLessEqual(len(context["pipeline_events"]), 5)

    def test_trend_failure_does_not_discard_aggregate_kpis(self):
        run = make_run()
        facts = make_mongo_facts(run["run_id"])
        context = MainDashboardService(
            mysql_repository=FakeMySQLRepository(run, [run]),
            mongodb_repository=FakeMongoRepository(
                facts,
                trend_error=MongoRepositoryError("trend unavailable"),
            ),
        ).get_dashboard()

        codes = {alert["code"] for alert in context["alerts"]}
        self.assertEqual(context["legacy"]["total_received"], 16)
        self.assertEqual(context["mongo"]["load"]["loaded"], 3)
        self.assertIn("MONGODB_TREND_UNAVAILABLE", codes)
        self.assertEqual(context["overall_status"], "WARNING")

    def test_all_mysql_run_query_failure_returns_critical_empty_context(self):
        mongo_repository = FakeMongoRepository()
        context = MainDashboardService(
            mysql_repository=FakeMySQLRepository(
                all_error=PipelineRepositoryError("all runs unavailable")
            ),
            mongodb_repository=mongo_repository,
        ).get_dashboard()

        self.assertEqual(context["legacy"]["total_received"], 0)
        self.assertEqual(context["legacy"]["run_count"], 0)
        self.assertEqual(context["overall_status"], "CRITICAL")
        self.assertIn(
            "MYSQL_UNAVAILABLE",
            {alert["code"] for alert in context["alerts"]},
        )
        self.assertEqual(mongo_repository.multi_summary_calls, [])
