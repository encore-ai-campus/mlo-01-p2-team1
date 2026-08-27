from django.conf import settings
from django.utils import timezone

from datapipeline.repository.mongodb_repository import MongoRepository, MongoRepositoryError
from datapipeline.repository.mysql_repository import PipelineRepository, PipelineRepositoryError
from datapipeline.service.mysql_services import (
    DEFAULT_ALERT_POLICY,
    TERMINAL_STATUSES,
    alert_status,
    empty_run_summary,
    evaluate_mysql_alerts,
    make_alert,
    percentage,
    run_started_at,
)


def empty_mongo_facts(run_id=None):
    empty_stage = lambda stage: {
        "stage": stage,
        "collection": settings.MONGODB[
            "STANDARDIZATION_REJECTED_COLLECTION"
            if stage == "standardization"
            else "NORMALIZATION_REJECTED_COLLECTION"
        ],
        "rejected_rows": 0,
        "error_occurrences": 0,
        "rows_without_errors": 0,
        "malformed_error_count": 0,
        "duplicate_document_count": 0,
        "error_codes": [],
        "error_columns": [],
        "reprocess_statuses": [],
        "recent_rejections": [],
    }
    return {
        "run_id": run_id,
        "run_started_at": None,
        "stages": {
            "standardization": empty_stage("standardization"),
            "normalization": empty_stage("normalization"),
        },
        "total_rejected_rows": 0,
        "total_error_occurrences": 0,
        "rows_without_errors": 0,
        "malformed_error_count": 0,
        "duplicate_document_count": 0,
        "error_codes": [],
        "error_columns": [],
        "reprocess_statuses": [],
        "recent_rejections": [],
    }


def evaluate_mongodb_alerts(run, mongo_facts, policy=None):
    policy = {**DEFAULT_ALERT_POLICY, **(policy or {})}
    run_id = run.get("run_id")
    status = str(run.get("batch_status") or "UNKNOWN").upper()
    alerts = []
    standard_actual = mongo_facts["stages"]["standardization"]["rejected_rows"]
    normalization_actual = mongo_facts["stages"]["normalization"]["rejected_rows"]
    comparisons = (
        ("STANDARDIZATION", standard_actual, run["standardization_rejected_count"]),
        ("NORMALIZATION", normalization_actual, run["final_rejected_count"]),
    )

    if status in TERMINAL_STATUSES:
        for stage, actual, expected in comparisons:
            if actual == expected:
                continue
            level = "CRITICAL" if status == "SUCCESS" else "WARNING"
            alerts.append(
                make_alert(
                    level,
                    f"{stage}_MONGO_COUNT_MISMATCH",
                    f"{stage.lower()} rejected 예상 {expected}건과 MongoDB 저장 {actual}건이 일치하지 않습니다.",
                    source="MONGODB",
                    run_id=run_id,
                    stage=stage,
                    actual=actual,
                    expected=expected,
                    delta=actual - expected,
                )
            )

    if mongo_facts["rows_without_errors"]:
        alerts.append(make_alert("WARNING", "REJECTED_WITHOUT_ERRORS", "반려 문서에 errors가 없는 행이 있습니다.", source="MONGODB", run_id=run_id, actual=mongo_facts["rows_without_errors"]))
    if mongo_facts["malformed_error_count"]:
        alerts.append(make_alert("WARNING", "MALFORMED_ERROR_CODE", "형식이 잘못되거나 단계와 불일치하는 오류 코드가 있습니다.", source="MONGODB", run_id=run_id, actual=mongo_facts["malformed_error_count"]))
    if mongo_facts["duplicate_document_count"]:
        alerts.append(make_alert("CRITICAL", "DUPLICATE_REJECTED_DOCUMENT", "동일 배치·단계·원천 행의 중복 rejected 문서가 있습니다.", source="MONGODB", run_id=run_id, actual=mongo_facts["duplicate_document_count"]))

    for reason in mongo_facts["error_codes"]:
        if reason["occurrence_count"] >= policy["error_code_warning_count"]:
            alerts.append(make_alert("WARNING", "ERROR_CODE_SPIKE", f"{reason['code']} 오류가 한 배치에서 {reason['occurrence_count']}회 발생했습니다.", source="MONGODB", run_id=run_id, error_code=reason["code"], actual=reason["occurrence_count"]))
            break
    return alerts


