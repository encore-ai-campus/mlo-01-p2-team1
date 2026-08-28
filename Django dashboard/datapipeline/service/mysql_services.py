from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from datapipeline.repository.mysql_repository import (
    COUNT_COLUMNS,
    PipelineRepository,
    PipelineRepositoryError,
    parse_run_id_started_at,
)


DEFAULT_ALERT_POLICY = {
    "run_interval_minutes": 3,
    "stale_warning_minutes": 6,
    "stale_critical_minutes": 9,
    "duration_warning_minutes": 3,
    "standard_reject_warning_count": 4,
    "standard_reject_warning_rate": 25.0,
    "standard_reject_critical_count": 8,
    "standard_reject_critical_rate": 50.0,
    "final_reject_warning_count": 3,
    "final_reject_warning_rate": 20.0,
    "final_reject_critical_rate": 40.0,
    "entity_load_critical_rate": 95.0,
    "error_code_warning_count": 3,
}

TERMINAL_STATUSES = {"SUCCESS", "PARTIAL_FAILURE", "FAILED"}


def percentage(numerator, denominator, *, empty_value=0.0):
    if not denominator:
        return float(empty_value)
    return round((numerator / denominator) * 100, 1)


def _aware(value):
    if value is None:
        return None
    if timezone.is_naive(value):
        return timezone.make_aware(value, timezone.get_current_timezone())
    return value


def run_started_at(run):
    return _aware(run.get("started_at")) or parse_run_id_started_at(run.get("run_id"))


def build_mysql_load_rate_telemetry(history):
    """Aggregate Final accepted/raw rates into KST clock-aligned 30m buckets."""
    buckets = {}
    for run in history:
        started_at = run_started_at(run)
        if started_at is None:
            continue
        local_started_at = timezone.localtime(started_at)
        bucket = local_started_at.replace(
            minute=0 if local_started_at.minute < 30 else 30,
            second=0,
            microsecond=0,
        )
        facts = buckets.setdefault(bucket, {"raw": 0, "loaded": 0})
        facts["raw"] += int(run.get("raw_row_count") or 0)
        facts["loaded"] += int(run.get("final_accepted_count") or 0)

    ordered = sorted(buckets.items())
    return {
        "labels": [bucket.strftime("%m-%d %H:%M") for bucket, _ in ordered],
        "values": [
            percentage(facts["loaded"], facts["raw"])
            for _, facts in ordered
        ],
    }


def _duration_seconds(run):
    started_at = run_started_at(run)
    completed_at = _aware(run.get("completed_at"))
    if not started_at or not completed_at:
        return None
    return (completed_at - started_at).total_seconds()


def _format_duration(run):
    duration_seconds = _duration_seconds(run)
    if duration_seconds is None or duration_seconds < 0:
        return "--:--"
    minutes, seconds = divmod(int(duration_seconds), 60)
    return f"{minutes:02d}:{seconds:02d}"


def _format_freshness(run, now=None):
    reference = _aware(run.get("updated_at")) or _aware(run.get("completed_at")) or run_started_at(run)
    if reference is None:
        return "확인 불가"
    elapsed = max(0, int(((now or timezone.now()) - reference).total_seconds()))
    if elapsed < 60:
        return f"{elapsed}초 전"
    if elapsed < 3600:
        return f"{elapsed // 60}분 전"
    return f"{elapsed // 3600}시간 전"


def make_alert(level, code, message, *, source="PIPELINE", run_id=None, **details):
    return {
        "level": level,
        "code": code,
        "message": message,
        "source": source,
        "run_id": run_id,
        **details,
    }


def alert_status(alerts):
    levels = {alert.get("level") for alert in alerts}
    if "CRITICAL" in levels:
        return "CRITICAL"
    if "WARNING" in levels:
        return "WARNING"
    return "NORMAL"


def empty_run_summary():
    return {
        "run_id": "NO-BATCH",
        "raw_row_count": 0,
        "standardization_accepted_count": 0,
        "standardization_rejected_count": 0,
        "final_accepted_count": 0,
        "final_rejected_count": 0,
        "manager_target_count": 0,
        "manager_loaded_count": 0,
        "top_area_target_count": 0,
        "top_area_loaded_count": 0,
        "area_target_count": 0,
        "area_loaded_count": 0,
        "started_at": None,
        "completed_at": None,
        "batch_status": "UNAVAILABLE",
        "error_message": None,
        "created_at": None,
        "updated_at": None,
    }


def aggregate_run_summaries(runs):
    """Sum batch facts while retaining the latest batch metadata."""
    if not runs:
        return empty_run_summary()

    latest = runs[0]
    aggregate = dict(latest)
    aggregate.update(
        {
            column: sum(int(run.get(column) or 0) for run in runs)
            for column in COUNT_COLUMNS
        }
    )
    aggregate["run_id"] = "ALL-RUNS"
    aggregate["source_run_count"] = len(runs)
    aggregate["latest_run_id"] = latest["run_id"]
    return aggregate


