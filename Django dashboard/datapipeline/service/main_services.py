from django.conf import settings
from django.utils import timezone

from datapipeline.repository.mongodb_repository import MongoRepository, MongoRepositoryError
from datapipeline.repository.mysql_repository import PipelineRepository, PipelineRepositoryError
from datapipeline.service.mongodb_services import (
    build_mongodb_dashboard_data,
    empty_mongo_facts,
    evaluate_mongodb_alerts,
)
from datapipeline.service.mysql_services import (
    alert_status,
    build_mysql_dashboard_data,
    empty_run_summary,
    evaluate_mysql_alerts,
    make_alert,
    percentage,
    run_started_at,
)


def _event_time(run):
    started_at = run_started_at(run)
    return timezone.localtime(started_at).strftime("%H:%M") if started_at else "--:--"


def _hourly_ingestion(history):
    """Aggregate raw input counts into KST hour buckets."""
    buckets = {}
    for item in history:
        started_at = run_started_at(item)
        if started_at is None:
            continue
        hour = timezone.localtime(started_at).replace(minute=0, second=0, microsecond=0)
        buckets[hour] = buckets.get(hour, 0) + item["raw_row_count"]

    ordered = sorted(buckets.items())
    return {
        "labels": [hour.strftime("%m-%d %H:00") for hour, _ in ordered],
        "values": [count for _, count in ordered],
    }


