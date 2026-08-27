"""Staging-only MongoDB validation for a full Bronze snapshot."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from pymongo.collection import Collection

from .models import PAYLOAD_FIELDS, WRAPPER_FIELDS, ValidationCheck, ValidationReport


def _missing_query(paths: Sequence[str]) -> Mapping[str, Any]:
    return {"$or": [{path: {"$exists": False}} for path in paths]}


def validate_staging(
    collection: Collection[Mapping[str, Any]],
    *,
    api_records: Sequence[Mapping[str, Any]],
    run_id: str,
    source_name: str,
) -> ValidationReport:
    expected_rows = len(api_records)
    document_count = collection.count_documents({})
    distinct_record_ids = len(collection.distinct("record_id"))
    duplicate_groups = list(
        collection.aggregate(
            [
                {"$group": {"_id": "$record_id", "count": {"$sum": 1}}},
                {"$match": {"count": {"$gt": 1}}},
                {"$count": "groups"},
            ]
        )
    )
    duplicate_count = duplicate_groups[0]["groups"] if duplicate_groups else 0
    missing_wrapper_count = collection.count_documents(_missing_query(WRAPPER_FIELDS))
    missing_payload_count = collection.count_documents(
        _missing_query(tuple(f"payload.{field}" for field in PAYLOAD_FIELDS))
    )
    run_id_mismatch_count = collection.count_documents(
        {"_ingest.run_id": {"$ne": run_id}}
    )
    source_name_mismatch_count = collection.count_documents(
        {"_ingest.source_name": {"$ne": source_name}}
    )

    expected_checksums: dict[Any, Any] = {}
    duplicate_api_ids = Counter(record.get("record_id") for record in api_records)
    for record in api_records:
        expected_checksums[record.get("record_id")] = record.get(
            "source_record_sha256"
        )
    checksum_mismatch_count = 0
    for document in collection.find(
        {}, {"_id": 0, "record_id": 1, "source_record_sha256": 1}
    ):
        if expected_checksums.get(document.get("record_id")) != document.get(
            "source_record_sha256"
        ):
            checksum_mismatch_count += 1
    missing_from_mongo = set(expected_checksums) - set(collection.distinct("record_id"))
    checksum_mismatch_count += len(missing_from_mongo)

    checks = (
        ValidationCheck(
            "row_count",
            expected_rows == document_count,
            expected_rows,
            document_count,
        ),
        ValidationCheck(
            "distinct_record_id",
            document_count == distinct_record_ids,
            document_count,
            distinct_record_ids,
        ),
        ValidationCheck("duplicate_record_id", duplicate_count == 0, 0, duplicate_count),
        ValidationCheck(
            "api_duplicate_record_id",
            all(count == 1 for count in duplicate_api_ids.values()),
            0,
            sum(count - 1 for count in duplicate_api_ids.values() if count > 1),
        ),
        ValidationCheck(
            "missing_wrapper_fields", missing_wrapper_count == 0, 0, missing_wrapper_count
        ),
        ValidationCheck(
            "missing_payload_fields", missing_payload_count == 0, 0, missing_payload_count
        ),
        ValidationCheck(
            "source_record_sha256_mismatch",
            checksum_mismatch_count == 0,
            0,
            checksum_mismatch_count,
        ),
        ValidationCheck("run_id_mismatch", run_id_mismatch_count == 0, 0, run_id_mismatch_count),
        ValidationCheck(
            "source_name_mismatch",
            source_name_mismatch_count == 0,
            0,
            source_name_mismatch_count,
        ),
    )
    return ValidationReport(run_id=run_id, checks=checks)
