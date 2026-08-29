from django.test import SimpleTestCase

from datapipeline.repository.mongodb_repository import MongoRepositoryError
from datapipeline.service.mongodb_services import (
    MongoDBDashboardService,
    build_mongodb_dashboard_data,
    evaluate_mongodb_alerts,
)
from datapipeline.tests.helpers import (
    FakeMongoRepository,
    FakeMySQLRepository,
    make_mongo_facts,
    make_run,
)


def alert_codes(alerts):
    return {alert["code"] for alert in alerts}


class MongoDBServiceRuleTests(SimpleTestCase):
    def test_matching_terminal_counts_have_no_reconciliation_alert(self):
        run = make_run()
        facts = make_mongo_facts(run["run_id"])

        self.assertEqual(evaluate_mongodb_alerts(run, facts), [])

    def test_success_mismatch_is_critical_but_running_mismatch_is_ignored(self):
        success = make_run()
        running = make_run(batch_status="RUNNING", completed_at=None)
        facts = make_mongo_facts(success["run_id"], standard_rows=1, normalization_rows=0)

        success_alerts = evaluate_mongodb_alerts(success, facts)
        running_alerts = evaluate_mongodb_alerts(running, facts)

        self.assertIn("STANDARDIZATION_MONGO_COUNT_MISMATCH", alert_codes(success_alerts))
        self.assertEqual(success_alerts[0]["level"], "CRITICAL")
        self.assertNotIn("STANDARDIZATION_MONGO_COUNT_MISMATCH", alert_codes(running_alerts))

    def test_document_quality_and_error_spike_alerts(self):
        run = make_run()
        facts = make_mongo_facts(
            run["run_id"],
            error_codes=[
                {
                    "code": "MISSING_REQUIRED",
                    "label": "필수값 누락",
                    "occurrence_count": 3,
                    "affected_row_count": 1,
                }
            ],
            rows_without_errors=1,
            malformed_error_count=1,
            duplicate_document_count=1,
        )

        codes = alert_codes(evaluate_mongodb_alerts(run, facts))

        self.assertIn("REJECTED_WITHOUT_ERRORS", codes)
        self.assertIn("MALFORMED_ERROR_CODE", codes)
        self.assertIn("DUPLICATE_REJECTED_DOCUMENT", codes)
        self.assertIn("ERROR_CODE_SPIKE", codes)

    def test_reason_rates_use_error_occurrences_not_rejected_rows(self):
        run = make_run()
        facts = make_mongo_facts(
            run["run_id"],
            standard_rows=1,
            normalization_rows=0,
            standard_errors=3,
            normalization_errors=0,
            error_codes=[
                {
                    "code": "MISSING_REQUIRED",
                    "label": "필수값 누락",
                    "occurrence_count": 2,
                    "affected_row_count": 1,
                },
                {
                    "code": "INVALID_DATE_FORMAT",
                    "label": "날짜 형식 오류",
                    "occurrence_count": 1,
                    "affected_row_count": 1,
                },
            ],
        )

        data = build_mongodb_dashboard_data(run, facts)

        self.assertEqual(data["standardized"]["rejected"], 1)
        self.assertEqual(data["standardized"]["errors"], 3)
        self.assertEqual(data["total_error_occurrences"], 3)
        self.assertEqual(data["reasons"][0]["rate"], 66.7)
        self.assertEqual(data["reasons"][0]["affected_rows"], 1)


class MongoDBDashboardServiceTests(SimpleTestCase):
    def test_service_queries_mongodb_with_same_mysql_run_id(self):
        run = make_run()
        facts = make_mongo_facts(run["run_id"])
        mysql_repository = FakeMySQLRepository(run, [run])
        mongo_repository = FakeMongoRepository(facts, trend={run["run_id"]: {}})

        context = MongoDBDashboardService(
            mongodb_repository=mongo_repository,
            mysql_repository=mysql_repository,
        ).get_dashboard(run["run_id"])

        self.assertEqual(mongo_repository.summary_calls, [run["run_id"]])
        self.assertEqual(mongo_repository.trend_calls, [[run["run_id"]]])
        self.assertEqual(context["mongo"]["run_id"], run["run_id"])
        self.assertEqual(context["chart_payload"]["mongoReasonVolume"]["type"], "bar")

    def test_default_dashboard_aggregates_all_mysql_run_ids_in_mongodb(self):
        latest = make_run(run_id="run-latest")
        previous = make_run(run_id="run-previous")
        runs = [latest, previous]
        facts = make_mongo_facts(
            "ALL-RUNS",
            standard_rows=4,
            normalization_rows=2,
        )
        facts["stages"]["standardization"]["run_counts"] = {
            run["run_id"]: {"rejected_rows": 2, "error_occurrences": 2}
            for run in runs
        }
        facts["stages"]["normalization"]["run_counts"] = {
            run["run_id"]: {"rejected_rows": 1, "error_occurrences": 1}
            for run in runs
        }
        mongo_repository = FakeMongoRepository(facts)

        context = MongoDBDashboardService(
            mongodb_repository=mongo_repository,
            mysql_repository=FakeMySQLRepository(latest, runs),
        ).get_dashboard()

        self.assertEqual(
            mongo_repository.multi_summary_calls,
            [["run-latest", "run-previous"]],
        )
        self.assertEqual(context["aggregation_scope"], "ALL_RUNS")
        self.assertEqual(context["aggregated_run_count"], 2)
        self.assertEqual(context["mongo"]["run_id"], "ALL-RUNS")
        self.assertEqual(context["mongo"]["load"]["loaded"], 6)

    def test_mongodb_repository_failure_becomes_critical_alert(self):
        run = make_run()
        context = MongoDBDashboardService(
            mongodb_repository=FakeMongoRepository(
                summary_error=MongoRepositoryError("offline")
            ),
            mysql_repository=FakeMySQLRepository(run, [run]),
        ).get_dashboard()

        self.assertEqual(context["overall_status"], "CRITICAL")
        self.assertIn("MONGODB_UNAVAILABLE", alert_codes(context["alerts"]))

    def test_running_batch_does_not_raise_false_mongodb_count_mismatch(self):
        run = make_run(batch_status="RUNNING", completed_at=None)
        facts = make_mongo_facts(run["run_id"], standard_rows=0, normalization_rows=0)
        context = MongoDBDashboardService(
            mongodb_repository=FakeMongoRepository(facts),
            mysql_repository=FakeMySQLRepository(run, [run]),
        ).get_dashboard()

        self.assertNotIn(
            "STANDARDIZATION_MONGO_COUNT_MISMATCH",
            alert_codes(context["alerts"]),
        )

    def test_trend_failure_keeps_current_rejected_facts(self):
        run = make_run()
        facts = make_mongo_facts(run["run_id"])
        context = MongoDBDashboardService(
            mongodb_repository=FakeMongoRepository(
                facts,
                trend_error=MongoRepositoryError("trend unavailable"),
            ),
            mysql_repository=FakeMySQLRepository(run, [run]),
        ).get_dashboard()

        self.assertEqual(context["mongo"]["load"]["loaded"], 3)
        self.assertIn("MONGODB_TREND_UNAVAILABLE", alert_codes(context["alerts"]))
        self.assertEqual(context["overall_status"], "WARNING")
