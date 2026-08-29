import re
from copy import deepcopy
from datetime import datetime, timedelta, timezone as datetime_timezone

from django.conf import settings
from django.db import connection as default_connection
from django.utils import timezone


class PipelineRepositoryError(RuntimeError):
    """Raised when MySQL pipeline facts cannot be read."""


RUN_ID_TIMESTAMP_PATTERN = re.compile(r"(?P<timestamp>\d{8}T\d{6}Z)")

RUN_COLUMNS = (
    "run_id",
    "raw_row_count",
    "standardization_accepted_count",
    "standardization_rejected_count",
    "final_accepted_count",
    "final_rejected_count",
    "manager_target_count",
    "manager_loaded_count",
    "top_area_target_count",
    "top_area_loaded_count",
    "area_target_count",
    "area_loaded_count",
    "started_at",
    "completed_at",
    "batch_status",
    "error_message",
    "created_at",
    "updated_at",
)

COUNT_COLUMNS = {
    "raw_row_count",
    "standardization_accepted_count",
    "standardization_rejected_count",
    "final_accepted_count",
    "final_rejected_count",
    "manager_target_count",
    "manager_loaded_count",
    "top_area_target_count",
    "top_area_loaded_count",
    "area_target_count",
    "area_loaded_count",
}


def parse_run_id_started_at(run_id):
    """Return the guaranteed UTC timestamp embedded in a run id, if present."""
    match = RUN_ID_TIMESTAMP_PATTERN.search(str(run_id or ""))
    if not match:
        return None
    try:
        return datetime.strptime(
            match.group("timestamp"),
            "%Y%m%dT%H%M%SZ",
        ).replace(tzinfo=datetime_timezone.utc)
    except ValueError:
        return None


def _sample_run(index=0, anchor=None):
    now = (anchor or timezone.now()).replace(microsecond=0)
    started_at = now - timedelta(minutes=index * 3, seconds=75)
    completed_at = started_at + timedelta(seconds=48 + index % 5)
    standard_rejected = [2, 1, 3, 2, 4, 1, 2, 0, 3, 1, 2, 1][index % 12]
    final_rejected = [1, 0, 1, 1, 0, 1, 0, 1, 1, 0, 1, 0][index % 12]
    raw_count = 16
    standard_accepted = raw_count - standard_rejected
    final_accepted = standard_accepted - final_rejected
    utc_stamp = started_at.astimezone(datetime_timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    return {
        "run_id": f"run-sample-full-row-{utc_stamp}-{index:04d}",
        "raw_row_count": raw_count,
        "standardization_accepted_count": standard_accepted,
        "standardization_rejected_count": standard_rejected,
        "final_accepted_count": final_accepted,
        "final_rejected_count": final_rejected,
        "manager_target_count": 5,
        "manager_loaded_count": 5,
        "top_area_target_count": 2,
        "top_area_loaded_count": 2,
        "area_target_count": max(final_accepted, 0),
        "area_loaded_count": max(final_accepted, 0),
        "started_at": started_at,
        "completed_at": completed_at,
        "batch_status": "SUCCESS",
        "error_message": None,
        "created_at": started_at,
        "updated_at": completed_at,
    }


class PipelineRepository:
    """Read-only boundary for ``dashboard_pipeline_run_view``.

    The repository returns batch facts only. Rates, reconciliation and alert
    decisions belong to the service layer.
    """

    VIEW_NAME = "dashboard_pipeline_run_view"

    def __init__(self, connection=None, data_mode=None):
        self._connection = connection
        self.data_mode = (data_mode or settings.DASHBOARD_DATA_MODE).lower()
        self._sample_anchor = timezone.now().replace(microsecond=0)

    @property
    def connection(self):
        return self._connection or default_connection

    @staticmethod
    def _normalize_row(row):
        if row is None:
            return None

        normalized = {column: row.get(column) for column in RUN_COLUMNS}
        for column in COUNT_COLUMNS:
            normalized[column] = int(normalized.get(column) or 0)
        normalized["run_id"] = str(normalized.get("run_id") or "")
        normalized["batch_status"] = str(normalized.get("batch_status") or "UNKNOWN").upper()

        if normalized["started_at"] is None:
            normalized["started_at"] = parse_run_id_started_at(normalized["run_id"])
        return normalized

    def _fetch_all(self, sql, params=None):
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(sql, params or [])
                columns = [description[0] for description in cursor.description]
                return [dict(zip(columns, values)) for values in cursor.fetchall()]
        except Exception as exc:
            raise PipelineRepositoryError("MySQL pipeline summary query failed.") from exc

    def get_latest_run_summary(self):
        if self.data_mode != "live":
            # Demo services live for the lifetime of the Django process. Refresh
            # the sample anchor per request so demo data never becomes stale.
            self._sample_anchor = timezone.now().replace(microsecond=0)
            return deepcopy(_sample_run(anchor=self._sample_anchor))

        rows = self._fetch_all(
            f"SELECT {', '.join(RUN_COLUMNS)} "
            f"FROM {self.VIEW_NAME} "
            "ORDER BY started_at DESC LIMIT 1"
        )
        return self._normalize_row(rows[0]) if rows else None

    def get_run_summary(self, run_id):
        if self.data_mode != "live":
            for run in self.get_run_history(limit=100):
                if run["run_id"] == run_id:
                    return run
            return None

        rows = self._fetch_all(
            f"SELECT {', '.join(RUN_COLUMNS)} "
            f"FROM {self.VIEW_NAME} WHERE run_id = %s LIMIT 1",
            [run_id],
        )
        return self._normalize_row(rows[0]) if rows else None

    def get_run_history(self, limit=12):
        safe_limit = max(1, min(int(limit), 100))
        if self.data_mode != "live":
            return [deepcopy(_sample_run(index, anchor=self._sample_anchor)) for index in range(safe_limit)]

        rows = self._fetch_all(
            f"SELECT {', '.join(RUN_COLUMNS)} "
            f"FROM {self.VIEW_NAME} "
            "ORDER BY started_at DESC LIMIT %s",
            [safe_limit],
        )
        return [self._normalize_row(row) for row in rows]

    def get_all_run_summaries(self):
        """Return every batch row used by the integrated dashboard.

        The main dashboard reconciles MongoDB documents against the complete
        set of MySQL run IDs. Detail dashboards continue to use the bounded
        history methods above so their charts stay compact.
        """
        if self.data_mode != "live":
            return [
                deepcopy(_sample_run(index, anchor=self._sample_anchor))
                for index in range(60)
            ]

        rows = self._fetch_all(
            f"SELECT {', '.join(RUN_COLUMNS)} "
            f"FROM {self.VIEW_NAME} "
            "ORDER BY started_at DESC"
        )
        return [self._normalize_row(row) for row in rows]

    def get_failed_runs(self, limit=10):
        safe_limit = max(1, min(int(limit), 100))
        if self.data_mode != "live":
            return []

        rows = self._fetch_all(
            f"SELECT {', '.join(RUN_COLUMNS)} "
            f"FROM {self.VIEW_NAME} "
            "WHERE batch_status IN ('PARTIAL_FAILURE', 'FAILED') "
            "ORDER BY started_at DESC LIMIT %s",
            [safe_limit],
        )
        return [self._normalize_row(row) for row in rows]
