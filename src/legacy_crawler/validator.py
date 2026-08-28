"""MongoDB validation for legacy staging and page-append production."""

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


def validate_appended_page(
    collection: Collection[Mapping[str, Any]],
    *,
    api_records: Sequence[Mapping[str, Any]],
    run_id: str,
    source_name: str,
) -> ValidationReport:
    """Validate only the production documents owned by one page run."""

    expected_rows = len(api_records)
    query = {"_ingest.run_id": run_id}
    documents = list(collection.find(query))
    expected_hashes = {
        record.get("record_id"): record.get("source_record_sha256")
        for record in api_records
    }
    actual_hashes = {
        document.get("record_id"): document.get("source_record_sha256")
        for document in documents
    }
    hash_mismatches = sum(
        actual_hashes.get(record_id) != checksum
        for record_id, checksum in expected_hashes.items()
    )
    record_ids = [document.get("record_id") for document in documents]
    source_rows = [document.get("source_row_no") for document in documents]
    missing_wrapper = sum(
        any(field not in document for field in WRAPPER_FIELDS)
        for document in documents
    )
    missing_payload = sum(
        not isinstance(document.get("payload"), Mapping)
        or any(field not in document["payload"] for field in PAYLOAD_FIELDS)
        for document in documents
    )
    checks = (
        ValidationCheck("page_row_count", len(documents) == expected_rows, expected_rows, len(documents)),
        ValidationCheck("page_distinct_record_id", len(set(record_ids)) == expected_rows, expected_rows, len(set(record_ids))),
        ValidationCheck("page_distinct_source_row_no", len(set(source_rows)) == expected_rows, expected_rows, len(set(source_rows))),
        ValidationCheck("page_source_hash_preserved", hash_mismatches == 0 and len(actual_hashes) == expected_rows, 0, hash_mismatches),
        ValidationCheck("page_missing_wrapper", missing_wrapper == 0, 0, missing_wrapper),
        ValidationCheck("page_missing_payload", missing_payload == 0, 0, missing_payload),
        ValidationCheck(
            "page_source_name",
            all(document.get("_ingest", {}).get("source_name") == source_name for document in documents),
            source_name,
            sorted({document.get("_ingest", {}).get("source_name") for document in documents}),
        ),
    )
    return ValidationReport(run_id=run_id, checks=checks)


def validate_accumulated_production(
    collection: Collection[Mapping[str, Any]],
    *,
    expected_rows: int,
    source_name: str,
    run_id: str,
) -> ValidationReport:
    """Validate the complete multi-run production collection."""

    count = collection.count_documents({})
    record_ids = collection.distinct("record_id")
    source_rows = collection.distinct("source_row_no")
    duplicate_record_groups = list(collection.aggregate([
        {"$group": {"_id": "$record_id", "count": {"$sum": 1}}},
        {"$match": {"count": {"$gt": 1}}},
        {"$count": "groups"},
    ]))
    duplicate_source_groups = list(collection.aggregate([
        {"$group": {"_id": "$source_row_no", "count": {"$sum": 1}}},
        {"$match": {"count": {"$gt": 1}}},
        {"$count": "groups"},
    ]))
    duplicate_records = duplicate_record_groups[0]["groups"] if duplicate_record_groups else 0
    duplicate_sources = duplicate_source_groups[0]["groups"] if duplicate_source_groups else 0
    source_names = collection.distinct("_ingest.source_name")
    checks = (
        ValidationCheck("production_row_count", count == expected_rows, expected_rows, count),
        ValidationCheck("production_distinct_record_id", len(record_ids) == expected_rows, expected_rows, len(record_ids)),
        ValidationCheck("production_duplicate_record_id", duplicate_records == 0, 0, duplicate_records),
        ValidationCheck("production_distinct_source_row_no", len(source_rows) == expected_rows, expected_rows, len(source_rows)),
        ValidationCheck("production_duplicate_source_row_no", duplicate_sources == 0, 0, duplicate_sources),
        ValidationCheck("production_source_name", source_names == [source_name], [source_name], source_names),
    )
    return ValidationReport(run_id=run_id, checks=checks)
