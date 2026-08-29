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
        "run_id": "gold-run-001",
        "as_of_datetime": "2026-08-28T15:30:05",
        "pipeline_completed_at": "2026-08-28T15:32:10",
        "manager_id": manager_id,
        "manager_department_name": "분석팀",
        "manager_position_name": "팀장",
        "manager_active_flag": 1,
        "manager_tenure_days": 2100,
        "managed_area_count": 3,
        "workload_score": 4.5,
        "peer_average_workload_score": 3.0,
        "peer_average_area_count": 2.4,
        "workload_ratio": 1.5,
        "reassignment_required_flag": 1,
        "reassignment_priority": "MEDIUM",
        "recommended_reassignment_area_count": 1,
        "reassignment_reason_code": "WORKLOAD_RATIO_HIGH",
        "reassignment_reason": "동료 평균보다 업무량이 높습니다.",
        "workload_rule_version": "area_load_v1",
        "feature_version": "v1",
    }
    row.update(overrides)
    return row


class FakeGoldRepository:
    view_name = "dashboard_gold_manager_assignment_view"

    def __init__(self, rows=None, error=None):
        self.rows = deepcopy(rows or [])
        self.error = error
        self.calls = []

    def get_manager_features(self, limit=5000):
        self.calls.append(limit)
        if self.error:
            raise self.error
        return deepcopy(self.rows)


class GoldServiceTests(SimpleTestCase):
    def test_builder_calculates_workload_and_reassignment_contracts(self):
        rows = [
            make_gold_row(),
            make_gold_row(
                "EMP000002",
                manager_department_name="생산팀",
                manager_active_flag=0,
                managed_area_count=0,
                workload_score=0.0,
                workload_ratio=0.0,
                reassignment_required_flag=0,
                reassignment_priority="NORMAL",
                recommended_reassignment_area_count=0,
                reassignment_reason_code="",
                reassignment_reason="",
            ),
        ]

        gold = build_gold_dashboard_data(rows)

        self.assertEqual(gold["run_id"], "gold-run-001")
        self.assertEqual(gold["total_managers"], 2)
        self.assertEqual(gold["active_rate"], 50.0)
        self.assertEqual(gold["reassignment_required_count"], 1)
        self.assertEqual(gold["reassignment_required_rate"], 50.0)
        self.assertEqual(gold["unassigned_count"], 1)
        self.assertEqual(gold["average_area_count"], 1.5)
        self.assertEqual(gold["feature_rows"][1]["review_signal"], "UNASSIGNED")
        self.assertEqual(gold["chart_payload"]["goldWorkloadMatrix"]["type"], "scatter")
        self.assertEqual(gold["chart_payload"]["goldFeatureRadar"]["type"], "radar")
        self.assertIn("workloadScore", gold["scene_managers"][0])

    def test_gold_validation_detects_snapshot_and_feature_errors(self):
        rows = [
            make_gold_row(),
            make_gold_row(
                run_id="gold-run-002",
                manager_tenure_days=-1,
                reassignment_reason="",
            ),
        ]

        codes = {alert["code"] for alert in evaluate_gold_alerts(rows)}

        self.assertIn("DUPLICATE_GOLD_MANAGER", codes)
        self.assertIn("MULTIPLE_GOLD_RUNS", codes)
        self.assertIn("INVALID_GOLD_FEATURE", codes)
        self.assertIn("MISSING_REASSIGNMENT_REASON", codes)

    def test_dashboard_service_keeps_view_failure_renderable(self):
        repository = FakeGoldRepository(error=GoldRepositoryError("unavailable"))

        context = GoldDashboardService(gold_repository=repository).get_dashboard()

        self.assertEqual(repository.calls, [5000])
        self.assertEqual(context["gold"]["total_managers"], 0)
        self.assertEqual(context["overall_status"], "CRITICAL")
        self.assertEqual(context["alerts"][0]["code"], "GOLD_VIEW_UNAVAILABLE")
        self.assertEqual(context["source_status"], "VIEW WAITING")

    def test_dashboard_service_returns_live_view_rows_to_browser_contract(self):
        rows = [make_gold_row(), make_gold_row("EMP000002")]
        repository = FakeGoldRepository(rows=rows)

        context = GoldDashboardService(gold_repository=repository).get_dashboard()

        self.assertEqual(repository.calls, [5000])
        self.assertEqual(context["view_name"], "dashboard_gold_manager_assignment_view")
        self.assertEqual(context["source_status"], "SYNCHRONIZED")
        self.assertEqual(context["gold"]["total_managers"], 2)
        self.assertEqual(len(context["feature_payload"]), 2)
        self.assertEqual(len(context["scene_payload"]["managers"]), 2)