def evaluate_mysql_alerts(run, history=None, now=None, policy=None):
    policy = {**DEFAULT_ALERT_POLICY, **(policy or {})}
    now = now or timezone.now()
    run_id = run.get("run_id")
    status = str(run.get("batch_status") or "UNKNOWN").upper()
    alerts = []

    if status == "FAILED":
        alerts.append(make_alert("CRITICAL", "BATCH_FAILED", "최근 배치가 실패했습니다.", source="MYSQL", run_id=run_id))
    elif status == "PARTIAL_FAILURE":
        alerts.append(make_alert("WARNING", "BATCH_PARTIAL_FAILURE", "최근 배치가 부분 실패했습니다.", source="MYSQL", run_id=run_id))
    elif status not in TERMINAL_STATUSES | {"RUNNING"}:
        alerts.append(make_alert("WARNING", "BATCH_STATUS_UNKNOWN", "배치 상태를 확인할 수 없습니다.", source="MYSQL", run_id=run_id))

    started_at = run_started_at(run)
    completed_at = _aware(run.get("completed_at"))
    if started_at:
        age = now - started_at
        if age < -timedelta(minutes=1):
            alerts.append(make_alert("WARNING", "CLOCK_SKEW", "배치 시작 시각이 현재보다 미래입니다.", source="MYSQL", run_id=run_id))
        elif status == "RUNNING":
            elapsed_minutes = age.total_seconds() / 60
            if elapsed_minutes >= policy["stale_critical_minutes"]:
                alerts.append(make_alert("CRITICAL", "RUN_STUCK", "배치가 9분 이상 RUNNING 상태입니다.", source="MYSQL", run_id=run_id))
            elif elapsed_minutes >= policy["stale_warning_minutes"]:
                alerts.append(make_alert("WARNING", "RUN_DELAYED", "배치가 6분 이상 RUNNING 상태입니다.", source="MYSQL", run_id=run_id))
        else:
            stale_minutes = age.total_seconds() / 60
            if stale_minutes >= policy["stale_critical_minutes"]:
                alerts.append(make_alert("CRITICAL", "PIPELINE_STALE", "최근 배치 시작 후 9분 이상 새 실행이 없습니다.", source="MYSQL", run_id=run_id))
            elif stale_minutes >= policy["stale_warning_minutes"]:
                alerts.append(make_alert("WARNING", "PIPELINE_DELAYED", "최근 배치 시작 후 6분 이상 새 실행이 없습니다.", source="MYSQL", run_id=run_id))

    if status in TERMINAL_STATUSES:
        if not completed_at:
            alerts.append(make_alert("CRITICAL", "COMPLETED_AT_MISSING", "종료된 배치에 완료 시각이 없습니다.", source="MYSQL", run_id=run_id))
        elif started_at and completed_at < started_at:
            alerts.append(make_alert("CRITICAL", "INVALID_RUN_DURATION", "완료 시각이 시작 시각보다 빠릅니다.", source="MYSQL", run_id=run_id))
        else:
            duration_seconds = _duration_seconds(run)
            if duration_seconds is not None and duration_seconds >= policy["duration_warning_minutes"] * 60:
                alerts.append(make_alert("WARNING", "RUN_OVERLAP_RISK", "배치 실행 시간이 다음 3분 주기를 초과했습니다.", source="MYSQL", run_id=run_id))

        raw_count = run["raw_row_count"]
        standard_accepted = run["standardization_accepted_count"]
        standard_rejected = run["standardization_rejected_count"]
        final_accepted = run["final_accepted_count"]
        final_rejected = run["final_rejected_count"]

        if raw_count != standard_accepted + standard_rejected:
            alerts.append(make_alert("CRITICAL", "STANDARD_COUNT_MISMATCH", "원천 건수와 표준화 accepted/rejected 합계가 일치하지 않습니다.", source="MYSQL", run_id=run_id, actual=standard_accepted + standard_rejected, expected=raw_count))
        if standard_accepted != final_accepted + final_rejected:
            alerts.append(make_alert("CRITICAL", "FINAL_COUNT_MISMATCH", "표준화 accepted와 final accepted/rejected 합계가 일치하지 않습니다.", source="MYSQL", run_id=run_id, actual=final_accepted + final_rejected, expected=standard_accepted))

        standard_reject_rate = percentage(standard_rejected, raw_count)
        if standard_rejected >= policy["standard_reject_critical_count"] or standard_reject_rate >= policy["standard_reject_critical_rate"]:
            alerts.append(make_alert("CRITICAL", "STANDARD_REJECT_SURGE", "표준화 rejected가 기준치를 크게 초과했습니다.", source="MYSQL", run_id=run_id, actual=standard_rejected, rate=standard_reject_rate))
        elif standard_rejected >= policy["standard_reject_warning_count"] or standard_reject_rate >= policy["standard_reject_warning_rate"]:
            alerts.append(make_alert("WARNING", "STANDARD_REJECT_HIGH", "표준화 rejected가 경고 기준을 초과했습니다.", source="MYSQL", run_id=run_id, actual=standard_rejected, rate=standard_reject_rate))

        final_reject_rate = percentage(final_rejected, standard_accepted)
        if final_reject_rate >= policy["final_reject_critical_rate"]:
            alerts.append(make_alert("CRITICAL", "FINAL_REJECT_SURGE", "Final rejected 비율이 기준치를 크게 초과했습니다.", source="MYSQL", run_id=run_id, actual=final_rejected, rate=final_reject_rate))
        elif final_rejected >= policy["final_reject_warning_count"] or final_reject_rate >= policy["final_reject_warning_rate"]:
            alerts.append(make_alert("WARNING", "FINAL_REJECT_HIGH", "Final rejected가 경고 기준을 초과했습니다.", source="MYSQL", run_id=run_id, actual=final_rejected, rate=final_reject_rate))

        for entity in ("manager", "top_area", "area"):
            target = run[f"{entity}_target_count"]
            loaded = run[f"{entity}_loaded_count"]
            rate = percentage(loaded, target, empty_value=100.0 if loaded == 0 else 0.0)
            if loaded > target:
                alerts.append(make_alert("CRITICAL", "LOAD_EXCEEDS_TARGET", f"{entity} 적재 건수가 대상 건수를 초과했습니다.", source="MYSQL", run_id=run_id, entity=entity, actual=loaded, expected=target))
            elif status == "SUCCESS" and loaded != target:
                alerts.append(make_alert("CRITICAL", "SUCCESS_LOAD_MISMATCH", f"SUCCESS 배치의 {entity} 적재 건수가 대상 건수와 다릅니다.", source="MYSQL", run_id=run_id, entity=entity, actual=loaded, expected=target, rate=rate))
            elif status != "SUCCESS" and target and rate < policy["entity_load_critical_rate"]:
                alerts.append(make_alert("WARNING", "ENTITY_LOAD_LOW", f"{entity} 적재율이 95% 미만입니다.", source="MYSQL", run_id=run_id, entity=entity, actual=loaded, expected=target, rate=rate))

    consecutive_partial = 0
    for item in history or []:
        if item.get("batch_status") != "PARTIAL_FAILURE":
            break
        consecutive_partial += 1
    if consecutive_partial >= 2:
        alerts.append(make_alert("CRITICAL", "REPEATED_PARTIAL_FAILURE", "부분 실패가 2회 이상 연속 발생했습니다.", source="MYSQL", run_id=run_id, count=consecutive_partial))

    return alerts


