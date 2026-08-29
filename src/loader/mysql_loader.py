"""Final Accepted와 배치 사실값을 MySQL에 적재한다.

대시보드 담당자는 이 모듈을 호출하지 않고 DB View를 직접 조회한다.
"""

import os
from datetime import datetime
from pathlib import Path

from src.gold.manager_assignment_features import (
    GOLD_MANAGER_ASSIGNMENT_COLUMNS,
    build_manager_assignment_features,
)

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None


PROJECT_ROOT = Path(__file__).resolve().parents[2]

if load_dotenv is not None:
    load_dotenv(PROJECT_ROOT / ".env")


MANAGER_COLUMNS = (
    "manager_id",
    "manager_name",
    "manager_department_name",
    "manager_position_name",
    "manager_hire_datetime",
    "manager_active_yn",
)

TOP_AREA_COLUMNS = (
    "top_business_area_id",
    "top_business_area_name",
    "top_business_area_level_code",
    "top_business_area_registration_datetime",
)

AREA_COLUMNS = (
    "business_area_id",
    "business_area_name",
    "manager_id",
    "parent_business_area_id",
    "top_business_area_id",
    "business_area_registration_datetime",
)

PIPELINE_RUN_STATUSES = {
    "RUNNING",
    "SUCCESS",
    "PARTIAL_FAILURE",
    "FAILED",
}

PIPELINE_RUN_COUNT_COLUMNS = (
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
)


def get_mysql_settings():
    """DB1_* 환경변수를 MySQL 연결 설정으로 바꾼다."""
    settings = {
        "host": os.getenv("DB1_HOST"),
        "port": os.getenv("DB1_PORT", "3306"),
        "user": os.getenv("DB1_USER"),
        "password": os.getenv("DB1_PASSWORD"),
        "database": os.getenv("DB1_NAME"),
    }
    environment_names = {
        "host": "DB1_HOST",
        "user": "DB1_USER",
        "password": "DB1_PASSWORD",
        "database": "DB1_NAME",
    }
    missing = [
        environment_names[name]
        for name in environment_names
        if not settings[name]
    ]
    if missing:
        raise ValueError(f"MySQL 환경변수가 비어 있습니다: {', '.join(missing)}")

    try:
        settings["port"] = int(settings["port"])
    except ValueError as exc:
        raise ValueError("DB1_PORT는 숫자여야 합니다.") from exc

    return settings


def connect_mysql():
    """DB1_* 환경변수로 MySQL에 연결한다."""
    import mysql.connector

    return mysql.connector.connect(**get_mysql_settings())


def to_mysql_value(column, value):
    """빈 Parent는 None으로, 일시 문자열은 datetime으로 변환한다."""
    if column == "parent_business_area_id" and (value is None or str(value).strip() == ""):
        return None
    if column.endswith("_datetime"):
        return datetime.fromisoformat(str(value))
    return value


def build_entity_rows(rows, key_column, columns):
    """통합 행에서 PK별 엔터티 행을 한 번씩 추출한다."""
    entities = {}
    for row in rows:
        key = row[key_column]
        values = tuple(to_mysql_value(column, row.get(column)) for column in columns)

        if key in entities and entities[key] != values:
            raise ValueError(f"품질검증 이후에도 {key_column}={key} 속성 충돌이 남아 있습니다.")
        entities[key] = values

    return list(entities.values())


def add_run_id(run_id, entity_rows):
    """각 RDB 행 앞에 같은 크롤링 회차 ID를 붙인다."""
    if run_id is None or str(run_id).strip() == "":
        raise ValueError("MySQL 적재에 사용할 run_id가 비어 있습니다.")
    return [(str(run_id), *row) for row in entity_rows]


def apply_schema(connection, schema_path):
    """schema.sql의 CREATE TABLE 문을 순서대로 실행한다."""
    sql_text = Path(schema_path).read_text(encoding="utf-8")
    statements = [statement.strip() for statement in sql_text.split(";") if statement.strip()]

    cursor = connection.cursor()
    try:
        for statement in statements:
            cursor.execute(statement)
    finally:
        cursor.close()


def normalize_pipeline_run_summary(summary):
    """배치 요약을 DB 제약조건에 맞는 값으로 검증·정규화한다."""
    run_id = str(summary.get("run_id", "")).strip()
    if not run_id:
        raise ValueError("배치 요약의 run_id가 비어 있습니다.")

    status = str(summary.get("batch_status", "")).strip().upper()
    if status not in PIPELINE_RUN_STATUSES:
        allowed = ", ".join(sorted(PIPELINE_RUN_STATUSES))
        raise ValueError(f"batch_status는 다음 중 하나여야 합니다: {allowed}")

    started_at = summary.get("started_at")
    if started_at is None:
        raise ValueError("배치 요약의 started_at이 비어 있습니다.")

    normalized = {
        "run_id": run_id,
        "started_at": started_at,
        "completed_at": summary.get("completed_at"),
        "batch_status": status,
        "error_message": summary.get("error_message"),
    }
    for column in PIPELINE_RUN_COUNT_COLUMNS:
        value = int(summary.get(column, 0))
        if value < 0:
            raise ValueError(f"{column}은 0 이상이어야 합니다.")
        normalized[column] = value

    return normalized


