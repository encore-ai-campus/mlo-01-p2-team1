"""표준화 통과 행을 최종 검증해 Accepted와 Rejected로 나눈다."""

import csv
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from .reconciliation import STANDARDIZATION_RESULT_KEYS, validate_result_shape


BUSINESS_COLUMNS = (
    "business_area_id",
    "business_area_name",
    "parent_business_area_id",
    "parent_business_area_name",
    "top_business_area_id",
    "top_business_area_name",
    "top_business_area_level_code",
    "manager_id",
    "manager_name",
    "manager_department_name",
    "manager_position_name",
    "manager_hire_datetime",
    "manager_active_yn",
    "business_area_registration_datetime",
    "top_business_area_registration_datetime",
)

REQUIRED_VALUE_COLUMNS = tuple(
    column
    for column in BUSINESS_COLUMNS
    if column not in ("parent_business_area_id", "parent_business_area_name")
)

AREA_ID_PATTERN = re.compile(r"^BIZ_[0-9]{5}$")
MANAGER_ID_PATTERN = re.compile(r"^EMP[0-9]{6}$")
DATETIME_FORMAT = "%Y-%m-%dT%H:%M:%S"


def is_blank(value):
    """None 또는 공백 문자열인지 확인한다."""
    return value is None or str(value).strip() == ""


def add_reason(reasons, row_index, message):
    """같은 오류 문구가 한 행에 중복 저장되지 않도록 추가한다."""
    if message not in reasons[row_index]:
        reasons[row_index].append(message)


def validate_required_columns(rows):
    """첫 Accepted 행에 합의된 업무 컬럼이 있는지 확인한다."""
    if not rows:
        return

    missing = [column for column in BUSINESS_COLUMNS if column not in rows[0]]
    if missing:
        raise ValueError(f"Accepted 행에 필수 컬럼이 없습니다: {', '.join(missing)}")


def validate_datetime(value):
    """표준화 결과의 일시가 YYYY-MM-DDTHH:MM:SS 형식인지 확인한다."""
    if is_blank(value):
        return False

    try:
        datetime.strptime(str(value).strip(), DATETIME_FORMAT)
        return True
    except ValueError:
        return False


def validate_each_row(rows, reasons):
    """각 행의 필수값·ID·코드·일시·Top 관계를 검사한다."""
    for index, row in enumerate(rows):
        for column in REQUIRED_VALUE_COLUMNS:
            if is_blank(row.get(column)):
                add_reason(reasons, index, f"필수값 누락: {column}")

        area_id = str(row.get("business_area_id", "")).strip()
        parent_id = str(row.get("parent_business_area_id") or "").strip()
        top_id = str(row.get("top_business_area_id", "")).strip()
        manager_id = str(row.get("manager_id", "")).strip()
        top_level = str(row.get("top_business_area_level_code", "")).strip()

        if area_id and not AREA_ID_PATTERN.fullmatch(area_id):
            add_reason(reasons, index, "업무영역 ID 형식 오류")
        if parent_id and not AREA_ID_PATTERN.fullmatch(parent_id):
            add_reason(reasons, index, "Parent ID 형식 오류")
        if top_id and not AREA_ID_PATTERN.fullmatch(top_id):
            add_reason(reasons, index, "Top ID 형식 오류")
        if manager_id and not MANAGER_ID_PATTERN.fullmatch(manager_id):
            add_reason(reasons, index, "Manager ID 형식 오류")

        if row.get("manager_active_yn") not in ("Y", "N"):
            add_reason(reasons, index, "Manager 활성 여부 허용값 오류")
        if top_level != "TOP":
            add_reason(reasons, index, "Top 레벨 코드 오류")

        for column in (
            "manager_hire_datetime",
            "business_area_registration_datetime",
            "top_business_area_registration_datetime",
        ):
            if not validate_datetime(row.get(column)):
                add_reason(reasons, index, f"일시 형식 오류: {column}")

        if not parent_id and (area_id != top_id or top_level != "TOP"):
            add_reason(reasons, index, "Parent가 NULL인 Area의 Top 관계 불일치")
        if parent_id and area_id == top_id:
            add_reason(reasons, index, "Top Area인데 Parent가 존재함")


def add_entity_conflicts(rows, reasons, key_column, value_columns, entity_name):
    """같은 PK에 서로 다른 유효 속성이 있으면 해당 그룹을 모두 Rejected 처리한다."""
    groups = defaultdict(list)
    for index, row in enumerate(rows):
        key = str(row.get(key_column) or "").strip()
        if key:
            groups[key].append(index)

    for key, indexes in groups.items():
        for column in value_columns:
            values = {
                str(rows[index].get(column)).strip()
                for index in indexes
                if not is_blank(rows[index].get(column))
            }
            if len(values) > 1:
                message = f"{entity_name} 동일 ID 속성 충돌: {key} / {column}"
                for index in indexes:
                    add_reason(reasons, index, message)