def build_mysql_dashboard_data(run, history=None, now=None):
    history = history or []
    now = now or timezone.now()
    raw_count = run["raw_row_count"]
    standard_accepted = run["standardization_accepted_count"]
    final_accepted = run["final_accepted_count"]
    entity_specs = (
        ("manager", "manager", "최종 적재"),
        ("top_area", "top_business_area", "최종 적재"),
        ("area", "business_area", "최종 적재"),
    )
    tables = []
    for key, name, stage in entity_specs:
        expected = run[f"{key}_target_count"]
        loaded = run[f"{key}_loaded_count"]
        rate = percentage(loaded, expected, empty_value=100.0 if loaded == 0 else 0.0)
        tables.append(
            {
                "name": name,
                "stage": stage,
                "loaded": loaded,
                "expected": expected,
                "rate": rate,
                "status": "정상" if loaded == expected else "확인 필요",
            }
        )

    total_expected = sum(table["expected"] for table in tables)
    total_loaded = sum(table["loaded"] for table in tables)
    recent_batches = [
        {
            "id": item["run_id"],
            "stage": "PIPELINE",
            "rows": item["final_accepted_count"],
            "duration": _format_duration(item),
            "status": item["batch_status"],
        }
        for item in history[:8]
    ]
    return {
        "run": run,
        "standardized": {
            "accepted": standard_accepted,
            "input": raw_count,
            "rate": percentage(standard_accepted, raw_count),
        },
        "normalized": {
            "accepted": final_accepted,
            "input": standard_accepted,
            "rate": percentage(final_accepted, standard_accepted),
        },
        "rejected": {
            "standardization": run["standardization_rejected_count"],
            "normalization": run["final_rejected_count"],
        },
        "load": {
            "loaded": final_accepted,
            "expected": raw_count,
            "rate": percentage(final_accepted, raw_count),
        },
        "entity_load": {
            "loaded": total_loaded,
            "expected": total_expected,
            "rate": percentage(total_loaded, total_expected, empty_value=100.0 if total_loaded == 0 else 0.0),
        },
        "freshness": _format_freshness(run, now=now),
        "tables": tables,
        "recent_batches": recent_batches,
        "batch_status": run["batch_status"],
        "error_message": run.get("error_message"),
    }


