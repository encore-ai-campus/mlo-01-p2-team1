from collections import Counter, defaultdict
from math import ceil
from statistics import fmean

from django.conf import settings
from django.utils import timezone

from datapipeline.repository.gold_repository import GoldRepository, GoldRepositoryError
from datapipeline.service.mysql_services import alert_status, make_alert, percentage


def _average(values):
    values = list(values)
    return round(fmean(values), 1) if values else 0.0


def _percentile(values, percentile):
    ordered = sorted(values)
    if not ordered:
        return 0
    index = max(0, min(len(ordered) - 1, ceil(len(ordered) * percentile) - 1))
    return ordered[index]


def evaluate_gold_alerts(rows):
    alerts = []
    manager_ids = [row["manager_id"] for row in rows if row["manager_id"]]
    duplicates = [manager_id for manager_id, count in Counter(manager_ids).items() if count > 1]
    if duplicates:
        alerts.append(
            make_alert(
                "CRITICAL",
                "DUPLICATE_GOLD_MANAGER",
                "Gold View에 동일한 manager_id가 중복되어 있습니다.",
                source="GOLD",
                actual=len(duplicates),
            )
        )

    invalid_rows = 0
    flag_mismatches = 0
    age_mismatches = 0
    for row in rows:
        counts = (
            row["managed_area_count"],
            row["managed_top_area_count"],
            row["managed_parent_area_count"],
            row["top_level_area_count"],
            row["manager_tenure_days"],
            row["average_area_age_days"],
            row["max_area_age_days"],
        )
        if (
            any(value < 0 for value in counts)
            or row["managed_top_area_count"] > row["managed_area_count"]
            or row["managed_parent_area_count"] > row["managed_area_count"]
            or row["top_level_area_count"] > row["managed_top_area_count"]
            or row["manager_active_flag"] not in {0, 1}
        ):
            invalid_rows += 1
        if row["cross_top_area_flag"] != int(row["managed_top_area_count"] > 1):
            flag_mismatches += 1
        if row["average_area_age_days"] > row["max_area_age_days"]:
            age_mismatches += 1

    if invalid_rows:
        alerts.append(
            make_alert(
                "CRITICAL",
                "INVALID_GOLD_FEATURE",
                "Gold Feature 범위 또는 계층 건수에 모순이 있습니다.",
                source="GOLD",
                actual=invalid_rows,
            )
        )
    if flag_mismatches:
        alerts.append(
            make_alert(
                "CRITICAL",
                "CROSS_TOP_FLAG_MISMATCH",
                "cross_top_area_flag와 Top Area 건수가 일치하지 않습니다.",
                source="GOLD",
                actual=flag_mismatches,
            )
        )
    if age_mismatches:
        alerts.append(
            make_alert(
                "WARNING",
                "AREA_AGE_MISMATCH",
                "평균 Area 운영 기간이 최대 운영 기간보다 큰 행이 있습니다.",
                source="GOLD",
                actual=age_mismatches,
            )
        )
    return alerts


