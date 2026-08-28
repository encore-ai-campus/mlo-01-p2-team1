import re
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timezone as datetime_timezone

from django.conf import settings

try:
    from pymongo import MongoClient
except ImportError:  # Sample mode remains available before optional drivers exist.
    MongoClient = None


class MongoRepositoryError(RuntimeError):
    """Raised when MongoDB rejected-data facts cannot be read."""


ERROR_LABELS = {
    "MISSING_REQUIRED": "필수값 누락",
    "INVALID_DATE_FORMAT": "날짜 형식 오류",
    "INVALID_TYPE": "타입 불일치",
    "DOMAIN_VIOLATION": "도메인 규칙 위반",
    "DUPLICATE": "중복 데이터",
    "REFERENCE_NOT_FOUND": "참조값 없음",
    "OUT_OF_RANGE": "허용범위 초과",
}

SAMPLE_STANDARD_REJECTED = [2, 1, 3, 2, 4, 1, 2, 0, 3, 1, 2, 1]
SAMPLE_FINAL_REJECTED = [1, 0, 1, 1, 0, 1, 0, 1, 1, 0, 1, 0]
RUN_ID_TIMESTAMP_PATTERN = re.compile(r"(?P<timestamp>\d{8}T\d{6}Z)")


def _parse_run_id_started_at(run_id):
    match = RUN_ID_TIMESTAMP_PATTERN.search(str(run_id or ""))
    if not match:
        return None
    try:
        return datetime.strptime(match.group("timestamp"), "%Y%m%dT%H%M%SZ").replace(
            tzinfo=datetime_timezone.utc
        )
    except ValueError:
        return None


def _sample_documents(run_id, stage):
    if stage == "standardization":
        return [
            {
                "run_id": run_id,
                "business_area_id": "BIZ_SAMPLE_001",
                "_source_row_number": 2,
                "errors": [
                    {
                        "error_code": "REJECTED_STANDARDIZATION : MISSING_REQUIRED",
                        "column": "business_area_name",
                        "reason": "필수 컬럼 값이 없거나 NULL 토큰입니다.",
                        "reprocessable": True,
                        "reprocess_status": "PENDING_SOURCE_CORRECTION",
                    },
                    {
                        "error_code": "REJECTED_STANDARDIZATION : INVALID_DATE_FORMAT",
                        "column": "manager_hire_datetime",
                        "reason": "값을 표준 도메인 형식으로 변환할 수 없습니다.",
                        "reprocessable": True,
                        "reprocess_status": "PENDING_SOURCE_CORRECTION",
                    },
                    {
                        "error_code": "REJECTED_STANDARDIZATION : DOMAIN_VIOLATION",
                        "column": "manager_active_yn",
                        "reason": "표준 도메인 규칙을 위반했습니다.",
                        "reprocessable": True,
                        "reprocess_status": "PENDING_SOURCE_CORRECTION",
                    },
                ],
            },
            {
                "run_id": run_id,
                "business_area_id": "BIZ_SAMPLE_002",
                "_source_row_number": 7,
                "errors": [
                    {
                        "error_code": "REJECTED_STANDARDIZATION : MISSING_REQUIRED",
                        "column": "manager_name",
                        "reason": "필수값이 누락되었습니다.",
                        "reprocessable": True,
                        "reprocess_status": "PENDING_SOURCE_CORRECTION",
                    }
                ],
            },
        ]

    return [
        {
            "run_id": run_id,
            "business_area_id": "BIZ_SAMPLE_003",
            "_source_row_number": 11,
            "errors": [
                {
                    "error_code": "REJECTED_NORMALIZATION : REFERENCE_NOT_FOUND",
                    "column": "parent_business_area_id",
                    "reason": "상위 업무영역 참조값을 찾을 수 없습니다.",
                    "reprocessable": True,
                    "reprocess_status": "PENDING_RELATION_RETRY",
                }
            ],
        }
    ]


