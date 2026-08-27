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
    def test_main_combines_same_run_and_keeps_row_units_separate(self):
        run = make_run()
        facts = make_mongo_facts(run["run_id"], standard_rows=2, normalization_rows=1)
        mysql_repository = FakeMySQLRepository(run, [run])
        mongo_repository = FakeMongoRepository(facts)

        context = MainDashboardService(
            mysql_repository=mysql_repository,
            mongodb_repository=mongo_repository,
        ).get_dashboard()

        self.assertEqual(mongo_repository.summary_calls, [run["run_id"]])
        self.assertEqual(context["legacy"]["total_received"], 16)
        self.assertEqual(context["total_loaded"], 16)
        self.assertEqual(context["overall_load_rate"], 100.0)
        self.assertEqual(context["pending_rows"], 0)
        self.assertEqual(context["scene_payload"]["mongoLoaded"], 3)
        self.assertNotEqual(context["total_loaded"], 20 + 3)

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

    def test_history_and_trend_failures_do_not_discard_current_kpis(self):
        run = make_run()
        facts = make_mongo_facts(run["run_id"])
        context = MainDashboardService(
            mysql_repository=FakeMySQLRepository(
                run,
                history_error=PipelineRepositoryError("history unavailable"),
            ),
            mongodb_repository=FakeMongoRepository(
                facts,
                trend_error=MongoRepositoryError("trend unavailable"),
            ),
        ).get_dashboard()

        codes = {alert["code"] for alert in context["alerts"]}
        self.assertEqual(context["legacy"]["total_received"], 16)
        self.assertEqual(context["mongo"]["load"]["loaded"], 3)
        self.assertIn("MYSQL_HISTORY_UNAVAILABLE", codes)
        self.assertIn("MONGODB_TREND_UNAVAILABLE", codes)
        self.assertEqual(context["overall_status"], "WARNING")