def build_gold_dashboard_data(rows):
    total = len(rows)
    active_count = sum(row["manager_active_flag"] == 1 for row in rows)
    cross_top_count = sum(row["cross_top_area_flag"] == 1 for row in rows)
    unassigned_count = sum(row["managed_area_count"] == 0 for row in rows)
    max_area_count = max((row["managed_area_count"] for row in rows), default=0)
    average_area_count = _average(row["managed_area_count"] for row in rows)
    workload_threshold = _percentile(
        [row["managed_area_count"] for row in rows],
        0.9,
    )

    feature_rows = []
    for row in rows:
        item = dict(row)
        item.update(
            {
                "active_label": "ACTIVE" if row["manager_active_flag"] == 1 else "INACTIVE",
                "cross_top_label": "MULTI-TOP" if row["cross_top_area_flag"] == 1 else "SINGLE",
                "tenure_years": round(row["manager_tenure_days"] / 365, 1),
                "relative_area_rate": percentage(
                    row["managed_area_count"],
                    max_area_count,
                ),
                "review_signal": (
                    "UNASSIGNED"
                    if row["managed_area_count"] == 0
                    else "HIGH LOAD"
                    if workload_threshold and row["managed_area_count"] >= workload_threshold
                    else "CROSS-TOP"
                    if row["cross_top_area_flag"] == 1
                    else "NORMAL"
                ),
            }
        )
        feature_rows.append(item)

    department_facts = defaultdict(lambda: {"managers": 0, "areas": 0, "cross_top": 0})
    for row in rows:
        department = row["manager_department_name"]
        department_facts[department]["managers"] += 1
        department_facts[department]["areas"] += row["managed_area_count"]
        department_facts[department]["cross_top"] += row["cross_top_area_flag"] == 1

    departments = []
    for name, facts in department_facts.items():
        departments.append(
            {
                "name": name,
                **facts,
                "average_areas": round(facts["areas"] / facts["managers"], 1),
                "cross_top_rate": percentage(facts["cross_top"], facts["managers"]),
            }
        )
    departments.sort(key=lambda item: (-item["average_areas"], item["name"]))

    area_distribution = Counter()
    for row in rows:
        count = row["managed_area_count"]
        label = str(count) if count <= 5 else "6+"
        area_distribution[label] += 1
    distribution_labels = ["0", "1", "2", "3", "4", "5", "6+"]

    top_workloads = sorted(
        feature_rows,
        key=lambda item: (
            -item["managed_area_count"],
            -item["managed_top_area_count"],
            item["manager_id"],
        ),
    )[:8]
    focus = top_workloads[0] if top_workloads else None
    radar_indicators = [
        {"name": "근속일", "max": max(1, max((row["manager_tenure_days"] for row in rows), default=1))},
        {"name": "Area", "max": max(1, max_area_count)},
        {"name": "Top Area", "max": max(1, max((row["managed_top_area_count"] for row in rows), default=1))},
        {"name": "Parent", "max": max(1, max((row["managed_parent_area_count"] for row in rows), default=1))},
        {"name": "Area 평균연령", "max": max(1, max((row["average_area_age_days"] for row in rows), default=1))},
    ]
    radar_keys = (
        "manager_tenure_days",
        "managed_area_count",
        "managed_top_area_count",
        "managed_parent_area_count",
        "average_area_age_days",
    )
    radar_datasets = [
        {
            "label": "전체 평균",
            "color": "#20d9ff",
            "values": [_average(row[key] for row in rows) for key in radar_keys],
        }
    ]
    if focus:
        radar_datasets.append(
            {
                "label": focus["manager_id"],
                "color": "#f7c948",
                "values": [focus[key] for key in radar_keys],
            }
        )

    return {
        "total_managers": total,
        "active_count": active_count,
        "active_rate": percentage(active_count, total),
        "cross_top_count": cross_top_count,
        "cross_top_rate": percentage(cross_top_count, total),
        "unassigned_count": unassigned_count,
        "unassigned_rate": percentage(unassigned_count, total),
        "average_area_count": average_area_count,
        "average_area_rate": percentage(average_area_count, max_area_count),
        "average_tenure_days": _average(row["manager_tenure_days"] for row in rows),
        "max_area_count": max_area_count,
        "workload_threshold": workload_threshold,
        "departments": departments,
        "positions": sorted({row["manager_position_name"] for row in rows}),
        "feature_rows": feature_rows,
        "top_workloads": top_workloads,
        "scene_managers": [
            {
                "managerId": row["manager_id"],
                "department": row["manager_department_name"],
                "position": row["manager_position_name"],
                "active": row["manager_active_flag"],
                "tenureDays": row["manager_tenure_days"],
                "areaCount": row["managed_area_count"],
                "topAreaCount": row["managed_top_area_count"],
                "crossTop": row["cross_top_area_flag"],
            }
            for row in feature_rows[:120]
        ],
        "chart_payload": {
            "goldAreaDistribution": {
                "type": "bar",
                "labels": distribution_labels,
                "datasets": [
                    {
                        "label": "담당자",
                        "color": "#f7c948",
                        "values": [area_distribution[label] for label in distribution_labels],
                    }
                ],
            },
            "goldDepartmentLoad": {
                "type": "bar",
                "horizontal": True,
                "labels": [item["name"] for item in departments[:8]],
                "datasets": [
                    {
                        "label": "평균 담당 Area",
                        "color": "#20d9ff",
                        "values": [item["average_areas"] for item in departments[:8]],
                    }
                ],
            },
            "goldWorkloadMatrix": {
                "type": "scatter",
                "xLabel": "근속 연수",
                "yLabel": "담당 Area",
                "datasets": [
                    {
                        "label": "Manager",
                        "color": "#f7c948",
                        "values": [
                            {
                                "value": [round(row["manager_tenure_days"] / 365, 1), row["managed_area_count"], row["managed_top_area_count"]],
                                "managerId": row["manager_id"],
                                "department": row["manager_department_name"],
                                "crossTop": row["cross_top_area_flag"],
                            }
                            for row in rows
                        ],
                    }
                ],
            },
            "goldActiveOrbit": {
                "type": "doughnut",
                "labels": ["Active", "Inactive"],
                "datasets": [{"values": [active_count, total - active_count], "colors": ["#15e6c1", "#394c62"]}],
                "centerText": f"{percentage(active_count, total)}%",
                "centerLabel": "ACTIVE MANAGERS",
            },
            "goldFeatureRadar": {
                "type": "radar",
                "indicators": radar_indicators,
                "datasets": radar_datasets,
            },
        },
    }


class GoldDashboardService:
    def __init__(self, gold_repository=None):
        self.gold_repository = gold_repository or GoldRepository()

    @staticmethod
    def _base_context():
        return {
            "active_section": "gold",
            "data_mode": "LIVE DATA" if settings.DASHBOARD_DATA_MODE == "live" else "DEMO DATA",
            "updated_at": timezone.localtime().strftime("%Y-%m-%d %H:%M:%S KST"),
        }

    def get_dashboard(self):
        repository_alerts = []
        try:
            rows = self.gold_repository.get_manager_features(limit=2000)
        except GoldRepositoryError:
            rows = []
            repository_alerts.append(
                make_alert(
                    "CRITICAL",
                    "GOLD_VIEW_UNAVAILABLE",
                    "Gold manager feature View를 조회할 수 없습니다.",
                    source="GOLD",
                )
            )

        if not rows and not repository_alerts:
            repository_alerts.append(
                make_alert(
                    "WARNING",
                    "GOLD_VIEW_EMPTY",
                    "Gold manager feature View에 조회 가능한 데이터가 없습니다.",
                    source="GOLD",
                )
            )

        gold = build_gold_dashboard_data(rows)
        alerts = repository_alerts + evaluate_gold_alerts(rows)
        status = alert_status(alerts)
        context = self._base_context()
        context.update(
            {
                "gold": gold,
                "alerts": alerts,
                "overall_status": status,
                "overall_status_label": "정상" if status == "NORMAL" else "경고" if status == "WARNING" else "위험",
                "source_status": "SYNCHRONIZED" if rows else "VIEW WAITING",
                "view_name": self.gold_repository.view_name,
                "chart_payload": gold["chart_payload"],
                "scene_payload": {"managers": gold["scene_managers"]},
                "feature_payload": gold["feature_rows"],
            }
        )
        return context
