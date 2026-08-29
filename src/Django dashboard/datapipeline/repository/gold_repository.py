from copy import deepcopy
import re

from django.conf import settings
from django.db import connection as default_connection


class GoldRepositoryError(RuntimeError):
    """Raised when the Gold manager feature view cannot be read."""


# Live DB contract for dashboard_gold_manager_assignment_view.
GOLD_COLUMNS = (
    "run_id",
    "as_of_datetime",
    "pipeline_completed_at",
    "manager_id",
    "manager_department_name",
    "manager_position_name",
    "manager_active_flag",
    "manager_tenure_days",
    "managed_area_count",
    "workload_score",
    "peer_average_workload_score",
    "peer_average_area_count",
    "workload_ratio",
    "reassignment_required_flag",
    "reassignment_priority",
    "recommended_reassignment_area_count",
    "reassignment_reason_code",
    "reassignment_reason",
    "workload_rule_version",
    "feature_version",
)

INTEGER_COLUMNS = {
    "manager_tenure_days",
    "managed_area_count",
    "recommended_reassignment_area_count",
}
FLOAT_COLUMNS = {
    "workload_score",
    "peer_average_workload_score",
    "peer_average_area_count",
    "workload_ratio",
}
FLAG_COLUMNS = {"manager_active_flag", "reassignment_required_flag"}
DATETIME_COLUMNS = {"as_of_datetime", "pipeline_completed_at"}
TEXT_COLUMNS = set(GOLD_COLUMNS) - INTEGER_COLUMNS - FLOAT_COLUMNS - FLAG_COLUMNS - DATETIME_COLUMNS


def _normalize_flag(value):
    if isinstance(value, bool):
        return int(value)
    normalized = str(value or "").strip().upper()
    if normalized in {"1", "Y", "YES", "TRUE", "ACTIVE", "REQUIRED"}:
        return 1
    if normalized in {"0", "N", "NO", "FALSE", "INACTIVE", "", "NORMAL"}:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return -1


def _sample_gold_features():
    departments = ("기획팀", "분석팀", "생산팀", "법무팀", "플랫폼팀", "데이터팀")
    positions = ("사원", "대리", "과장", "차장", "팀장")
    rows = []
    for index in range(1, 31):
        area_count = (index * 3) % 11
        peer_area = round(4.2 + ((index * 7) % 25) / 10, 2)
        workload_score = round(area_count * (0.85 + (index % 5) * 0.08), 2)
        peer_workload = round(peer_area * 0.95, 2)
        workload_ratio = round(workload_score / peer_workload, 2) if peer_workload else 0.0
        reassignment_required = int(workload_ratio >= 1.2)
        recommended_count = max(0, round(area_count - peer_area)) if reassignment_required else 0
        priority = "HIGH" if workload_ratio >= 1.5 else "MEDIUM" if reassignment_required else "NORMAL"
        rows.append(
            {
                "run_id": "sample-gold-run",
                "as_of_datetime": "2026-08-28T12:00:00",
                "pipeline_completed_at": "2026-08-28T12:02:00",
                "manager_id": f"EMP{index:06d}",
                "manager_department_name": departments[(index - 1) % len(departments)],
                "manager_position_name": positions[(index - 1) % len(positions)],
                "manager_active_flag": 0 if index % 11 == 0 else 1,
                "manager_tenure_days": 420 + ((index * 281) % 4300),
                "managed_area_count": area_count,
                "workload_score": workload_score,
                "peer_average_workload_score": peer_workload,
                "peer_average_area_count": peer_area,
                "workload_ratio": workload_ratio,
                "reassignment_required_flag": reassignment_required,
                "reassignment_priority": priority,
                "recommended_reassignment_area_count": recommended_count,
                "reassignment_reason_code": "WORKLOAD_RATIO_HIGH" if reassignment_required else "",
                "reassignment_reason": "동일 부서 평균 대비 업무 부하가 높습니다." if reassignment_required else "",
                "workload_rule_version": "sample-v1",
                "feature_version": "sample-v1",
            }
        )
    return rows


class GoldRepository:
    """Read-only boundary for the Gold manager workload feature view."""

    DEFAULT_VIEW_NAME = "dashboard_gold_manager_assignment_view"

    def __init__(self, connection=None, data_mode=None, view_name=None):
        self._connection = connection
        self.data_mode = (data_mode or settings.DASHBOARD_DATA_MODE).lower()
        configured_name = view_name or getattr(
            settings,
            "GOLD_DASHBOARD_VIEW",
            self.DEFAULT_VIEW_NAME,
        )
        if not re.fullmatch(r"[A-Za-z0-9_]+", configured_name):
            raise ValueError("Gold dashboard view name contains unsupported characters.")
        self.view_name = configured_name

    @property
    def connection(self):
        return self._connection or default_connection

    @staticmethod
    def _normalize_row(row):
        normalized = {column: row.get(column) for column in GOLD_COLUMNS}

        for column in TEXT_COLUMNS:
            default = "미지정" if column in {"manager_department_name", "manager_position_name"} else ""
            normalized[column] = str(normalized.get(column) or default).strip()

        for column in INTEGER_COLUMNS:
            try:
                normalized[column] = int(normalized.get(column) or 0)
            except (TypeError, ValueError):
                normalized[column] = 0

        for column in FLOAT_COLUMNS:
            try:
                normalized[column] = round(float(normalized.get(column) or 0), 2)
            except (TypeError, ValueError):
                normalized[column] = 0.0

        for column in FLAG_COLUMNS:
            normalized[column] = _normalize_flag(normalized.get(column))

        for column in DATETIME_COLUMNS:
            value = normalized.get(column)
            if hasattr(value, "isoformat"):
                normalized[column] = value.isoformat()
            else:
                normalized[column] = str(value or "").strip()

        return normalized

    def get_manager_features(self, limit=5000):
        safe_limit = max(1, min(int(limit), 5000))
        if self.data_mode != "live":
            return [self._normalize_row(deepcopy(row)) for row in _sample_gold_features()[:safe_limit]]

        try:
            with self.connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT run_id FROM {self.view_name} "
                    "ORDER BY as_of_datetime DESC, pipeline_completed_at DESC, run_id DESC LIMIT 1"
                )
                latest = cursor.fetchone()
                if not latest:
                    return []
                latest_run_id = latest[0]

                cursor.execute(
                    f"SELECT {', '.join(GOLD_COLUMNS)} "
                    f"FROM {self.view_name} "
                    "WHERE run_id = %s "
                    "ORDER BY reassignment_required_flag DESC, workload_ratio DESC, "
                    "managed_area_count DESC, manager_id ASC LIMIT %s",
                    [latest_run_id, safe_limit],
                )
                columns = [description[0] for description in cursor.description]
                rows = [dict(zip(columns, values)) for values in cursor.fetchall()]
        except Exception as exc:
            raise GoldRepositoryError("MySQL Gold manager feature query failed.") from exc

        return [self._normalize_row(row) for row in rows]