class MainDashboardService:
    """Combine MySQL pipeline facts and MongoDB rejected-data facts."""

    def __init__(self, mysql_repository=None, mongodb_repository=None, alert_policy=None):
        self.mysql_repository = mysql_repository or PipelineRepository()
        self.mongodb_repository = mongodb_repository or MongoRepository()
        self.alert_policy = alert_policy

    @staticmethod
    def _base_context():
        return {
            "active_section": "main",
            "data_mode": "LIVE DATA" if settings.DASHBOARD_DATA_MODE == "live" else "DEMO DATA",
            "updated_at": timezone.localtime().strftime("%Y-%m-%d %H:%M:%S KST"),
        }

    def get_dashboard(self):
        repository_alerts = []
        try:
            run = self.mysql_repository.get_latest_run_summary()
            if run is None:
                run = empty_run_summary()
                repository_alerts.append(make_alert("WARNING", "NO_BATCH_DATA", "조회 가능한 배치가 없습니다.", source="MYSQL"))
        except PipelineRepositoryError:
            run = empty_run_summary()
            history = []
            repository_alerts.append(make_alert("CRITICAL", "MYSQL_UNAVAILABLE", "MySQL 배치 데이터를 조회할 수 없습니다.", source="MYSQL"))
        else:
            try:
                history = self.mysql_repository.get_run_history(limit=60)
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
            mongo_trend = {}
        else:
            try:
                mongo_facts = self.mongodb_repository.get_rejection_summary(run["run_id"])
            except MongoRepositoryError:
                mongo_facts = empty_mongo_facts(run["run_id"])
                mongo_trend = {}
                repository_alerts.append(make_alert("CRITICAL", "MONGODB_UNAVAILABLE", "MongoDB rejected 데이터를 조회할 수 없습니다.", source="MONGODB", run_id=run["run_id"]))
            else:
                try:
                    mongo_trend = self.mongodb_repository.get_run_counts([item["run_id"] for item in history])
                except MongoRepositoryError:
                    mongo_trend = {}
                    repository_alerts.append(
                        make_alert(
                            "WARNING",
                            "MONGODB_TREND_UNAVAILABLE",
                            "현재 rejected 데이터는 조회했지만 MongoDB 배치 추이를 조회할 수 없습니다.",
                            source="MONGODB",
                            run_id=run["run_id"],
                        )
                    )

        mysql = build_mysql_dashboard_data(run, history)
        mongo = build_mongodb_dashboard_data(run, mongo_facts)
        alerts = repository_alerts + evaluate_mysql_alerts(run, history, policy=self.alert_policy) + evaluate_mongodb_alerts(run, mongo_facts, policy=self.alert_policy)
        overall_status = alert_status(alerts)

        # Final accepted rows and actually stored rejected documents share the
        # same raw-row unit. Entity table counts do not and are never added here.
        accounted_rows = run["final_accepted_count"] + mongo["load"]["loaded"]
        raw_count = run["raw_row_count"]
        overall_load_rate = percentage(accounted_rows, raw_count)
        pending_rows = max(raw_count - accounted_rows, 0)
        mysql_legacy_rate = percentage(run["final_accepted_count"], raw_count)
        mongo_legacy_rate = percentage(mongo["load"]["loaded"], raw_count)
        legacy = {
            "total_received": raw_count,
            "input_rate": 100.0 if raw_count else 0.0,
            "latest_batch": run["run_id"],
        }
        database_shares = {
            "mysql": {
                "loaded": run["final_accepted_count"],
                "total": raw_count,
                "rate": mysql_legacy_rate,
            },
            "mongodb": {
                "loaded": mongo["load"]["loaded"],
                "total": raw_count,
                "rate": mongo_legacy_rate,
            },
        }

        event_time = _event_time(run)
        pipeline_events = [
            {"time": event_time, "label": f"배치 상태 {run['batch_status']}", "tone": "green" if run["batch_status"] == "SUCCESS" else "orange"},
            {"time": event_time, "label": f"Final accepted {run['final_accepted_count']:,}건", "tone": "blue"},
            {"time": event_time, "label": f"표준화 rejected 저장 {mongo['standardized']['rejected']:,}건", "tone": "purple"},
            {"time": event_time, "label": f"정규화 rejected 저장 {mongo['normalized']['rejected']:,}건", "tone": "purple"},
        ]
        if alerts:
            pipeline_events.insert(
                0,
                {
                    "time": event_time,
                    "label": alerts[0]["message"],
                    "tone": "red" if alerts[0]["level"] == "CRITICAL" else "orange",
                },
            )

        chart_history = history or ([] if run["run_id"] == "NO-BATCH" else [run])
        history_for_chart = list(reversed(chart_history))
        hourly_ingestion = _hourly_ingestion(chart_history)
        labels = [
            timezone.localtime(run_started_at(item)).strftime("%H:%M") if run_started_at(item) else "--:--"
            for item in history_for_chart
        ]
        context = self._base_context()
        context.update(
            {
                "legacy": legacy,
                "mysql": mysql,
                "mongo": mongo,
                "overall_load_rate": overall_load_rate,
                "total_loaded": accounted_rows,
                "pending_rows": pending_rows,
                "database_shares": database_shares,
                "alerts": alerts,
                "overall_status": overall_status,
                "overall_status_label": "정상" if overall_status == "NORMAL" else "경고" if overall_status == "WARNING" else "위험",
                "pipeline_events": pipeline_events[:5],
                "scene_payload": {
                    "legacy": raw_count,
                    "standardized": run["standardization_accepted_count"],
                    "normalized": run["final_accepted_count"],
                    "mysqlLoaded": run["final_accepted_count"],
                    "mongoLoaded": mongo["load"]["loaded"],
                    "standardRejected": mongo["standardized"]["rejected"],
                    "normalRejected": mongo["normalized"]["rejected"],
                    "overallRate": overall_load_rate,
                },
                "chart_payload": {
                    "pipelineThroughput": {
                        "type": "line",
                        "labels": labels,
                        "datasets": [
                            {"label": "원천 수집", "color": "#f59e0b", "values": [item["raw_row_count"] for item in history_for_chart]},
                            {"label": "Final accepted", "color": "#14b8a6", "values": [item["final_accepted_count"] for item in history_for_chart]},
                        ],
                    },
                    "qualityDistribution": {
                        "type": "doughnut",
                        "labels": ["MySQL accepted", "MongoDB rejected", "미대사"],
                        "datasets": [{"values": [run["final_accepted_count"], mongo["load"]["loaded"], pending_rows], "colors": ["#14b8a6", "#8b5cf6", "#e2e8f0"]}],
                        "centerText": f"{mysql_legacy_rate}%",
                        "centerLabel": "FINAL ACCEPTED",
                    },
                    "hourlyIngestionVolume": {
                        "type": "bar",
                        "labels": hourly_ingestion["labels"],
                        "datasets": [{"label": "시간당 원천 수집량", "color": "#20d9ff", "values": hourly_ingestion["values"]}],
                    },
                    "rejectReasonVolume": {
                        "type": "bar",
                        "horizontal": True,
                        "labels": [reason["label"] for reason in mongo["reasons"][:5]],
                        "datasets": [{"label": "오류 발생 건수", "color": "#a855f7", "values": [reason["count"] for reason in mongo["reasons"][:5]]}],
                    },
                    "mongoBatchTrend": mongo_trend,
                },
            }
        )
        return context
