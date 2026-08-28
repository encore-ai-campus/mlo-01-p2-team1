from copy import deepcopy

from django.test import SimpleTestCase

from datapipeline.repository.gold_repository import GoldRepositoryError
from datapipeline.service.gold_services import (
    GoldDashboardService,
    build_gold_dashboard_data,
    evaluate_gold_alerts,
)


def make_gold_row(manager_id="EMP000001", **overrides):
    row = {
        "manager_id": manager_id,
        "manager_department_name": "분석팀",
        "manager_position_name": "팀장",
        "manager_active_flag": 1,
        "manager_tenure_days": 2100,
        "managed_area_count": 3,
        "managed_top_area_count": 2,
        "managed_parent_area_count": 1,
        "top_level_area_count": 0,
        "average_area_age_days": 800.0,
        "max_area_age_days": 1200,
        "cross_top_area_flag": 1,
    }
    row.update(overrides)
    return row


class FakeGoldRepository:
    view_name = "dashboard_gold_manager_view"

    def __init__(self, rows=None, error=None):
        self.rows = deepcopy(rows or [])
        self.error = error
        self.calls = []

    def get_manager_features(self, limit=2000):
        self.calls.append(limit)
        if self.error:
            raise self.error
        return deepcopy(self.rows)


class GoldServiceTests(SimpleTestCase):
    def test_builder_calculates_manager_grain_kpis_and_chart_contracts(self):
        rows = [
            make_gold_row(),
            make_gold_row(
                "EMP000002",
                manager_department_name="생산팀",
                manager_active_flag=0,
                managed_area_count=0,
                managed_top_area_count=0,
                managed_parent_area_count=0,
                cross_top_area_flag=0,
            ),
        ]

        gold = build_gold_dashboard_data(rows)

        self.assertEqual(gold["total_managers"], 2)
        self.assertEqual(gold["active_rate"], 50.0)
        self.assertEqual(gold["cross_top_count"], 1)
        self.assertEqual(gold["unassigned_count"], 1)
        self.assertEqual(gold["average_area_count"], 1.5)
        self.assertEqual(gold["feature_rows"][1]["review_signal"], "UNASSIGNED")
        self.assertEqual(gold["chart_payload"]["goldWorkloadMatrix"]["type"], "scatter")
        self.assertEqual(gold["chart_payload"]["goldFeatureRadar"]["type"], "radar")

    def test_gold_validation_detects_duplicate_and_feature_contradictions(self):
        rows = [
            make_gold_row(),
            make_gold_row(
                managed_area_count=1,
                managed_top_area_count=2,
                top_level_area_count=3,
                cross_top_area_flag=0,
                average_area_age_days=1300,
                max_area_age_days=1200,
            ),
        ]

        codes = {alert["code"] for alert in evaluate_gold_alerts(rows)}

        self.assertIn("DUPLICATE_GOLD_MANAGER", codes)
        self.assertIn("INVALID_GOLD_FEATURE", codes)
        self.assertIn("CROSS_TOP_FLAG_MISMATCH", codes)
        self.assertIn("AREA_AGE_MISMATCH", codes)

    def test_dashboard_service_keeps_view_failure_renderable(self):
        repository = FakeGoldRepository(error=GoldRepositoryError("unavailable"))

        context = GoldDashboardService(gold_repository=repository).get_dashboard()

        self.assertEqual(repository.calls, [2000])
        self.assertEqual(context["gold"]["total_managers"], 0)
        self.assertEqual(context["overall_status"], "CRITICAL")
        self.assertEqual(context["alerts"][0]["code"], "GOLD_VIEW_UNAVAILABLE")
        self.assertEqual(context["source_status"], "VIEW WAITING")
