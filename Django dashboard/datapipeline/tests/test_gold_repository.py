from datetime import datetime
from decimal import Decimal
from unittest.mock import MagicMock

from django.test import SimpleTestCase

from datapipeline.repository.gold_repository import (
    GOLD_COLUMNS,
    GoldRepository,
    GoldRepositoryError,
)


class GoldRepositoryTests(SimpleTestCase):
    def _connection_with_rows(self, rows, latest_run_id="gold-run-001"):
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = (latest_run_id,) if latest_run_id else None
        cursor.description = [(column,) for column in GOLD_COLUMNS]
        cursor.fetchall.return_value = [
            tuple(row.get(column) for column in GOLD_COLUMNS) for row in rows
        ]
        return connection, cursor

    def test_live_view_query_returns_normalized_workload_features(self):
        row = {column: None for column in GOLD_COLUMNS}
        row.update(
            {
                "run_id": "gold-run-001",
                "as_of_datetime": datetime(2026, 8, 28, 15, 30, 5),
                "pipeline_completed_at": datetime(2026, 8, 28, 15, 32, 10),
                "manager_id": " EMP000001 ",
                "manager_department_name": "분석팀",
                "manager_position_name": "팀장",
                "manager_active_flag": "Y",
                "manager_tenure_days": "2100",
                "managed_area_count": "11",
                "workload_score": Decimal("11.00"),
                "peer_average_workload_score": Decimal("8.26"),
                "peer_average_area_count": Decimal("8.26"),
                "workload_ratio": Decimal("1.33"),
                "reassignment_required_flag": True,
                "reassignment_priority": "MEDIUM",
                "recommended_reassignment_area_count": "3",
                "reassignment_reason_code": "AREA_COUNT_HIGH",
                "reassignment_reason": "동료 평균보다 업무량이 높습니다.",
                "workload_rule_version": "area_load_v1",
                "feature_version": "v1",
            }
        )
        connection, cursor = self._connection_with_rows([row])
        repository = GoldRepository(connection=connection, data_mode="live")

        result = repository.get_manager_features(limit=10)

        self.assertEqual(result[0]["manager_id"], "EMP000001")
        self.assertEqual(result[0]["manager_active_flag"], 1)
        self.assertEqual(result[0]["managed_area_count"], 11)
        self.assertEqual(result[0]["workload_score"], 11.0)
        self.assertEqual(result[0]["workload_ratio"], 1.33)
        self.assertEqual(result[0]["reassignment_required_flag"], 1)
        self.assertEqual(result[0]["as_of_datetime"], "2026-08-28T15:30:05")

        self.assertEqual(cursor.execute.call_count, 2)
        latest_sql = cursor.execute.call_args_list[0].args[0]
        data_sql, params = cursor.execute.call_args_list[1].args
        self.assertIn("ORDER BY as_of_datetime DESC", latest_sql)
        self.assertIn("FROM dashboard_gold_manager_assignment_view", data_sql)
        self.assertIn("WHERE run_id = %s", data_sql)
        self.assertNotIn("managed_top_area_count", data_sql)
        self.assertEqual(params, ["gold-run-001", 10])

    def test_live_empty_view_returns_no_rows(self):
        connection, cursor = self._connection_with_rows([], latest_run_id=None)
        repository = GoldRepository(connection=connection, data_mode="live")

        self.assertEqual(repository.get_manager_features(), [])
        self.assertEqual(cursor.execute.call_count, 1)

    def test_sample_mode_returns_feature_rows_without_database_access(self):
        connection = MagicMock()
        repository = GoldRepository(connection=connection, data_mode="sample")

        rows = repository.get_manager_features(limit=5)

        self.assertEqual(len(rows), 5)
        self.assertEqual(set(rows[0]), set(GOLD_COLUMNS))
        connection.cursor.assert_not_called()

    def test_query_failure_is_wrapped(self):
        connection, cursor = self._connection_with_rows([])
        cursor.execute.side_effect = RuntimeError("view missing")
        repository = GoldRepository(connection=connection, data_mode="live")

        with self.assertRaises(GoldRepositoryError) as raised:
            repository.get_manager_features()

        self.assertIsInstance(raised.exception.__cause__, RuntimeError)

    def test_unsafe_view_name_is_rejected(self):
        with self.assertRaises(ValueError):
            GoldRepository(data_mode="sample", view_name="gold_view; DROP TABLE manager")