def _format_batch_time(value):
    return timezone.localtime(value).strftime("%H:%M") if value else "--:--"


def build_mongodb_dashboard_data(run, mongo_facts):
    standard = mongo_facts["stages"]["standardization"]
    normalization = mongo_facts["stages"]["normalization"]
    standard_expected = run["standardization_rejected_count"]
    normalization_expected = run["final_rejected_count"]
    total_expected = standard_expected + normalization_expected
    total_loaded = standard["rejected_rows"] + normalization["rejected_rows"]
    total_errors = mongo_facts["total_error_occurrences"]
    reasons = [
        {
            "code": item["code"],
            "label": item["label"],
            "count": item["occurrence_count"],
            "affected_rows": item["affected_row_count"],
            "rate": percentage(item["occurrence_count"], total_errors),
        }
        for item in mongo_facts["error_codes"]
    ]
    top_reason = reasons[0] if reasons else {"code": "NO_ERROR", "label": "오류 없음", "count": 0, "rate": 0.0}
    batch_time = run_started_at(run) or mongo_facts.get("run_started_at")
    recent_rejections = [
        {
            "time": _format_batch_time(item.get("run_started_at") or batch_time),
            "record": item["record"],
            "stage": "표준화" if item["stage"] == "standardization" else "정규화",
            "reason": item["reason"],
            "column": item["column"],
            "reprocess_status": item["reprocess_status"],
        }
        for item in mongo_facts["recent_rejections"]
    ]
    collections = [
        {
            "name": standard["collection"],
            "stage": "표준화",
            "loaded": standard["rejected_rows"],
            "expected": standard_expected,
            "rate": percentage(standard["rejected_rows"], standard_expected, empty_value=100.0 if standard["rejected_rows"] == 0 else 0.0),
            "status": "정상" if standard["rejected_rows"] == standard_expected else "확인 필요",
        },
        {
            "name": normalization["collection"],
            "stage": "정규화",
            "loaded": normalization["rejected_rows"],
            "expected": normalization_expected,
            "rate": percentage(normalization["rejected_rows"], normalization_expected, empty_value=100.0 if normalization["rejected_rows"] == 0 else 0.0),
            "status": "정상" if normalization["rejected_rows"] == normalization_expected else "확인 필요",
        },
    ]
    return {
        "run_id": run.get("run_id"),
        "standardized": {
            "rejected": standard["rejected_rows"],
            "input": run["raw_row_count"],
            "rate": percentage(standard["rejected_rows"], run["raw_row_count"]),
            "errors": standard["error_occurrences"],
        },
        "normalized": {
            "rejected": normalization["rejected_rows"],
            "input": run["standardization_accepted_count"],
            "rate": percentage(normalization["rejected_rows"], run["standardization_accepted_count"]),
            "errors": normalization["error_occurrences"],
        },
        "load": {
            "loaded": total_loaded,
            "expected": total_expected,
            "rate": percentage(total_loaded, total_expected, empty_value=100.0 if total_loaded == 0 else 0.0),
        },
        "freshness": _format_batch_time(batch_time),
        "collections": collections,
        "reasons": reasons,
        "top_reason": top_reason,
        "recent_rejections": recent_rejections,
        "total_error_occurrences": total_errors,
        "rows_without_errors": mongo_facts["rows_without_errors"],
        "error_columns": mongo_facts["error_columns"],
        "reprocess_statuses": mongo_facts["reprocess_statuses"],
    }