class MySQLDashboardService:
    """Build the accepted-data dashboard and MySQL-side warning signals."""

    def __init__(self, mysql_repository=None, alert_policy=None):
        self.mysql_repository = mysql_repository or PipelineRepository()
        self.alert_policy = alert_policy

    @staticmethod
    def _base_context():
        return {
            "active_section": "mysql",
            "data_mode": "LIVE DATA" if settings.DASHBOARD_DATA_MODE == "live" else "DEMO DATA",
            "updated_at": timezone.localtime().strftime("%Y-%m-%d %H:%M:%S KST"),
        }

    def get_dashboard(self, run_id=None):
        repository_alerts = []
        aggregate_scope = run_id is None
        try:
            if run_id:
                selected_run = self.mysql_repository.get_run_summary(run_id)
                all_runs = [selected_run] if selected_run else []
                run = selected_run or empty_run_summary()
            else:
                all_runs = self.mysql_repository.get_all_run_summaries()
                run = aggregate_run_summaries(all_runs)
            if not all_runs:
                run = empty_run_summary()
                repository_alerts.append(make_alert("WARNING", "NO_BATCH_DATA", "조회 가능한 배치가 없습니다.", source="MYSQL"))
        except PipelineRepositoryError:
            all_runs = []
            run = empty_run_summary()
            history = []
            repository_alerts.append(make_alert("CRITICAL", "MYSQL_UNAVAILABLE", "MySQL 배치 데이터를 조회할 수 없습니다.", source="MYSQL", run_id=run_id))
        else:
            if aggregate_scope:
                history = all_runs[:60]
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

        mysql = build_mysql_dashboard_data(run, history)
        alert_run = all_runs[0] if aggregate_scope and all_runs else run
        mysql_alerts = (
            evaluate_mysql_alerts(alert_run, history, policy=self.alert_policy)
            if all_runs
            else []
        )
        alerts = repository_alerts + mysql_alerts
        status = alert_status(alerts)
        load_rate_telemetry = build_mysql_load_rate_telemetry(history)
        stage_rejected = run["standardization_rejected_count"] + run["final_rejected_count"]
        unaccounted = max(run["raw_row_count"] - run["final_accepted_count"] - stage_rejected, 0)

        context = self._base_context()
        context.update(
            {
                "mysql": mysql,
                "aggregation_scope": "ALL_RUNS" if aggregate_scope else "SINGLE_RUN",
                "aggregated_run_count": len(all_runs),
                "aggregation_label": (
                    f"ALL {len(all_runs):,} RUNS"
                    if aggregate_scope
                    else f"RUN {run['run_id']}"
                ),
                "alerts": alerts,
                "overall_status": status,
                "overall_status_label": "정상" if status == "NORMAL" else "경고" if status == "WARNING" else "위험",
                "chart_payload": {
                    "mysqlLoadTrend": {
                        "type": "line",
                        "labels": load_rate_telemetry["labels"],
                        "datasets": [{"label": "Final accepted / Legacy", "color": "#f59e0b", "fill": True, "values": load_rate_telemetry["values"]}],
                        "suffix": "%",
                    },
                    "mysqlStageVolume": {
                        "type": "bar",
                        "labels": ["수집", "표준화 승인", "최종 승인", "MySQL 적재"],
                        "datasets": [{"label": "레코드", "color": "#14b8a6", "values": [run["raw_row_count"], run["standardization_accepted_count"], run["final_accepted_count"], mysql["load"]["loaded"]]}],
                    },
                    "mysqlTableLoad": {
                        "type": "bar",
                        "horizontal": True,
                        "labels": [table["name"] for table in mysql["tables"]],
                        "datasets": [{"label": "적재율", "color": "#20d9ff", "values": [table["rate"] for table in mysql["tables"]]}],
                        "suffix": "%",
                    },
                    "mysqlAcceptance": {
                        "type": "doughnut",
                        "labels": ["Final accepted", "Rejected", "미대사"],
                        "datasets": [{"values": [run["final_accepted_count"], stage_rejected, unaccounted], "colors": ["#15e6c1", "#a855f7", "#f59e0b"]}],
                        "centerText": f"{mysql['load']['rate']}%",
                        "centerLabel": "FINAL ACCEPTED",
                    },
                },
            }
        )
        return context