def validate_foreign_keys(rows, reasons):
    """Final Accepted에 남는 Top 후보만 기준으로 Parent·Top FK를 검사한다."""
    while True:
        top_ids = {
            str(row.get("top_business_area_id") or "").strip()
            for index, row in enumerate(rows)
            if not reasons[index]
            and not is_blank(row.get("top_business_area_id"))
        }
        changed = False

        for index, row in enumerate(rows):
            if reasons[index]:
                continue

            parent_id = str(row.get("parent_business_area_id") or "").strip()
            top_id = str(row.get("top_business_area_id") or "").strip()

            before_count = len(reasons[index])
            if parent_id and parent_id not in top_ids:
                add_reason(reasons, index, "Parent FK 대상이 Final Accepted에 없음")
            if top_id and top_id not in top_ids:
                add_reason(reasons, index, "Top FK 대상이 Final Accepted에 없음")
            if len(reasons[index]) > before_count:
                changed = True

        if not changed:
            break


def run_normalization(standardization_result):
    """정제 담당자의 결과 딕셔너리를 받아 같은 형식의 최종 결과를 반환한다."""
    validate_result_shape(
        standardization_result,
        "standardization_result",
        STANDARDIZATION_RESULT_KEYS,
    )
    rows = [dict(row) for row in standardization_result["accepted_candidate_row_list"]]
    validate_required_columns(rows)

    reasons = defaultdict(list)
    validate_each_row(rows, reasons)

    add_entity_conflicts(
        rows,
        reasons,
        "business_area_id",
        (
            "business_area_name",
            "manager_id",
            "parent_business_area_id",
            "top_business_area_id",
            "business_area_registration_datetime",
        ),
        "Area",
    )
    add_entity_conflicts(
        rows,
        reasons,
        "manager_id",
        (
            "manager_name",
            "manager_department_name",
            "manager_position_name",
            "manager_hire_datetime",
            "manager_active_yn",
        ),
        "Manager",
    )
    add_entity_conflicts(
        rows,
        reasons,
        "top_business_area_id",
        (
            "top_business_area_name",
            "top_business_area_level_code",
            "top_business_area_registration_datetime",
        ),
        "Top Area",
    )
    validate_foreign_keys(rows, reasons)

    accepted_rows = []
    rejected_rows = []
    for index, row in enumerate(rows):
        if reasons[index]:
            rejected_row = dict(row)
            rejected_row["rejection_reason"] = " | ".join(reasons[index])
            rejected_rows.append(rejected_row)
        else:
            accepted_rows.append(row)

    return {
        "run_id": standardization_result["run_id"],
        "final_accepted_row_count": len(accepted_rows),
        "final_rejected_row_count": len(rejected_rows),
        "final_accepted_row_list": accepted_rows,
        "final_rejected_row_list": rejected_rows,
    }


def count_rejection_reasons(rejected_rows):
    """Rejected 행에 기록된 사유별 발생 건수를 센다."""
    counts = Counter()
    for row in rejected_rows:
        reason_text = row.get("rejection_reason", "")
        reasons = [reason.strip() for reason in reason_text.split("|") if reason.strip()]
        counts.update(reasons)
    return dict(counts)


def collect_fieldnames(rows):
    """행에 등장한 컬럼명을 원래 순서대로 모은다."""
    fieldnames = []
    for row in rows:
        for field in row:
            if field not in fieldnames:
                fieldnames.append(field)
    return fieldnames


def write_csv(path, rows, fallback_fieldnames):
    """딕셔너리 행 목록을 UTF-8 CSV로 저장한다."""
    fieldnames = collect_fieldnames(rows) or list(fallback_fieldnames)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def save_final_outputs(final_result, validation, output_dir):
    """최종 Accepted·Rejected CSV와 검증 JSON을 저장한다."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    accepted_path = output_path / "final_accepted.csv"
    rejected_path = output_path / "final_rejected.csv"
    validation_path = output_path / "final_validation.json"

    write_csv(
        accepted_path,
        final_result["final_accepted_row_list"],
        BUSINESS_COLUMNS,
    )
    write_csv(
        rejected_path,
        final_result["final_rejected_row_list"],
        BUSINESS_COLUMNS + ("rejection_reason",),
    )
    with validation_path.open("w", encoding="utf-8") as file:
        json.dump(validation, file, ensure_ascii=False, indent=2)

    return {
        "final_accepted": str(accepted_path),
        "final_rejected": str(rejected_path),
        "final_validation": str(validation_path),
    }