class MongoDBDashboardService:
    """Build rejected-data KPIs and cross-database reconciliation warnings."""

    def __init__(self, mongodb_repository=None, mysql_repository=None, alert_policy=None):
        self.mongodb_repository = mongodb_repository or MongoRepository()
        self.mysql_repository = mysql_repository or PipelineRepository()
        self.alert_policy = alert_policy

    @staticmethod
    def _base_context():
        return {
            "active_section": "mongodb",
            "data_mode": "LIVE DATA" if settings.DASHBOARD_DATA_MODE == "live" else "DEMO DATA",
            "updated_at": timezone.localtime().strftime("%Y-%m-%d %H:%M:%S KST"),
        }

    def get_dashboard(self, run_id=None):
        repository_alerts = []
        try:
            run = self.mysql_repository.get_run_summary(run_id) if run_id else self.mysql_repository.get_latest_run_summary()
            if run is None:
                run = empty_run_summary()
                repository_alerts.append(make_alert("WARNING", "NO_BATCH_DATA", "조회 가능한 배치가 없습니다.", source="MYSQL"))
        except PipelineRepositoryError:
            run = empty_run_summary()
            history = []
            repository_alerts.append(make_alert("CRITICAL", "MYSQL_UNAVAILABLE", "MySQL 배치 데이터를 조회할 수 없습니다.", source="MYSQL"))
        else:
            try:
                history = self.mysql_repository.get_run_history(limit=12)
            except PipelineRepositoryError:
                history = []
                repository_alerts.append(
                    make_alert(
                        "WARNING",
                        "MYSQL_HISTORY_UNAVAILABLE",
                        "현재 배치는 조회했지만 MySQL 배치 이력을 조회할 수 없습니다.",
                        source="MYSQL",
                        run_id=run["run_id"],
                    )
                )

        if run["run_id"] == "NO-BATCH":
            mongo_facts = empty_mongo_facts(run["run_id"])
            trend = {}
        else:
            try:
                mongo_facts = self.mongodb_repository.get_rejection_summary(run["run_id"])
            except MongoRepositoryError:
                mongo_facts = empty_mongo_facts(run["run_id"])
                trend = {}
                repository_alerts.append(make_alert("CRITICAL", "MONGODB_UNAVAILABLE", "MongoDB rejected 데이터를 조회할 수 없습니다.", source="MONGODB", run_id=run["run_id"]))
            else:
                try:
                    trend = self.mongodb_repository.get_run_counts([item["run_id"] for item in history])
                except MongoRepositoryError:
                    trend = {}
                    repository_alerts.append(
                        make_alert(
                            "WARNING",
                            "MONGODB_TREND_UNAVAILABLE",
                            "현재 rejected 데이터는 조회했지만 MongoDB 배치 추이를 조회할 수 없습니다.",
                            source="MONGODB",
                            run_id=run["run_id"],
                        )
                    )

        mongo = build_mongodb_dashboard_data(run, mongo_facts)
        alerts = repository_alerts + evaluate_mysql_alerts(run, history, policy=self.alert_policy) + evaluate_mongodb_alerts(run, mongo_facts, policy=self.alert_policy)
        status = alert_status(alerts)
        history_for_chart = list(reversed(history))

        context = self._base_context()
        context.update(
            {
                "mongo": mongo,
                "alerts": alerts,
                "overall_status": status,
                "overall_status_label": "정상" if status == "NORMAL" else "경고" if status == "WARNING" else "위험",
                "chart_payload": {
                    "mongoReasonVolume": {
                        "type": "bar",
                        "labels": [reason["label"] for reason in mongo["reasons"]],
                        "datasets": [{"label": "오류 발생 건수", "color": "#8b5cf6", "values": [reason["count"] for reason in mongo["reasons"]]}],
                    },
                    "mongoStageSplit": {
                        "type": "doughnut",
                        "labels": ["표준화 rejected 행", "정규화 rejected 행"],
                        "datasets": [{"values": [mongo["standardized"]["rejected"], mongo["normalized"]["rejected"]], "colors": ["#8b5cf6", "#f59e0b"]}],
                        "centerText": f"{mongo['load']['loaded']:,}",
                        "centerLabel": "총 반려 행",
                    },
                    "mongoCollectionLoad": {
                        "type": "bar",
                        "horizontal": True,
                        "labels": [collection["name"] for collection in mongo["collections"]],
                        "datasets": [{"label": "적재율", "color": "#a855f7", "values": [collection["rate"] for collection in mongo["collections"]]}],
                        "suffix": "%",
                    },
                    "mongoRejectTrend": {
                        "type": "line",
                        "labels": [_format_batch_time(run_started_at(item)) for item in history_for_chart],
                        "datasets": [
                            {
                                "label": "표준화 rejected 행",
                                "color": "#a855f7",
                                "fill": True,
                                "values": [trend.get(item["run_id"], {}).get("standardization", {}).get("rejected_rows", 0) for item in history_for_chart],
                            },
                            {
                                "label": "정규화 rejected 행",
                                "color": "#f59e0b",
                                "values": [trend.get(item["run_id"], {}).get("normalization", {}).get("rejected_rows", 0) for item in history_for_chart],
                            },
                        ],
                    },
                },
            }
        )
        return context