class MongoRepository:
    """Read-only boundary for the two rejected-data collections.

    A MongoDB document represents one rejected source row. Items inside its
    ``errors`` array represent error occurrences and are counted separately.
    """

    STAGES = ("standardization", "normalization")

    def __init__(self, client=None, database=None, data_mode=None):
        self._client = client
        self._database = database
        self._owns_client = client is None
        self.data_mode = (data_mode or settings.DASHBOARD_DATA_MODE).lower()

    @property
    def database(self):
        if self._database is not None:
            return self._database

        config = settings.MONGODB
        if not settings.MONGODB_CONFIGURED:
            raise MongoRepositoryError("MongoDB environment variables are incomplete.")
        if MongoClient is None:
            raise MongoRepositoryError("PyMongo is not installed.")

        try:
            if self._client is None:
                self._client = MongoClient(
                    config["URI"],
                    serverSelectionTimeoutMS=config["SERVER_SELECTION_TIMEOUT_MS"],
                    connectTimeoutMS=config["CONNECT_TIMEOUT_MS"],
                    tz_aware=True,
                )
            self._database = self._client[config["DATABASE"]]
            return self._database
        except Exception as exc:
            raise MongoRepositoryError("MongoDB client initialization failed.") from exc

    @staticmethod
    def _collection_name(stage):
        config = settings.MONGODB
        if stage == "standardization":
            return config["STANDARDIZATION_REJECTED_COLLECTION"]
        if stage == "normalization":
            return config["NORMALIZATION_REJECTED_COLLECTION"]
        raise ValueError(f"Unsupported rejection stage: {stage}")

    @staticmethod
    def _normalize_error_code(value, stage):
        raw_code = str(value or "").strip()
        if not raw_code:
            return "UNKNOWN_ERROR", True

        expected_prefix = f"REJECTED_{stage.upper()}"
        if ":" not in raw_code:
            return raw_code, False

        prefix, code = (part.strip() for part in raw_code.split(":", maxsplit=1))
        return code or "UNKNOWN_ERROR", prefix != expected_prefix or not code

    @staticmethod
    def _error_label(code):
        return ERROR_LABELS.get(code, code.replace("_", " ").title())

    def _load_documents(self, run_id, stage):
        if self.data_mode != "live":
            return deepcopy(_sample_documents(run_id, stage))

        projection = {
            "run_id": 1,
            "business_area_id": 1,
            "_source_row_number": 1,
            "errors.error_code": 1,
            "errors.status": 1,
            "errors.column": 1,
            "errors.reason": 1,
            "errors.reprocessable": 1,
            "errors.reprocess_status": 1,
        }
        try:
            collection = self.database[self._collection_name(stage)]
            return list(collection.find({"run_id": run_id}, projection))
        except Exception as exc:
            raise MongoRepositoryError(f"MongoDB {stage} rejected query failed.") from exc

    def _summarize_stage(self, run_id, stage, documents):
        error_counts = Counter()
        affected_rows = defaultdict(set)
        column_counts = Counter()
        reprocess_counts = Counter()
        row_identifiers = Counter()
        recent = []
        rows_without_errors = 0
        malformed_error_count = 0
        run_started_at = _parse_run_id_started_at(run_id)

        for document_index, document in enumerate(documents):
            source_row = document.get("_source_row_number")
            row_key = source_row if source_row is not None else f"document-{document_index}"
            row_identifiers[str(row_key)] += 1
            errors = document.get("errors")
            if not isinstance(errors, list) or not errors:
                rows_without_errors += 1
                continue

            record_id = document.get("business_area_id") or f"ROW-{row_key}"
            for error in errors:
                if not isinstance(error, dict):
                    malformed_error_count += 1
                    continue

                raw_code = error.get("error_code") or error.get("status")
                code, malformed = self._normalize_error_code(raw_code, stage)
                malformed_error_count += int(malformed)
                error_counts[code] += 1
                affected_rows[code].add(str(row_key))

                column = str(error.get("column") or "UNKNOWN_COLUMN")
                column_counts[column] += 1
                reprocess_status = str(error.get("reprocess_status") or "UNSPECIFIED")
                reprocess_counts[reprocess_status] += 1
                recent.append(
                    {
                        "run_started_at": run_started_at,
                        "record": str(record_id),
                        "source_row_number": source_row,
                        "stage": stage,
                        "reason": code,
                        "column": column,
                        "reason_text": str(error.get("reason") or ""),
                        "reprocessable": bool(error.get("reprocessable")),
                        "reprocess_status": reprocess_status,
                    }
                )

        duplicate_document_count = sum(count - 1 for count in row_identifiers.values() if count > 1)
        return {
            "stage": stage,
            "collection": self._collection_name(stage),
            "rejected_rows": len(documents),
            "error_occurrences": sum(error_counts.values()),
            "rows_without_errors": rows_without_errors,
            "malformed_error_count": malformed_error_count,
            "duplicate_document_count": duplicate_document_count,
            "error_codes": [
                {
                    "code": code,
                    "label": self._error_label(code),
                    "occurrence_count": count,
                    "affected_row_count": len(affected_rows[code]),
                }
                for code, count in error_counts.most_common()
            ],
            "error_columns": [
                {"column": column, "occurrence_count": count}
                for column, count in column_counts.most_common()
            ],
            "reprocess_statuses": [
                {"status": status, "occurrence_count": count}
                for status, count in reprocess_counts.most_common()
            ],
            "recent_rejections": recent,
        }

    def get_rejection_summary(self, run_id):
        if not run_id:
            raise MongoRepositoryError("run_id is required for rejected-data queries.")

        stage_summaries = {}
        all_recent = []
        combined_codes = Counter()
        combined_affected = Counter()
        combined_columns = Counter()
        combined_reprocess = Counter()

        for stage in self.STAGES:
            documents = self._load_documents(run_id, stage)
            summary = self._summarize_stage(run_id, stage, documents)
            stage_summaries[stage] = summary
            all_recent.extend(summary["recent_rejections"])
            combined_codes.update(
                {item["code"]: item["occurrence_count"] for item in summary["error_codes"]}
            )
            combined_affected.update(
                {item["code"]: item["affected_row_count"] for item in summary["error_codes"]}
            )
            combined_columns.update(
                {item["column"]: item["occurrence_count"] for item in summary["error_columns"]}
            )
            combined_reprocess.update(
                {item["status"]: item["occurrence_count"] for item in summary["reprocess_statuses"]}
            )

        all_recent.sort(
            key=lambda item: (
                item["run_started_at"] is not None,
                item["run_started_at"],
                item["source_row_number"] if item["source_row_number"] is not None else -1,
            ),
            reverse=True,
        )
        return {
            "run_id": run_id,
            "run_started_at": _parse_run_id_started_at(run_id),
            "stages": stage_summaries,
            "total_rejected_rows": sum(item["rejected_rows"] for item in stage_summaries.values()),
            "total_error_occurrences": sum(item["error_occurrences"] for item in stage_summaries.values()),
            "rows_without_errors": sum(item["rows_without_errors"] for item in stage_summaries.values()),
            "malformed_error_count": sum(item["malformed_error_count"] for item in stage_summaries.values()),
            "duplicate_document_count": sum(item["duplicate_document_count"] for item in stage_summaries.values()),
            "error_codes": [
                {
                    "code": code,
                    "label": self._error_label(code),
                    "occurrence_count": count,
                    "affected_row_count": combined_affected[code],
                }
                for code, count in combined_codes.most_common()
            ],
            "error_columns": [
                {"column": column, "occurrence_count": count}
                for column, count in combined_columns.most_common()
            ],
            "reprocess_statuses": [
                {"status": status, "occurrence_count": count}
                for status, count in combined_reprocess.most_common()
            ],
            "recent_rejections": all_recent[:20],
        }

    @staticmethod
    def _sample_index(run_id):
        match = re.search(r"-(\d{4})$", str(run_id or ""))
        return int(match.group(1)) if match else 0

    def get_run_counts(self, run_ids):
        run_ids = [str(run_id) for run_id in run_ids if run_id]
        result = {
            run_id: {
                "standardization": {"rejected_rows": 0, "error_occurrences": 0},
                "normalization": {"rejected_rows": 0, "error_occurrences": 0},
            }
            for run_id in run_ids
        }
        if not run_ids:
            return result

        if self.data_mode != "live":
            for run_id in run_ids:
                index = self._sample_index(run_id)
                standard_rows = SAMPLE_STANDARD_REJECTED[index % len(SAMPLE_STANDARD_REJECTED)]
                normal_rows = SAMPLE_FINAL_REJECTED[index % len(SAMPLE_FINAL_REJECTED)]
                result[run_id]["standardization"] = {
                    "rejected_rows": standard_rows,
                    "error_occurrences": standard_rows + (2 if index == 0 else 0),
                }
                result[run_id]["normalization"] = {
                    "rejected_rows": normal_rows,
                    "error_occurrences": normal_rows,
                }
            return result

        try:
            for stage in self.STAGES:
                collection = self.database[self._collection_name(stage)]
                rows = collection.aggregate(
                    [
                        {"$match": {"run_id": {"$in": run_ids}}},
                        {
                            "$project": {
                                "run_id": 1,
                                "error_count": {"$size": {"$ifNull": ["$errors", []]}},
                            }
                        },
                        {
                            "$group": {
                                "_id": "$run_id",
                                "rejected_rows": {"$sum": 1},
                                "error_occurrences": {"$sum": "$error_count"},
                            }
                        },
                    ]
                )
                for row in rows:
                    run_id = str(row.get("_id") or "")
                    if run_id in result:
                        result[run_id][stage] = {
                            "rejected_rows": int(row.get("rejected_rows") or 0),
                            "error_occurrences": int(row.get("error_occurrences") or 0),
                        }
            return result
        except Exception as exc:
            raise MongoRepositoryError("MongoDB run trend query failed.") from exc

    def close(self):
        if self._owns_client and self._client is not None:
            self._client.close()
            self._client = None
            self._database = None
