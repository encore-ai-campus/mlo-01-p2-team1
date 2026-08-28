"""MongoDB 원본부터 표준화·정규화·MySQL 적재까지 실행한다.

대시보드 API나 Django 화면은 이 모듈에서 호출하지 않는다. 이 모듈은
대시보드 담당자가 직접 조회할 MySQL 사실값과 View를 준비하는 데까지만
책임진다.
"""

from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from src.loader.mysql_loader import (
    connect_mysql,
    load_final_result,
    upsert_pipeline_run_summary,
)
from src.loader.write_rejected_rows_to_mongodb import (
    write_rejected_rows_to_mongodb,
)
from src.normailization.normalization import (
    count_rejection_reasons,
    run_normalization,
    save_final_outputs,
)
from src.normailization.reconciliation import (
    STANDARDIZATION_RESULT_KEYS,
    reconcile_counts,
)
from src.standardization.do_standardization import do_standardization
from src.standardization.get_raw_data_from_mongodb import (
    get_raw_data_from_mongoDB,
    update_pipeline_status,
)


def keep_standardization_contract(result):
    """표준화 결과에서 팀이 합의한 다섯 값만 다음 단계로 넘긴다."""
    missing = [key for key in STANDARDIZATION_RESULT_KEYS if key not in result]
    if missing:
        raise ValueError(f"표준화 결과에 키가 없습니다: {', '.join(missing)}")
    return {key: result[key] for key in STANDARDIZATION_RESULT_KEYS}


def ensure_run_id_matches(expected_run_id, result, result_name):
    """앞 단계와 다음 단계가 같은 수집 회차를 처리하는지 확인한다."""
    actual_run_id = str(result.get("run_id", "")).strip()
    if actual_run_id != str(expected_run_id).strip():
        raise ValueError(
            f"Raw run_id와 {result_name} run_id가 다릅니다: "
            f"{expected_run_id} != {actual_run_id}"
        )


def _ingest_date(value: Any) -> str:
    """수집 시각에서 표준화 결과 저장용 날짜를 만든다."""
    candidate = str(value or "")[:10]
    try:
        date.fromisoformat(candidate)
    except ValueError:
        return date.today().isoformat()
    return candidate


