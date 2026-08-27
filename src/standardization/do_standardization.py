"""Silver 계층 표준화 파사드.

MongoDB 조회는 호출 계층의 책임이다. 이 모듈은 MongoDB에서 조회한 manifest와
rows를 JSON 객체로 전달받아 컬럼 매핑, 값 표준화, 검증, 결과 격리를 수행한다.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo


CODE_VERSION = "do_standardization(v0.1)"
REJECTED = "REJECTED_STANDARDIZATION"
SCHEMA_MISMATCH = f"{REJECTED} : SCHEMA_MISMATCH"
MISSING_REQUIRED = f"{REJECTED} : MISSING_REQUIRED"
INVALID_TYPE = f"{REJECTED} : INVALID_TYPE"
INVALID_DATE_FORMAT = f"{REJECTED} : INVALID_DATE_FORMAT"
DOMAIN_VIOLATION = f"{REJECTED} : DOMAIN_VIOLATION"

ACCEPTED_FILE = "accepted_candidate_rows.csv"
REJECTED_FILE = "rejected_standardization_rows.csv"
VALIDATION_FILE = "standardization_validation_check.json"

_SAFE_PATH_PART = re.compile(r"^[A-Za-z0-9._-]+$")
_BUSINESS_ID_SOURCE = re.compile(r"^BIZ[\s_-]*([0-9]{5})$", re.IGNORECASE)
_MANAGER_ID_SOURCE = re.compile(r"^EMP[\s_-]*([0-9]{6})$", re.IGNORECASE)
_SCALAR_TYPES = (str, int, float, bool, datetime, date)


class StandardizationError(RuntimeError):
    """표준화 실행을 완료할 수 없을 때 발생한다."""


class IdempotencyConflictError(StandardizationError):
    """동일 run_id 경로에 다른 입력의 산출물이 있을 때 발생한다."""


class RowReconciliationError(StandardizationError):
    """입력 행 수와 판정 결과 행 수를 대사할 수 없을 때 발생한다."""


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    column: str | None
    reason: str
    raw_value: Any = None
    reprocessable: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.code,
            "error_code": self.code,
            "column": self.column,
            "raw_value": _json_safe(self.raw_value),
            "reason": self.reason,
            "reprocessable": self.reprocessable,
            "reprocess_status": (
                "PENDING_SOURCE_CORRECTION"
                if self.reprocessable
                else "NOT_REPROCESSABLE"
            ),
        }


@dataclass
class WorkingRow:
    source_row_number: int
    raw: Any
    mapped: dict[str, Any]
    missing_source_columns: list[str] = field(default_factory=list)
    standardized: dict[str, Any] = field(default_factory=dict)
    issues: list[ValidationIssue] = field(default_factory=list)
    corrections: list[dict[str, Any]] = field(default_factory=list)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _rule_paths(root: Path) -> tuple[Path, Path, Path]:
    directory = root / "docs" / "standardization"
    return (
        directory / "source-to-standard-mapping.csv",
        directory / "standard-terms.csv",
        directory / "domain-rules.yaml",
    )


def _require_files(paths: Iterable[Path]) -> None:
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise StandardizationError(f"필수 규칙 파일이 없습니다: {', '.join(missing)}")


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _read_yaml(path: Path) -> dict[str, Any]:
    """운영에서는 PyYAML, 의존성이 없는 로컬 환경에서는 Ruby YAML을 사용한다."""
    try:
        import yaml  # type: ignore[import-not-found]

        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except ModuleNotFoundError:
        ruby_script = (
            "require 'yaml'; require 'json'; "
            "puts JSON.generate(YAML.safe_load(File.read(ARGV[0]), "
            "permitted_classes: [], aliases: false))"
        )
        try:
            completed = subprocess.run(
                ["ruby", "-e", ruby_script, str(path)],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
        except (FileNotFoundError, subprocess.CalledProcessError) as exc:
            raise StandardizationError(
                "domain-rules.yaml을 읽으려면 PyYAML을 설치해야 합니다."
            ) from exc
        loaded = json.loads(completed.stdout)
    if not isinstance(loaded, dict):
        raise StandardizationError("domain-rules.yaml의 최상위 값은 객체여야 합니다.")
    return loaded


def _parse_payload(payload: str | Mapping[str, Any]) -> tuple[dict[str, Any], list[Any]]:
    if isinstance(payload, str):
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise StandardizationError("입력 문자열이 유효한 JSON이 아닙니다.") from exc
    elif isinstance(payload, Mapping):
        parsed = dict(payload)
    else:
        raise StandardizationError("입력은 JSON 문자열 또는 Mapping 객체여야 합니다.")
    if not isinstance(parsed, dict):
        raise StandardizationError("입력 JSON의 최상위 값은 객체여야 합니다.")
    manifest = parsed.get("manifest")
    rows = parsed.get("rows", parsed.get("data"))
    if not isinstance(manifest, dict):
        raise StandardizationError("입력 JSON에 manifest 객체가 필요합니다.")
    if not isinstance(rows, list):
        raise StandardizationError("입력 JSON에 rows 또는 data 배열이 필요합니다.")
    return dict(manifest), rows


def _remove_white_space(value: Any) -> Any:
    """문자열의 모든 Unicode 공백을 제거하고 중첩 컨테이너를 순회한다."""
    if isinstance(value, str):
        return "".join(value.split())
    if isinstance(value, Mapping):
        return {key: _remove_white_space(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_remove_white_space(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_remove_white_space(item) for item in value)
    return value


def remove_white_space_from_rows(data: Sequence[Any]) -> list[Any]:
    """표준화 대상 문자열의 앞뒤·내부 공백을 제거해 새 목록을 반환한다.

    MongoDB 원본 document 구조이면 ``payload`` 내부만 처리하고 ``_id``, 수집
    메타데이터 및 ``_ingest``는 변경하지 않는다. payload dict 자체가 전달되면
    해당 row 전체를 처리한다. 컬럼명과 원본 ``data``는 변경하지 않는다.
    """
    cleaned_rows: list[Any] = []
    for row in data:
        if isinstance(row, Mapping) and "payload" in row:
            cleaned_document = dict(row)
            cleaned_document["payload"] = _remove_white_space(row["payload"])
            cleaned_rows.append(cleaned_document)
        else:
            cleaned_rows.append(_remove_white_space(row))
    return cleaned_rows


def _standardization_target_rows(data: Sequence[Any]) -> list[Any]:
    """MongoDB document에서는 payload만 표준화 대상으로 추출한다."""
    return [
        row["payload"]
        if isinstance(row, Mapping) and "payload" in row
        else row
        for row in data
    ]


def _manifest_metadata(manifest: Mapping[str, Any]) -> tuple[str, str, str]:
    run_id = str(manifest.get("run_id", "")).strip()
    ingest_date = str(manifest.get("ingest_date", "")).strip()
    if not run_id or not _SAFE_PATH_PART.fullmatch(run_id):
        raise StandardizationError("manifest.run_id가 없거나 안전한 경로 값이 아닙니다.")
    try:
        date.fromisoformat(ingest_date)
    except ValueError as exc:
        raise StandardizationError(
            "manifest.ingest_date는 YYYY-MM-DD 형식이어야 합니다."
        ) from exc
    supplied_time = next(
        (
            manifest[key]
            for key in ("processed_at", "processing_time", "ingested_at", "created_at")
            if manifest.get(key)
        ),
        None,
    )
    processed_at = (
        str(supplied_time)
        if supplied_time
        else datetime.now(ZoneInfo("Asia/Seoul")).isoformat(timespec="seconds")
    )
    return run_id, ingest_date, processed_at


def _load_mapping(path: Path) -> list[dict[str, str]]:
    mapping = _read_csv(path)
    required = {"source_column", "standard_column", "domain_id", "nullable"}
    if not mapping or not required.issubset(mapping[0]):
        raise StandardizationError("source-to-standard-mapping.csv 구조가 올바르지 않습니다.")
    sources = [item["source_column"] for item in mapping]
    standards = [item["standard_column"] for item in mapping]
    if len(sources) != len(set(sources)) or len(standards) != len(set(standards)):
        raise StandardizationError("컬럼 매핑에 중복 컬럼이 있습니다.")
    return mapping


def _working_rows(
    data: Sequence[Any], mapping: Sequence[Mapping[str, str]]
) -> list[WorkingRow]:
    result: list[WorkingRow] = []
    source_columns = [item["source_column"] for item in mapping]
    for number, raw in enumerate(data, start=1):
        if not isinstance(raw, Mapping):
            result.append(
                WorkingRow(
                    source_row_number=number,
                    raw=raw,
                    mapped={},
                    missing_source_columns=source_columns.copy(),
                    issues=[
                        ValidationIssue(
                            SCHEMA_MISMATCH,
                            None,
                            "원천 row가 JSON 객체가 아닙니다.",
                            raw,
                        )
                    ],
                )
            )
            continue
        mapped = {
            item["standard_column"]: raw[item["source_column"]]
            for item in mapping
            if item["source_column"] in raw
        }
        missing = [column for column in source_columns if column not in raw]
        result.append(
            WorkingRow(number, dict(raw), mapped, missing_source_columns=missing)
        )
    return result


def do_column_mapping(
    data: Sequence[Any], mapping_path: str | Path | None = None
) -> list[dict[str, Any]]:
    """매핑 CSV에 따라 원천 컬럼을 표준 컬럼으로 변경한다.

    규칙 대상이 아닌 MongoDB 메타 컬럼은 표준 데이터 결과에서 제외한다.
    """
    path = Path(mapping_path) if mapping_path else _rule_paths(_project_root())[0]
    mapping = _load_mapping(path)
    return [row.mapped for row in _working_rows(data, mapping)]


def _append_issue(row: WorkingRow, issue: ValidationIssue) -> None:
    key = (issue.code, issue.column, issue.reason)
    existing = {(item.code, item.column, item.reason) for item in row.issues}
    if key not in existing:
        row.issues.append(issue)


def check_schema(rows: Sequence[WorkingRow]) -> None:
    """1단계: 매핑에 필요한 원천 컬럼 존재 여부를 검사한다."""
    for row in rows:
        if row.missing_source_columns:
            _append_issue(
                row,
                ValidationIssue(
                    SCHEMA_MISMATCH,
                    None,
                    "매핑 대상 원천 컬럼이 없습니다: "
                    + ", ".join(row.missing_source_columns),
                    row.missing_source_columns,
                ),
            )


def _normalize_text(value: Any) -> str:
    value = unicodedata.normalize("NFKC", str(value))
    value = re.sub(
        r"[\t\u00a0\u1680\u2000-\u200a\u202f\u205f\u3000]", " ", value
    )
    return re.sub(r"\s+", " ", value).strip()


def _is_null(value: Any, extra_tokens: Iterable[str] = ()) -> bool:
    if value is None:
        return True
    if not isinstance(value, _SCALAR_TYPES):
        return False
    normalized = _normalize_text(value).upper()
    tokens = {"", "-", "NULL", "N/A", "NA", "UNKNOWN"}
    tokens.update(_normalize_text(token).upper() for token in extra_tokens)
    return normalized in tokens


def check_required_and_type(
    rows: Sequence[WorkingRow], terms: Sequence[Mapping[str, str]]
) -> None:
    """2단계: 필수값과 입력 값 타입을 검사한다."""
    nullable = {
        term["physical_name"]: term.get("nullable", "N").strip().upper() == "Y"
        for term in terms
    }
    for row in rows:
        for column, is_nullable in nullable.items():
            if column not in row.mapped:
                continue
            value = row.mapped[column]
            if value is not None and not isinstance(value, _SCALAR_TYPES):
                _append_issue(
                    row,
                    ValidationIssue(
                        INVALID_TYPE,
                        column,
                        "문자열 또는 기본 스칼라로 변환할 수 없는 타입입니다.",
                        value,
                    ),
                )
                continue
            extra = ("없음",) if column == "parent_business_area_id" else ()
            if not is_nullable and _is_null(value, extra):
                _append_issue(
                    row,
                    ValidationIssue(
                        MISSING_REQUIRED,
                        column,
                        "필수 컬럼 값이 없거나 NULL 토큰입니다.",
                        value,
                    ),
                )


def _business_id(value: Any) -> str | None:
    match = _BUSINESS_ID_SOURCE.fullmatch(_normalize_text(value))
    return f"BIZ_{match.group(1)}" if match else None


def _manager_id(value: Any) -> str | None:
    match = _MANAGER_ID_SOURCE.fullmatch(_normalize_text(value))
    return f"EMP{match.group(1)}" if match else None


def _datetime_value(value: Any, config: Mapping[str, Any]) -> str | None:
    if isinstance(value, datetime):
        parsed: datetime | None = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, datetime.min.time())
    else:
        text = _normalize_text(value)
        invalid_sentinels = {
            "".join(str(item).split())
            for item in config.get("invalid_sentinels", [])
        }
        if "".join(text.split()) in invalid_sentinels:
            return None
        parsed = None
        for source_format in config.get("accepted_source_formats", []):
            formats = dict.fromkeys(
                (str(source_format), "".join(str(source_format).split()))
            )
            for candidate_format in formats:
                try:
                    parsed = datetime.strptime(text, candidate_format)
                    break
                except ValueError:
                    pass
            if parsed is not None:
                break
        if parsed is None:
            return None
    return parsed.strftime(str(config.get("target_format", "%Y-%m-%dT%H:%M:%S")))


def _standardize_value(
    column: str, value: Any, policy: Mapping[str, Any]
) -> Any:
    if column == "parent_business_area_id" and _is_null(value, ("없음",)):
        return None
    if _is_null(value):
        return None
    if not isinstance(value, _SCALAR_TYPES):
        return value
    if column in {"business_area_id", "top_business_area_id"}:
        return _business_id(value)
    if column == "parent_business_area_id":
        return _business_id(value)
    if column == "manager_id":
        return _manager_id(value)
    if column.endswith("_datetime"):
        return _datetime_value(value, policy.get("datetime", {}))
    if column == "top_business_area_level_code":
        text = "".join(_normalize_text(value).split()).upper()
        value_map = {
            "".join(_normalize_text(key).split()).upper(): mapped
            for key, mapped in policy.get("top_area_level_code", {})
            .get("value_map", {})
            .items()
        }
        return value_map.get(text, text)
    if column == "manager_active_yn":
        text = "".join(_normalize_text(value).split()).upper()
        value_map = {
            "".join(_normalize_text(key).split()).upper(): mapped
            for key, mapped in policy.get("manager_active_yn", {})
            .get("value_map", {})
            .items()
        }
        # YAML 1.1 loader가 따옴표 없는 YES/NO를 TRUE/FALSE로 읽는 경우 방어한다.
        if "YES" not in value_map and "TRUE" in value_map:
            value_map["YES"] = value_map["TRUE"]
        if "NO" not in value_map and "FALSE" in value_map:
            value_map["NO"] = value_map["FALSE"]
        return value_map.get(text, text)
    if column == "manager_position_name":
        text = _normalize_text(value)
        allowed = set(
            policy.get("manager_position_name", {}).get("allowed_values", [])
        )
        compact = text.replace(" ", "")
        return compact if compact in allowed else text
    return _normalize_text(value)


def _record_correction(
    row: WorkingRow, column: str, before: Any, after: Any
) -> None:
    if before != after:
        row.corrections.append(
            {
                "column": column,
                "before": _json_safe(before),
                "after": _json_safe(after),
            }
        )


def check_domains(
    rows: Sequence[WorkingRow],
    terms: Sequence[Mapping[str, str]],
    rules: Mapping[str, Any],
) -> None:
    """3단계: 안전한 값은 보정하고 도메인을 벗어난 값은 거부한다."""
    domains = {
        item["domain_id"]: item
        for item in rules.get("domains", [])
        if isinstance(item, dict) and item.get("domain_id")
    }
    policy = rules.get("normalization_policy", {})
    for row in rows:
        for term in terms:
            column = term["physical_name"]
            if column not in row.mapped:
                continue
            raw_value = row.mapped[column]
            if any(
                issue.column == column and issue.code == INVALID_TYPE
                for issue in row.issues
            ):
                row.standardized[column] = raw_value
                continue
            value = _standardize_value(column, raw_value, policy)
            row.standardized[column] = value
            _record_correction(row, column, raw_value, value)
            is_nullable = term.get("nullable", "N").strip().upper() == "Y"
            domain = domains.get(term["domain_id"])
            if not domain:
                _append_issue(
                    row,
                    ValidationIssue(
                        SCHEMA_MISMATCH,
                        column,
                        f"참조 도메인이 없습니다: {term['domain_id']}",
                        raw_value,
                        False,
                    ),
                )
                continue
            if value is None:
                already_missing = any(
                    issue.column == column and issue.code == MISSING_REQUIRED
                    for issue in row.issues
                )
                if not is_nullable and not already_missing:
                    code = (
                        INVALID_DATE_FORMAT
                        if domain.get("logical_type") == "datetime"
                        else DOMAIN_VIOLATION
                    )
                    _append_issue(
                        row,
                        ValidationIssue(
                            code,
                            column,
                            "값을 표준 도메인 형식으로 변환할 수 없습니다.",
                            raw_value,
                        ),
                    )
                continue
            allowed = domain.get("allowed_values") or []
            if allowed and value not in allowed:
                _append_issue(
                    row,
                    ValidationIssue(
                        DOMAIN_VIOLATION,
                        column,
                        f"승인된 허용값이 아닙니다: {allowed}",
                        raw_value,
                    ),
                )
                continue
            pattern = domain.get("format")
            if pattern and domain.get("logical_type") != "datetime":
                try:
                    valid_format = re.fullmatch(str(pattern), str(value)) is not None
                except re.error as exc:
                    raise StandardizationError(
                        f"도메인 {term['domain_id']}의 정규식이 잘못되었습니다."
                    ) from exc
                if not valid_format:
                    _append_issue(
                        row,
                        ValidationIssue(
                            DOMAIN_VIOLATION,
                            column,
                            f"도메인 형식 {pattern}에 맞지 않습니다.",
                            raw_value,
                        ),
                    )
                    continue
            maximum_length = domain.get("length")
            if maximum_length and len(str(value)) > int(maximum_length):
                _append_issue(
                    row,
                    ValidationIssue(
                        DOMAIN_VIOLATION,
                        column,
                        f"최대 길이 {maximum_length}자를 초과했습니다.",
                        raw_value,
                    ),
                )


def check_validations(
    data: Sequence[Any],
    *,
    mapping_path: str | Path,
    terms_path: str | Path,
    domain_rules_path: str | Path,
) -> tuple[list[WorkingRow], list[WorkingRow], list[str]]:
    """세 검사를 순서대로 호출하고 accepted/rejected 행을 분리한다."""
    mapping = _load_mapping(Path(mapping_path))
    terms = _read_csv(Path(terms_path))
    rules = _read_yaml(Path(domain_rules_path))
    standard_columns = [item["standard_column"] for item in mapping]
    term_columns = [item.get("physical_name") for item in terms]
    if standard_columns != term_columns:
        raise StandardizationError(
            "mapping과 standard-terms의 표준 컬럼 순서가 일치하지 않습니다."
        )
    rows = _working_rows(data, mapping)
    check_schema(rows)
    check_required_and_type(rows, terms)
    check_domains(rows, terms, rules)
    for row in rows:
        for column in standard_columns:
            if column in row.mapped and column not in row.standardized:
                row.standardized[column] = row.mapped[column]
    return (
        [row for row in rows if not row.issues],
        [row for row in rows if row.issues],
        standard_columns,
    )


def _json_safe(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return repr(value)


def _idempotency_key(
    manifest: Mapping[str, Any], data: Sequence[Any], paths: Sequence[Path]
) -> str:
    stable_manifest = {
        key: _json_safe(value)
        for key, value in manifest.items()
        if key not in {"processed_at", "processing_time"}
    }
    canonical = json.dumps(
        {"manifest": stable_manifest, "rows": _json_safe(data)},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(CODE_VERSION.encode("utf-8") + canonical.encode("utf-8"))
    for path in paths:
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _metadata(run_id: str, processed_at: str) -> list[str]:
    return [
        f"# run_id={run_id}",
        f"# processed_at={processed_at}",
        f"# code_version={CODE_VERSION}",
    ]


def _csv_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, (Mapping, list, tuple, set)):
        return json.dumps(_json_safe(value), ensure_ascii=False, sort_keys=True)
    return _json_safe(value)


def _write_csv(
    path: Path,
    run_id: str,
    processed_at: str,
    fieldnames: Sequence[str],
    rows: Iterable[Mapping[str, Any]],
) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        for line in _metadata(run_id, processed_at):
            handle.write(line + "\n")
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_value(row.get(key)) for key in fieldnames})


def _read_result_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        for _ in range(3):
            next(handle, None)
        return list(csv.DictReader(handle))


def _write_report(path: Path, report: Mapping[str, Any]) -> None:
    """첫 3줄에 메타데이터, 마지막 줄에 완료 비율을 둔 유효 JSON을 쓴다."""
    values = dict(report)
    run_id = values.pop("run_id")
    processed_at = values.pop("processed_at")
    code_version = values.pop("code_version")
    completion = values.pop("validation_completion_rate")
    lines = [
        "{" + json.dumps("run_id") + ": " + json.dumps(run_id, ensure_ascii=False) + ",",
        "  " + json.dumps("processed_at") + ": " + json.dumps(processed_at, ensure_ascii=False) + ",",
        "  " + json.dumps("code_version") + ": " + json.dumps(code_version) + ",",
    ]
    middle = json.dumps(values, ensure_ascii=False, indent=2)[1:-1].strip("\n")
    if middle:
        middle_lines = middle.splitlines()
        middle_lines[-1] += ","
        lines.extend(middle_lines)
    lines.append(
        "  "
        + json.dumps("validation_completion_rate")
        + ": "
        + json.dumps(completion)
        + "}"
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _accepted_row(row: WorkingRow, columns: Sequence[str]) -> dict[str, Any]:
    return {column: row.standardized.get(column) for column in columns}


def _rejected_row(row: WorkingRow, columns: Sequence[str]) -> dict[str, Any]:
    result = _accepted_row(row, columns)
    result.update(
        {
            "_source_row_number": row.source_row_number,
            "errors": [issue.to_dict() for issue in row.issues],
            "reprocessable": all(issue.reprocessable for issue in row.issues),
            "reprocess_status": (
                "PENDING_SOURCE_CORRECTION"
                if all(issue.reprocessable for issue in row.issues)
                else "NOT_REPROCESSABLE"
            ),
        }
    )
    return result


def _rejected_csv_row(row: WorkingRow, columns: Sequence[str]) -> dict[str, Any]:
    result = _accepted_row(row, columns)
    result.update(
        {
            "_source_row_number": row.source_row_number,
            "_rejection_status": REJECTED,
            "_error_codes": [issue.code for issue in row.issues],
            "_error_reasons": [issue.reason for issue in row.issues],
            "_reprocessable": all(issue.reprocessable for issue in row.issues),
            "_reprocess_status": (
                "PENDING_SOURCE_CORRECTION"
                if all(issue.reprocessable for issue in row.issues)
                else "NOT_REPROCESSABLE"
            ),
            "_raw_payload": row.raw,
        }
    )
    return result


def _existing_result(directory: Path, run_id: str) -> dict[str, Any]:
    accepted = _read_result_csv(directory / ACCEPTED_FILE)
    rejected_csv = _read_result_csv(directory / REJECTED_FILE)
    report = json.loads((directory / VALIDATION_FILE).read_text(encoding="utf-8"))
    return {
        "run_id": run_id,
        "accepted_candidate_row_count": len(accepted),
        "rejected_row_count": len(rejected_csv),
        "accepted_candidate_row_list": accepted,
        "rejected_row_list": report.get("rejected_rows", []),
        "output_dir": str(directory),
        "idempotent_reuse": True,
    }


def do_standardization(
    payload: str | Mapping[str, Any],
    *,
    project_root: str | Path | None = None,
    output_root: str | Path | None = None,
) -> dict[str, Any]:
    """컬럼 매핑부터 검증 산출물 생성까지 수행하는 메인 파사드.

    payload는 ``{"manifest": {...}, "rows": [...]}`` 형식이다. ``data`` 키도
    ``rows``의 별칭으로 허용한다. rows가 MongoDB 원본 document이면 각 document의
    ``payload``만 표준화하며 나머지 필드는 변경하거나 검증하지 않는다. 기존처럼
    payload dict 목록을 직접 전달하는 방식도 허용한다.
    """
    root = Path(project_root).resolve() if project_root else _project_root()
    mapping_path, terms_path, domain_path = _rule_paths(root)
    rule_paths = (mapping_path, terms_path, domain_path)
    _require_files(rule_paths)
    manifest, data = _parse_payload(payload)
    data = remove_white_space_from_rows(data)
    data = _standardization_target_rows(data)
    run_id, ingest_date, processed_at = _manifest_metadata(manifest)
    identity = _idempotency_key(manifest, data, rule_paths)
    base = (
        Path(output_root).resolve()
        if output_root
        else root / "data" / "silver" / "standardization"
    )
    directory = base / f"ingest_date={ingest_date}" / f"run_id={run_id}"
    expected = [directory / ACCEPTED_FILE, directory / REJECTED_FILE, directory / VALIDATION_FILE]
    if directory.exists():
        if all(path.is_file() for path in expected):
            try:
                existing = json.loads(expected[2].read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise IdempotencyConflictError(
                    f"run_id={run_id}의 기존 검증 파일이 손상되었습니다."
                ) from exc
            if existing.get("idempotency_key") == identity:
                return _existing_result(directory, run_id)
        raise IdempotencyConflictError(
            f"run_id={run_id} 경로에 다른 입력 또는 불완전한 산출물이 있습니다."
        )

    accepted, rejected, columns = check_validations(
        data,
        mapping_path=mapping_path,
        terms_path=terms_path,
        domain_rules_path=domain_path,
    )
    accepted_rows = [_accepted_row(row, columns) for row in accepted]
    rejected_rows = [_rejected_row(row, columns) for row in rejected]

    directory.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{run_id}-", dir=directory.parent))
    try:
        _write_csv(
            staging / ACCEPTED_FILE,
            run_id,
            processed_at,
            columns,
            accepted_rows,
        )
        rejected_metadata = [
            "_source_row_number",
            "_rejection_status",
            "_error_codes",
            "_error_reasons",
            "_reprocessable",
            "_reprocess_status",
            "_raw_payload",
        ]
        _write_csv(
            staging / REJECTED_FILE,
            run_id,
            processed_at,
            [*columns, *rejected_metadata],
            (_rejected_csv_row(row, columns) for row in rejected),
        )

        # 요구사항에 따라 실제로 생성된 두 CSV를 다시 읽어 행 수를 대사한다.
        accepted_count = len(_read_result_csv(staging / ACCEPTED_FILE))
        rejected_count = len(_read_result_csv(staging / REJECTED_FILE))
        validated_count = accepted_count + rejected_count
        reconciled = validated_count == len(data)
        completion_rate = validated_count / len(data) if data else 1.0
        error_counts = Counter(issue.code for row in rejected for issue in row.issues)
        report = {
            "run_id": run_id,
            "processed_at": processed_at,
            "code_version": CODE_VERSION,
            "status": "COMPLETED" if reconciled else "FAILED_ROW_RECONCILIATION",
            "idempotency_key": identity,
            "input_row_count": len(data),
            "accepted_candidate_row_count": accepted_count,
            "rejected_row_count": rejected_count,
            "validated_row_count": validated_count,
            "error_code_counts": dict(sorted(error_counts.items())),
            "checks": {
                "schema": {
                    "error_code": SCHEMA_MISMATCH,
                    "failed_row_count": sum(
                        any(issue.code == SCHEMA_MISMATCH for issue in row.issues)
                        for row in rejected
                    ),
                },
                "required": {
                    "error_code": MISSING_REQUIRED,
                    "failed_row_count": sum(
                        any(issue.code == MISSING_REQUIRED for issue in row.issues)
                        for row in rejected
                    ),
                },
                "type_and_date": {
                    "error_codes": [INVALID_TYPE, INVALID_DATE_FORMAT],
                    "failed_row_count": sum(
                        any(
                            issue.code in {INVALID_TYPE, INVALID_DATE_FORMAT}
                            for issue in row.issues
                        )
                        for row in rejected
                    ),
                },
                "domain": {
                    "error_code": DOMAIN_VIOLATION,
                    "failed_row_count": sum(
                        any(issue.code == DOMAIN_VIOLATION for issue in row.issues)
                        for row in rejected
                    ),
                },
            },
            "rejected_rows": [
                {
                    "source_row_number": row.source_row_number,
                    "errors": [issue.to_dict() for issue in row.issues],
                    "corrections": row.corrections,
                    "reprocessable": all(
                        issue.reprocessable for issue in row.issues
                    ),
                    "reprocess_status": (
                        "PENDING_SOURCE_CORRECTION"
                        if all(issue.reprocessable for issue in row.issues)
                        else "NOT_REPROCESSABLE"
                    ),
                }
                for row in rejected
            ],
            "row_reconciliation": {
                "input_row_count": len(data),
                "accepted_plus_rejected_row_count": validated_count,
                "matched": reconciled,
            },
            "validation_completion_rate": completion_rate,
        }
        _write_report(staging / VALIDATION_FILE, report)
        os.replace(staging, directory)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    if not reconciled:
        raise RowReconciliationError(
            f"입력 {len(data)}건과 판정 결과 {validated_count}건이 일치하지 않습니다."
        )
    return {
        "run_id": run_id,
        "accepted_candidate_row_count": len(accepted_rows),
        "rejected_row_count": len(rejected_rows),
        "accepted_candidate_row_list": accepted_rows,
        "rejected_row_list": rejected_rows,
        "output_dir": str(directory),
        "idempotent_reuse": False,
    }


__all__ = [
    "CODE_VERSION",
    "DOMAIN_VIOLATION",
    "INVALID_DATE_FORMAT",
    "INVALID_TYPE",
    "MISSING_REQUIRED",
    "SCHEMA_MISMATCH",
    "IdempotencyConflictError",
    "RowReconciliationError",
    "StandardizationError",
    "check_domains",
    "check_required_and_type",
    "check_schema",
    "check_validations",
    "do_column_mapping",
    "do_standardization",
    "remove_white_space_from_rows",
]
