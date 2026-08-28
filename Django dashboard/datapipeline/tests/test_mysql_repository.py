from datetime import datetime, timedelta, timezone as datetime_timezone
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from datapipeline.repository.mysql_repository import (
    COUNT_COLUMNS,
    RUN_COLUMNS,
    PipelineRepository,
    PipelineRepositoryError,
    parse_run_id_started_at,
)


class MySQLRepositoryTests(SimpleTestCase):
    def _connection_with_rows(self, rows):
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.description = [(column,) for column in RUN_COLUMNS]
        cursor.fetchall.return_value = [
            tuple(row.get(column) for column in RUN_COLUMNS) for row in rows
        ]
        return connection, cursor

    def test_run_id_timestamp_is_parsed_as_utc(self):
        parsed = parse_run_id_started_at(
            "run-final-001-full-row-20260827T104049Z-7428bef9"
        )

        self.assertEqual(
            parsed,
            datetime(2026, 8, 27, 10, 40, 49, tzinfo=datetime_timezone.utc),
        )
        self.assertIsNone(parse_run_id_started_at("run-without-time"))
        self.assertIsNone(parse_run_id_started_at("run-20269999T999999Z"))

    def test_row_normalization_casts_counts_status_and_falls_back_to_run_id_time(self):
        row = {column: None for column in RUN_COLUMNS}
        row.update(
            {
                "run_id": "run-20260827T104049Z-x",
                "raw_row_count": "16",
                "standardization_accepted_count": "14",
                "batch_status": "success",
            }
        )

        normalized = PipelineRepository._normalize_row(row)

        self.assertEqual(normalized["raw_row_count"], 16)
        self.assertEqual(normalized["standardization_accepted_count"], 14)
        self.assertTrue(all(isinstance(normalized[key], int) for key in COUNT_COLUMNS))
        self.assertEqual(normalized["batch_status"], "SUCCESS")
        self.assertEqual(
            normalized["started_at"],
            datetime(2026, 8, 27, 10, 40, 49, tzinfo=datetime_timezone.utc),
        )

    def test_live_latest_query_returns_normalized_view_row(self):
        row = {column: None for column in RUN_COLUMNS}
        row.update(
            {
                "run_id": "run-20260827T104049Z-x",
                "raw_row_count": 16,
                "batch_status": "success",
            }
        )
        connection, cursor = self._connection_with_rows([row])
        repository = PipelineRepository(connection=connection, data_mode="live")

        result = repository.get_latest_run_summary()

        self.assertEqual(result["raw_row_count"], 16)
        self.assertEqual(result["batch_status"], "SUCCESS")
        sql, params = cursor.execute.call_args.args
        self.assertIn("FROM dashboard_pipeline_run_view", sql)
        self.assertIn("ORDER BY started_at DESC LIMIT 1", sql)
        self.assertEqual(params, [])

    def test_live_history_clamps_limit_to_safe_range(self):
        connection, cursor = self._connection_with_rows([])
        repository = PipelineRepository(connection=connection, data_mode="live")

        repository.get_run_history(limit=0)
        self.assertEqual(cursor.execute.call_args.args[1], [1])

        repository.get_run_history(limit=101)
        self.assertEqual(cursor.execute.call_args.args[1], [100])

    def test_live_all_run_query_has_no_limit_and_returns_every_view_row(self):
        rows = []
        for index in range(3):
            row = {column: None for column in RUN_COLUMNS}
            row.update(
                {
                    "run_id": f"run-{index}",
                    "raw_row_count": index + 1,
                    "batch_status": "SUCCESS",
                }
            )
            rows.append(row)
        connection, cursor = self._connection_with_rows(rows)
        repository = PipelineRepository(connection=connection, data_mode="live")

        result = repository.get_all_run_summaries()

        self.assertEqual([item["run_id"] for item in result], ["run-0", "run-1", "run-2"])
        sql, params = cursor.execute.call_args.args
        self.assertIn("FROM dashboard_pipeline_run_view", sql)
        self.assertIn("ORDER BY started_at DESC", sql)
        self.assertNotIn("LIMIT", sql)
        self.assertEqual(params, [])

    def test_query_failure_is_wrapped_in_repository_error(self):
        connection, cursor = self._connection_with_rows([])
        cursor.execute.side_effect = RuntimeError("database offline")
        repository = PipelineRepository(connection=connection, data_mode="live")

        with self.assertRaises(PipelineRepositoryError) as raised:
            repository.get_latest_run_summary()

        self.assertIsInstance(raised.exception.__cause__, RuntimeError)

    def test_sample_mode_refreshes_latest_run_without_opening_database_connection(self):
        connection = MagicMock()
        initial_time = datetime(2026, 8, 28, 10, 0, tzinfo=datetime_timezone.utc)
        refreshed_time = initial_time + timedelta(minutes=30)
        with patch(
            "datapipeline.repository.mysql_repository.timezone.now",
            return_value=initial_time,
        ):
            repository = PipelineRepository(connection=connection, data_mode="sample")

        with patch(
            "datapipeline.repository.mysql_repository.timezone.now",
            return_value=refreshed_time,
        ):
            latest = repository.get_latest_run_summary()

        self.assertEqual(
            latest["started_at"],
            refreshed_time - timedelta(seconds=75),
        )
        self.assertEqual(len(repository.get_run_history(limit=3)), 3)
        self.assertEqual(len(repository.get_all_run_summaries()), 60)
        self.assertEqual(repository.get_failed_runs(), [])
        connection.cursor.assert_not_called()