def build_standardization_payload(
    raw_documents: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Mongo 문서의 payload와 _ingest.run_id를 표준화 입력으로 바꾼다."""
    if not raw_documents:
        raise ValueError("MongoDB에서 표준화할 원본 문서가 없습니다.")

    run_ids = set()
    rows = []
    collected_at = ""

    for index, document in enumerate(raw_documents, start=1):
        if not isinstance(document, Mapping):
            raise TypeError(f"MongoDB 원본 {index}번째 문서가 객체가 아닙니다.")

        ingest = document.get("_ingest")
        if not isinstance(ingest, Mapping):
            raise ValueError(f"MongoDB 원본 {index}번째 문서에 _ingest가 없습니다.")

        run_id = str(ingest.get("run_id", "")).strip()
        if not run_id:
            raise ValueError(f"MongoDB 원본 {index}번째 문서의 run_id가 비어 있습니다.")
        run_ids.add(run_id)

        row = document.get("payload")
        if not isinstance(row, Mapping):
            raise ValueError(f"MongoDB 원본 {index}번째 문서의 payload가 객체가 아닙니다.")
        rows.append(dict(row))

        if not collected_at:
            collected_at = str(ingest.get("collected_at", "")).strip()

    if len(run_ids) != 1:
        raise ValueError("한 번의 실행에는 하나의 run_id만 있어야 합니다.")

    run_id = next(iter(run_ids))
    return {
        "manifest": {
            "run_id": run_id,
            "ingest_date": _ingest_date(collected_at),
            "processed_at": collected_at,
        },
        "rows": rows,
    }


def run_pipeline(standardization_result, raw_row_count, output_dir="outputs"):
    """표준화 결과를 최종 검증하고 세 결과 파일을 저장한다."""
    final_result = run_normalization(standardization_result)
    reconciliation = reconcile_counts(
        raw_row_count,
        standardization_result,
        final_result,
    )

    validation = {
        "run_id": final_result["run_id"],
        "status": "PASS" if reconciliation["total_reconciliation_pass"] else "FAIL",
        "counts": reconciliation,
        "rejection_reason_counts": count_rejection_reasons(
            final_result["final_rejected_row_list"]
        ),
    }
    output_files = save_final_outputs(final_result, validation, output_dir)

    if not reconciliation["total_reconciliation_pass"]:
        raise ValueError("m + x + y가 raw_row_count와 달라 적재를 중단합니다.")

    return {
        "standardization_result": standardization_result,
        "final_result": final_result,
        "validation": validation,
        "output_files": output_files,
    }


def _write_pipeline_run_summary(connection_factory, summary_writer, summary):
    """배치 요약 1건을 별도 연결로 저장하고 반드시 연결을 닫는다."""
    connection = connection_factory()
    try:
        return summary_writer(connection, summary)
    finally:
        connection.close()


def _new_pipeline_run_summary(run_id, raw_row_count, started_at):
    """아직 처리되지 않은 RUNNING 상태의 사실값을 만든다."""
    return {
        "run_id": run_id,
        "raw_row_count": raw_row_count,
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
        "started_at": started_at,
        "completed_at": None,
        "batch_status": "RUNNING",
        "error_message": None,
    }


def run_all(
    output_dir="outputs",
    *,
    raw_data_reader: Callable[[], list[dict[str, Any]]] = get_raw_data_from_mongoDB,
    mysql_connection_factory: Callable[[], Any] = connect_mysql,
    mysql_loader: Callable[[Any, Mapping[str, Any]], dict[str, Any]] = load_final_result,
    rejected_rows_writer: Callable[
        [Mapping[str, Any], Mapping[str, Any]], dict[str, int]
    ] = write_rejected_rows_to_mongodb,
    run_summary_writer: Callable[[Any, Mapping[str, Any]], dict[str, Any]] = (
        upsert_pipeline_run_summary
    ),
    pipeline_status_updater: Callable[[str, str], dict[str, Any]] = update_pipeline_status,
    standardization_output_root: str | Path | None = None,
    now_factory: Callable[[], datetime] = datetime.now,
):
    """Mongo 원본 조회부터 MySQL 적재와 배치 사실 기록까지만 실행한다."""
    raw_documents = raw_data_reader()
    raw_row_count = len(raw_documents)
    standardization_payload = build_standardization_payload(raw_documents)
    run_id = standardization_payload["manifest"]["run_id"]
    summary = _new_pipeline_run_summary(
        run_id,
        raw_row_count,
        now_factory(),
    )
    mysql_loaded = False

    try:
        _write_pipeline_run_summary(
            mysql_connection_factory,
            run_summary_writer,
            summary,
        )
        pipeline_status_updater(run_id, "processing")

        standardization_result = do_standardization(
            standardization_payload,
            output_root=standardization_output_root,
        )
        standardization_result = keep_standardization_contract(standardization_result)
        ensure_run_id_matches(run_id, standardization_result, "표준화 결과")

        result = run_pipeline(
            standardization_result,
            raw_row_count=raw_row_count,
            output_dir=Path(output_dir),
        )
        counts = result["validation"]["counts"]
        summary.update(
            {
                "standardization_accepted_count": counts[
                    "standardization_accepted_row_count"
                ],
                "standardization_rejected_count": counts[
                    "standardization_rejected_row_count"
                ],
                "final_accepted_count": counts["final_accepted_row_count"],
                "final_rejected_count": counts["final_rejected_row_count"],
            }
        )

        connection = mysql_connection_factory()
        try:
            mysql_result = mysql_loader(connection, result["final_result"])
            mysql_loaded = True
        finally:
            connection.close()

        for entity in ("manager", "top_area", "area"):
            row_count = mysql_result.get(f"{entity}_row_count", 0)
            summary[f"{entity}_target_count"] = mysql_result.get(
                f"{entity}_target_count",
                row_count,
            )
            summary[f"{entity}_loaded_count"] = mysql_result.get(
                f"{entity}_loaded_count",
                row_count,
            )

        rejected_mongo_result = rejected_rows_writer(
            standardization_result,
            result["final_result"],
        )
        status_result = pipeline_status_updater(run_id, "pass")
        summary.update(
            {
                "completed_at": now_factory(),
                "batch_status": "SUCCESS",
                "error_message": None,
            }
        )
        summary_result = _write_pipeline_run_summary(
            mysql_connection_factory,
            run_summary_writer,
            summary,
        )
    except Exception as exc:
        summary.update(
            {
                "completed_at": now_factory(),
                "batch_status": "PARTIAL_FAILURE" if mysql_loaded else "FAILED",
                "error_message": f"{type(exc).__name__}: {exc}",
            }
        )
        try:
            _write_pipeline_run_summary(
                mysql_connection_factory,
                run_summary_writer,
                summary,
            )
        except Exception as summary_exc:
            exc.add_note(f"배치 실패 요약 저장도 실패했습니다: {summary_exc}")
        try:
            pipeline_status_updater(run_id, "failed")
        except Exception as status_exc:
            exc.add_note(f"Mongo manifest 실패 상태 변경도 실패했습니다: {status_exc}")
        raise

    result["mysql_load"] = mysql_result
    result["mongodb_rejected_load"] = rejected_mongo_result
    result["pipeline_status_update"] = status_result
    result["pipeline_run_summary"] = summary_result
    return result


if __name__ == "__main__":
    completed = run_all()
    print(completed["validation"])
    print(completed["mysql_load"])
    print(completed["mongodb_rejected_load"])
    print(completed["pipeline_status_update"])
