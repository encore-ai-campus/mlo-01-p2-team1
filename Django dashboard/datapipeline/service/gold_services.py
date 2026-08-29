from collections import Counter, defaultdict
from statistics import fmean

from django.conf import settings
from django.utils import timezone

from datapipeline.repository.gold_repository import GoldRepository, GoldRepositoryError
from datapipeline.service.mysql_services import alert_status, make_alert, percentage


PRIORITY_RANK = {
    "CRITICAL": 5,
    "URGENT": 5,
    "HIGH": 4,
    "MEDIUM": 3,
    "LOW": 2,
    "NORMAL": 1,
    "NONE": 0,
    "": 0,
}


def _average(values):
    values = list(values)
    return round(fmean(values), 2) if values else 0.0


def evaluate_gold_alerts(rows):
    alerts = []
    manager_ids = [row["manager_id"] for row in rows if row["manager_id"]]
    duplicates = [manager_id for manager_id, count in Counter(manager_ids).items() if count > 1]
    if duplicates:
        alerts.append(
            make_alert(
                "CRITICAL",
                "DUPLICATE_GOLD_MANAGER",
                "동일 Gold snapshot에 manager_id가 중복되어 있습니다.",
                source="GOLD",
                actual=len(duplicates),
            )
        )

    run_ids = {row["run_id"] for row in rows if row["run_id"]}
    if len(run_ids) > 1:
        alerts.append(
            make_alert(
                "CRITICAL",
                "MULTIPLE_GOLD_RUNS",
                "Gold 화면 입력에 서로 다른 run_id가 함께 포함되어 있습니다.",
                source="GOLD",
                actual=len(run_ids),
            )
        )

    invalid_rows = 0
    missing_reason_rows = 0
    for row in rows:
        numeric_values = (
            row["manager_tenure_days"],
            row["managed_area_count"],
            row["workload_score"],
            row["peer_average_workload_score"],
            row["peer_average_area_count"],
            row["workload_ratio"],
            row["recommended_reassignment_area_count"],
        )
        if (
            not row["run_id"]
            or not row["manager_id"]
            or any(value < 0 for value in numeric_values)
            or row["manager_active_flag"] not in {0, 1}
            or row["reassignment_required_flag"] not in {0, 1}
        ):
            invalid_rows += 1
        if row["reassignment_required_flag"] == 1 and not row["reassignment_reason"]:
            missing_reason_rows += 1

    if invalid_rows:
        alerts.append(
            make_alert(
                "CRITICAL",
                "INVALID_GOLD_FEATURE",
                "Gold workload Feature의 식별자·범위·플래그에 유효하지 않은 값이 있습니다.",
                source="GOLD",
                actual=invalid_rows,
            )
        )
    if missing_reason_rows:
        alerts.append(
            make_alert(
                "WARNING",
                "MISSING_REASSIGNMENT_REASON",
                "재배치 필요 신호에 사유가 없는 담당자가 있습니다.",
                source="GOLD",
                actual=missing_reason_rows,
            )
        )
    return alerts


