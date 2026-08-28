from copy import deepcopy
import re

from django.conf import settings
from django.db import connection as default_connection


class GoldRepositoryError(RuntimeError):
    """Raised when the Gold manager feature view cannot be read."""


GOLD_COLUMNS = (
    "manager_id",
    "manager_department_name",
    "manager_position_name",
    "manager_active_flag",
    "manager_tenure_days",
    "managed_area_count",
    "managed_top_area_count",
    "managed_parent_area_count",
    "top_level_area_count",
    "average_area_age_days",
    "max_area_age_days",
    "cross_top_area_flag",
)

INTEGER_COLUMNS = {
    "manager_tenure_days",
    "managed_area_count",
    "managed_top_area_count",
    "managed_parent_area_count",
    "top_level_area_count",
    "max_area_age_days",
}

FLAG_COLUMNS = {"manager_active_flag", "cross_top_area_flag"}


def _normalize_flag(value):
    if isinstance(value, bool):
        return int(value)
    normalized = str(value or "").strip().upper()
    if normalized in {"1", "Y", "YES", "TRUE", "ACTIVE"}:
        return 1
    if normalized in {"0", "N", "NO", "FALSE", "INACTIVE", ""}:
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
        top_count = 0 if area_count == 0 else min(area_count, 1 + (index % 4))
        parent_count = 0 if area_count == 0 else min(area_count, 1 + (index % 5))
        top_level_count = 0 if area_count == 0 else min(top_count, index % 3)
        average_age = 280 + ((index * 137) % 1700)
        rows.append(
            {
                "manager_id": f"EMP{index:06d}",
                "manager_department_name": departments[(index - 1) % len(departments)],
                "manager_position_name": positions[(index - 1) % len(positions)],
                "manager_active_flag": 0 if index % 11 == 0 else 1,
                "manager_tenure_days": 420 + ((index * 281) % 4300),
                "managed_area_count": area_count,
                "managed_top_area_count": top_count,
                "managed_parent_area_count": parent_count,
                "top_level_area_count": top_level_count,
                "average_area_age_days": float(average_age),
                "max_area_age_days": average_age + 120 + ((index * 31) % 700),
                "cross_top_area_flag": int(top_count > 1),
            }
        )
    return rows


class GoldRepository:
    """Read-only boundary for the dashboard Gold manager feature view.

    This layer returns normalized database facts only. KPI calculation,
    outlier signals and presentation shaping belong to ``gold_services``.
    """

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
        normalized["manager_id"] = str(normalized.get("manager_id") or "").strip()
        normalized["manager_department_name"] = str(
            normalized.get("manager_department_name") or "미지정"
        ).strip()
        normalized["manager_position_name"] = str(
            normalized.get("manager_position_name") or "미지정"
        ).strip()

        for column in INTEGER_COLUMNS:
            try:
                normalized[column] = int(normalized.get(column) or 0)
            except (TypeError, ValueError):
                normalized[column] = 0

        try:
            normalized["average_area_age_days"] = round(
                float(normalized.get("average_area_age_days") or 0),
                1,
            )
        except (TypeError, ValueError):
            normalized["average_area_age_days"] = 0.0

        for column in FLAG_COLUMNS:
            normalized[column] = _normalize_flag(normalized.get(column))
        return normalized

    def get_manager_features(self, limit=2000):
        safe_limit = max(1, min(int(limit), 5000))
        if self.data_mode != "live":
            return [deepcopy(row) for row in _sample_gold_features()[:safe_limit]]

        try:
            with self.connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT {', '.join(GOLD_COLUMNS)} "
                    f"FROM {self.view_name} "
                    "ORDER BY managed_area_count DESC, manager_id ASC LIMIT %s",
                    [safe_limit],
                )
                columns = [description[0] for description in cursor.description]
                rows = [dict(zip(columns, values)) for values in cursor.fetchall()]
        except Exception as exc:
            raise GoldRepositoryError("MySQL Gold manager feature query failed.") from exc

        return [self._normalize_row(row) for row in rows]