def upsert_pipeline_run_summary(connection, summary):
    """run_id 단위 파이프라인 사실값과 상태를 멱등적으로 저장한다."""
    normalized = normalize_pipeline_run_summary(summary)
    columns = (
        "run_id",
        *PIPELINE_RUN_COUNT_COLUMNS,
        "started_at",
        "completed_at",
        "batch_status",
        "error_message",
    )
    column_sql = ", ".join(columns)
    placeholders = ", ".join(["%s"] * len(columns))
    update_sql = ",\n            ".join(
        f"{column} = VALUES({column})" for column in columns if column != "run_id"
    )
    sql = f"""
        INSERT INTO pipeline_run_summary ({column_sql})
        VALUES ({placeholders})
        ON DUPLICATE KEY UPDATE
            {update_sql}
    """
    values = tuple(normalized[column] for column in columns)

    cursor = connection.cursor()
    try:
        cursor.execute(sql, values)
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()

    return normalized


def load_final_result(connection, final_result):
    """Silver 세 테이블과 담당자별 Gold Feature를 함께 적재한다."""
    run_id = final_result["run_id"]
    rows = final_result["final_accepted_row_list"]
    managers = add_run_id(
        run_id,
        build_entity_rows(rows, "manager_id", MANAGER_COLUMNS),
    )
    top_areas = add_run_id(
        run_id,
        build_entity_rows(rows, "top_business_area_id", TOP_AREA_COLUMNS),
    )
    areas = add_run_id(
        run_id,
        build_entity_rows(rows, "business_area_id", AREA_COLUMNS),
    )
    gold_features = build_manager_assignment_features(final_result)
    gold_rows = [
        tuple(feature[column] for column in GOLD_MANAGER_ASSIGNMENT_COLUMNS)
        for feature in gold_features
    ]

    manager_sql = """
        INSERT INTO manager (
            run_id, manager_id, manager_name, manager_department_name,
            manager_position_name, manager_hire_datetime, manager_active_yn
        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            run_id = VALUES(run_id),
            manager_name = VALUES(manager_name),
            manager_department_name = VALUES(manager_department_name),
            manager_position_name = VALUES(manager_position_name),
            manager_hire_datetime = VALUES(manager_hire_datetime),
            manager_active_yn = VALUES(manager_active_yn)
    """
    top_area_sql = """
        INSERT INTO top_area (
            run_id, top_business_area_id, top_business_area_name,
            top_business_area_level_code, top_business_area_registration_datetime
        ) VALUES (%s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            run_id = VALUES(run_id),
            top_business_area_name = VALUES(top_business_area_name),
            top_business_area_level_code = VALUES(top_business_area_level_code),
            top_business_area_registration_datetime =
                VALUES(top_business_area_registration_datetime)
    """
    area_sql = """
        INSERT INTO area (
            run_id, business_area_id, business_area_name, manager_id,
            parent_business_area_id, top_business_area_id,
            business_area_registration_datetime
        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            run_id = VALUES(run_id),
            business_area_name = VALUES(business_area_name),
            manager_id = VALUES(manager_id),
            parent_business_area_id = VALUES(parent_business_area_id),
            top_business_area_id = VALUES(top_business_area_id),
            business_area_registration_datetime =
                VALUES(business_area_registration_datetime)
    """
    gold_sql = """
        INSERT INTO gold_manager_assignment_features (
            run_id, as_of_datetime, manager_id,
            manager_department_name, manager_position_name,
            manager_active_flag, manager_tenure_days,
            managed_area_count, managed_top_area_count,
            managed_parent_area_count, top_level_area_count,
            average_area_age_days, max_area_age_days,
            cross_top_area_flag, feature_version
        ) VALUES (
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s
        )
        ON DUPLICATE KEY UPDATE
            as_of_datetime = VALUES(as_of_datetime),
            manager_department_name = VALUES(manager_department_name),
            manager_position_name = VALUES(manager_position_name),
            manager_active_flag = VALUES(manager_active_flag),
            manager_tenure_days = VALUES(manager_tenure_days),
            managed_area_count = VALUES(managed_area_count),
            managed_top_area_count = VALUES(managed_top_area_count),
            managed_parent_area_count = VALUES(managed_parent_area_count),
            top_level_area_count = VALUES(top_level_area_count),
            average_area_age_days = VALUES(average_area_age_days),
            max_area_age_days = VALUES(max_area_age_days),
            cross_top_area_flag = VALUES(cross_top_area_flag),
            feature_version = VALUES(feature_version)
    """

    cursor = connection.cursor()
    try:
        connection.start_transaction()
        cursor.executemany(manager_sql, managers)
        cursor.executemany(top_area_sql, top_areas)
        cursor.executemany(area_sql, areas)
        cursor.execute(
            "DELETE FROM gold_manager_assignment_features WHERE run_id = %s",
            (run_id,),
        )
        if gold_rows:
            cursor.executemany(gold_sql, gold_rows)
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()

    return {
        "run_id": run_id,
        "manager_row_count": len(managers),
        "top_area_row_count": len(top_areas),
        "area_row_count": len(areas),
        "manager_target_count": len(managers),
        "manager_loaded_count": len(managers),
        "top_area_target_count": len(top_areas),
        "top_area_loaded_count": len(top_areas),
        "area_target_count": len(areas),
        "area_loaded_count": len(areas),
        "gold_manager_assignment_row_count": len(gold_rows),
        "gold_manager_assignment_target_count": len(gold_rows),
        "gold_manager_assignment_loaded_count": len(gold_rows),
    }