def build_gold_dashboard_data(rows):
    total = len(rows)
    active_count = sum(row["manager_active_flag"] == 1 for row in rows)
    reassignment_required_count = sum(row["reassignment_required_flag"] == 1 for row in rows)
    unassigned_count = sum(row["managed_area_count"] == 0 for row in rows)
    max_area_count = max((row["managed_area_count"] for row in rows), default=0)
    average_area_count = _average(row["managed_area_count"] for row in rows)
    max_workload_score = max((row["workload_score"] for row in rows), default=0.0)
    max_workload_ratio = max((row["workload_ratio"] for row in rows), default=0.0)
    run_ids = sorted({row["run_id"] for row in rows if row["run_id"]})

    feature_rows = []
    for row in rows:
        item = dict(row)
        priority = (row["reassignment_priority"] or "").upper()
        if row["reassignment_required_flag"] == 1:
            review_signal = priority if priority not in {"", "NONE", "NORMAL"} else "REASSIGNMENT"
        elif row["managed_area_count"] == 0:
            review_signal = "UNASSIGNED"
        else:
            review_signal = "NORMAL"
        item.update(
            {
                "active_label": "ACTIVE" if row["manager_active_flag"] == 1 else "INACTIVE",
                "reassignment_label": "REQUIRED" if row["reassignment_required_flag"] == 1 else "NORMAL",
                "tenure_years": round(row["manager_tenure_days"] / 365, 1),
                "relative_area_rate": percentage(row["managed_area_count"], max_area_count),
                "review_signal": review_signal,
            }
        )
        feature_rows.append(item)

    department_facts = defaultdict(lambda: {"managers": 0, "areas": 0, "reassignment": 0, "workload": 0.0})
    for row in rows:
        department = row["manager_department_name"]
        department_facts[department]["managers"] += 1
        department_facts[department]["areas"] += row["managed_area_count"]
        department_facts[department]["reassignment"] += row["reassignment_required_flag"] == 1
        department_facts[department]["workload"] += row["workload_score"]

    departments = []
    for name, facts in department_facts.items():
        departments.append(
            {
                "name": name,
                **facts,
                "average_areas": round(facts["areas"] / facts["managers"], 2),
                "average_workload": round(facts["workload"] / facts["managers"], 2),
                "reassignment_rate": percentage(facts["reassignment"], facts["managers"]),
            }
        )
    departments.sort(key=lambda item: (-item["average_workload"], item["name"]))

    area_distribution = Counter()
    for row in rows:
        count = row["managed_area_count"]
        label = str(count) if count <= 5 else "6+"
        area_distribution[label] += 1
    distribution_labels = ["0", "1", "2", "3", "4", "5", "6+"]

    top_workloads = sorted(
        feature_rows,
        key=lambda item: (
            -item["reassignment_required_flag"],
            -PRIORITY_RANK.get((item["reassignment_priority"] or "").upper(), 0),
            -item["workload_ratio"],
            -item["workload_score"],
            -item["managed_area_count"],
            item["manager_id"],
        ),
    )[:8]
    focus = top_workloads[0] if top_workloads else None

    radar_keys = (
        "manager_tenure_days",
        "managed_area_count",
        "workload_score",
        "workload_ratio",
        "recommended_reassignment_area_count",
    )
    radar_indicators = [
        {"name": "근속일", "max": max(1, max((row["manager_tenure_days"] for row in rows), default=1))},
        {"name": "Area", "max": max(1, max_area_count)},
        {"name": "Workload", "max": max(1, max_workload_score)},
        {"name": "Ratio", "max": max(1, max_workload_ratio)},
        {
            "name": "재배치 권고",
            "max": max(1, max((row["recommended_reassignment_area_count"] for row in rows), default=1)),
        },
    ]
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
        "run_id": run_ids[0] if len(run_ids) == 1 else "",
        "as_of_datetime": max((row["as_of_datetime"] for row in rows), default=""),
        "pipeline_completed_at": max((row["pipeline_completed_at"] for row in rows), default=""),
        "feature_version": next((row["feature_version"] for row in rows if row["feature_version"]), ""),
        "workload_rule_version": next((row["workload_rule_version"] for row in rows if row["workload_rule_version"]), ""),
        "total_managers": total,
        "active_count": active_count,
        "active_rate": percentage(active_count, total),
        "reassignment_required_count": reassignment_required_count,
        "reassignment_required_rate": percentage(reassignment_required_count, total),
        "unassigned_count": unassigned_count,
        "unassigned_rate": percentage(unassigned_count, total),
        "average_area_count": average_area_count,
        "average_area_rate": percentage(average_area_count, max_area_count),
        "average_tenure_days": _average(row["manager_tenure_days"] for row in rows),
        "average_workload_score": _average(row["workload_score"] for row in rows),
        "average_workload_ratio": _average(row["workload_ratio"] for row in rows),
        "max_area_count": max_area_count,
        "max_workload_score": max_workload_score,
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
                "workloadScore": row["workload_score"],
                "workloadRatio": row["workload_ratio"],
                "reassignmentRequired": row["reassignment_required_flag"],
                "priority": row["reassignment_priority"],
                "recommendedAreaCount": row["recommended_reassignment_area_count"],
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
                        "label": "평균 Workload",
                        "color": "#20d9ff",
                        "values": [item["average_workload"] for item in departments[:8]],
                    }
                ],
            },
            "goldWorkloadMatrix": {
                "type": "scatter",
                "xLabel": "근속 연수",
                "yLabel": "Workload score",
                "datasets": [
                    {
                        "label": "Manager",
                        "color": "#f7c948",
                        "values": [
                            {
                                "value": [
                                    round(row["manager_tenure_days"] / 365, 1),
                                    row["workload_score"],
                                    row["workload_ratio"],
                                ],
                                "managerId": row["manager_id"],
                                "department": row["manager_department_name"],
                                "reassignmentRequired": row["reassignment_required_flag"],
                                "priority": row["reassignment_priority"],
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
            rows = self.gold_repository.get_manager_features(limit=5000)
        except GoldRepositoryError:
            rows = []
            repository_alerts.append(
                make_alert(
                    "CRITICAL",
                    "GOLD_VIEW_UNAVAILABLE",
                    "Gold manager workload View를 조회할 수 없습니다.",
                    source="GOLD",
                )
            )

        if not rows and not repository_alerts:
            repository_alerts.append(
                make_alert(
                    "WARNING",
                    "GOLD_VIEW_EMPTY",
                    "Gold manager workload View에 조회 가능한 데이터가 없습니다.",
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
