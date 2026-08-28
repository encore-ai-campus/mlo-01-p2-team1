from unittest.mock import MagicMock

from django.test import SimpleTestCase

from datapipeline.repository.gold_repository import (
    GOLD_COLUMNS,
    GoldRepository,
    GoldRepositoryError,
)


class GoldRepositoryTests(SimpleTestCase):
    def _connection_with_rows(self, rows):
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.description = [(column,) for column in GOLD_COLUMNS]
        cursor.fetchall.return_value = [
            tuple(row.get(column) for column in GOLD_COLUMNS) for row in rows
        ]
        return connection, cursor

    def test_live_view_query_returns_normalized_manager_features(self):
        row = {column: None for column in GOLD_COLUMNS}
        row.update(
            {
                "manager_id": " EMP000001 ",
                "manager_department_name": "분석팀",
                "manager_position_name": "팀장",
                "manager_active_flag": "Y",
                "manager_tenure_days": "2100",
                "managed_area_count": "3",
                "managed_top_area_count": 2,
                "managed_parent_area_count": 1,
                "top_level_area_count": 0,
                "average_area_age_days": "800.25",
                "max_area_age_days": 1200,
                "cross_top_area_flag": True,
            }
        )
        connection, cursor = self._connection_with_rows([row])
        repository = GoldRepository(connection=connection, data_mode="live")

        result = repository.get_manager_features(limit=10)

        self.assertEqual(result[0]["manager_id"], "EMP000001")
        self.assertEqual(result[0]["manager_active_flag"], 1)
        self.assertEqual(result[0]["managed_area_count"], 3)
        self.assertEqual(result[0]["average_area_age_days"], 800.2)
        sql, params = cursor.execute.call_args.args
        self.assertIn("FROM dashboard_gold_manager_assignment_view", sql)
        self.assertIn("ORDER BY managed_area_count DESC", sql)
        self.assertEqual(params, [10])

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
