"""MongoDB staging and operational history storage.

This module deliberately has no production promotion method. Every record
write is restricted to a run-specific staging collection, and READY state is
blocked until a later explicitly approved stage implements promotion.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from copy import deepcopy
from datetime import datetime
import re
from typing import Any

from pymongo import ASCENDING, MongoClient
from pymongo.collection import Collection
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from .config import PRODUCTION_COLLECTION, Settings
from .models import PAYLOAD_FIELDS, WRAPPER_FIELDS, RunState, ValidationReport


class MongoStorageError(RuntimeError):
    """Base storage error."""


class ProductionProtectionError(MongoStorageError):
    """A write attempted to target production or publish READY data."""


class SourceContractError(MongoStorageError):
    """A source record cannot be stored without changing its contract."""


_SAFE_RUN_ID_RE = re.compile(r"[^A-Za-z0-9]+")


def safe_run_id(run_id: str) -> str:
    """Return a collection-safe token without changing the real lineage key."""

    if not isinstance(run_id, str) or not run_id:
        raise ValueError("run_id must be a non-empty string")
    safe = _SAFE_RUN_ID_RE.sub("_", run_id).strip("_")
    if not safe:
        raise ValueError("run_id has no collection-safe characters")
    return safe


def staging_collection_name(run_id: str, prefix: str) -> str:
    name = f"{prefix}{safe_run_id(run_id)}"
    if len(name.encode("utf-8")) > 120:
        raise ValueError("staging collection name is too long")
    if name == PRODUCTION_COLLECTION:
        raise ProductionProtectionError("staging name resolved to production")
    return name


def _source_contract(record: Mapping[str, Any]) -> None:
    if "_ingest" in record:
        raise SourceContractError("source record already contains _ingest")
    missing_wrapper = [field for field in WRAPPER_FIELDS if field not in record]
    if missing_wrapper:
        raise SourceContractError(f"missing wrapper fields: {missing_wrapper}")
    payload = record.get("payload")
    if not isinstance(payload, Mapping):
        raise SourceContractError("payload must be an object")
    missing_payload = [field for field in PAYLOAD_FIELDS if field not in payload]
    if missing_payload:
        raise SourceContractError(f"missing payload fields: {missing_payload}")


def prepare_staging_document(
    record: Mapping[str, Any],
    *,
    run_id: str,
    source_name: str,
    collected_at: str,
) -> dict[str, Any]:
    """Deep-copy source data and append only the approved lineage envelope."""

    _source_contract(record)
    document = deepcopy(dict(record))
    document["_ingest"] = {
        "run_id": run_id,
        "source_name": source_name,
        "collected_at": collected_at,
    }
    return document


class MongoStorage:
    def __init__(
        self,
        settings: Settings,
        *,
        client: MongoClient[Mapping[str, Any]] | None = None,
        database: Database[Mapping[str, Any]] | None = None,
    ) -> None:
        self.settings = settings
        self._client = client if client is not None else MongoClient(
            settings.mongodb_uri,
            serverSelectionTimeoutMS=settings.request_timeout_seconds * 1000,
        )
        self.database = (
            database
            if database is not None
            else self._client[settings.mongodb_database]
        )

    def ping(self) -> None:
        self._client.admin.command("ping")

    def close(self) -> None:
        self._client.close()

    def staging_name(self, run_id: str) -> str:
        return staging_collection_name(run_id, self.settings.mongodb_staging_prefix)

    def _staging_collection(self, run_id: str) -> Collection[Mapping[str, Any]]:
        name = self.staging_name(run_id)
        self._assert_staging_target(name)
        return self.database[name]

    def _assert_staging_target(self, collection_name: str) -> None:
        if collection_name == self.settings.mongodb_records_collection:
            raise ProductionProtectionError("production collection write blocked")
        if collection_name == PRODUCTION_COLLECTION:
            raise ProductionProtectionError("legacy_records write blocked")
        if not collection_name.startswith(self.settings.mongodb_staging_prefix):
            raise ProductionProtectionError("non-staging record write blocked")

    def create_staging(self, run_id: str) -> str:
        collection = self._staging_collection(run_id)
        if collection.count_documents({}, limit=1):
            raise MongoStorageError(
                f"staging collection already contains data: {collection.name}"
            )
        collection.create_index(
            [("record_id", ASCENDING)], name="uq_record_id", unique=True
        )
        return collection.name

    def insert_full_snapshot(
        self,
        run_id: str,
        records: Iterable[Mapping[str, Any]],
        *,
        source_name: str,
        collected_at: str,
        batch_size: int = 1000,
    ) -> int:
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        collection = self._staging_collection(run_id)
        self.create_staging(run_id)
        inserted = 0
        batch: list[dict[str, Any]] = []
        for record in records:
            batch.append(
                prepare_staging_document(
                    record,
                    run_id=run_id,
                    source_name=source_name,
                    collected_at=collected_at,
                )
            )
            if len(batch) >= batch_size:
                result = collection.insert_many(batch, ordered=True)
                inserted += len(result.inserted_ids)
                batch = []
        if batch:
            result = collection.insert_many(batch, ordered=True)
            inserted += len(result.inserted_ids)
        return inserted

    @property
    def runs(self) -> Collection[Mapping[str, Any]]:
        return self.database[self.settings.mongodb_runs_collection]

    @property
    def manifests(self) -> Collection[Mapping[str, Any]]:
        return self.database[self.settings.mongodb_manifest_collection]

    def ensure_history_indexes(self) -> None:
        self.runs.create_index([("run_id", ASCENDING)], name="uq_run_id", unique=True)
        self.runs.create_index(
            [("source_name", ASCENDING), ("state", ASCENDING), ("ready_at", -1)],
            name="ix_source_state_ready",
        )
        self.manifests.create_index(
            [("run_id", ASCENDING)], name="uq_run_id", unique=True
        )

    def create_run(
        self,
        *,
        run_id: str,
        source_name: str,
        started_at: str,
        expected_rows: int,
    ) -> None:
        if expected_rows < 0:
            raise ValueError("expected_rows must not be negative")
        self.ensure_history_indexes()
        document = {
            "run_id": run_id,
            "source_name": source_name,
            "state": RunState.LOADING.value,
            "staging_collection": self.staging_name(run_id),
            "production_collection": self.settings.mongodb_records_collection,
            "expected_rows": expected_rows,
            "inserted_rows": 0,
            "validation": None,
            "started_at": started_at,
            "validation_started_at": None,
            "ready_at": None,
            "failed_at": None,
            "error": None,
        }
        try:
            self.runs.insert_one(document)
        except DuplicateKeyError as exc:
            raise MongoStorageError(f"run_id already exists: {run_id}") from exc

    def set_inserted_rows(self, run_id: str, inserted_rows: int) -> None:
        result = self.runs.update_one(
            {"run_id": run_id, "state": RunState.LOADING.value},
            {"$set": {"inserted_rows": inserted_rows}},
        )
        if result.matched_count != 1:
            raise MongoStorageError("run is not in loading state")

    def set_expected_rows(self, run_id: str, expected_rows: int) -> None:
        if expected_rows < 0:
            raise ValueError("expected_rows must not be negative")
        result = self.runs.update_one(
            {"run_id": run_id, "state": RunState.LOADING.value},
            {"$set": {"expected_rows": expected_rows}},
        )
        if result.matched_count != 1:
            raise MongoStorageError("run is not in loading state")

    def transition_to_validating(self, run_id: str, *, started_at: str) -> None:
        result = self.runs.update_one(
            {"run_id": run_id, "state": RunState.LOADING.value},
            {
                "$set": {
                    "state": RunState.VALIDATING.value,
                    "validation_started_at": started_at,
                }
            },
        )
        if result.matched_count != 1:
            raise MongoStorageError("loading -> validating transition rejected")

    def mark_failed(
        self,
        run_id: str,
        *,
        failed_at: str,
        error: str,
        validation: Mapping[str, Any] | None = None,
    ) -> None:
        result = self.runs.update_one(
            {
                "run_id": run_id,
                "state": {
                    "$in": [RunState.LOADING.value, RunState.VALIDATING.value]
                },
            },
            {
                "$set": {
                    "state": RunState.FAILED.value,
                    "failed_at": failed_at,
                    "error": error,
                    "validation": deepcopy(dict(validation))
                    if validation is not None
                    else None,
                }
            },
        )
        if result.matched_count != 1:
            raise MongoStorageError("run cannot transition to failed")

    def record_validation(self, report: ValidationReport) -> None:
        if report.passed:
            result = self.runs.update_one(
                {"run_id": report.run_id, "state": RunState.VALIDATING.value},
                {"$set": {"validation": deepcopy(dict(report.as_dict()))}},
            )
            if result.matched_count != 1:
                raise MongoStorageError("validation result update rejected")
            return
        self.mark_failed(
            report.run_id,
            failed_at=datetime.now().astimezone().isoformat(),
            error="staging validation failed",
            validation=report.as_dict(),
        )

    def mark_ready(self, run_id: str) -> None:
        raise ProductionProtectionError(
            "READY transition is disabled until production promotion is approved"
        )

    def mark_ready_after_promotion(
        self,
        run_id: str,
        *,
        ready_at: str,
        post_validation: ValidationReport,
    ) -> None:
        if not post_validation.passed or post_validation.run_id != run_id:
            raise ProductionProtectionError(
                "READY requires a passing production post-validation for this run"
            )
        production_run_ids = self.database[PRODUCTION_COLLECTION].distinct(
            "_ingest.run_id"
        )
        if production_run_ids != [run_id]:
            raise ProductionProtectionError(
                "READY blocked because production run_id does not match"
            )
        result = self.runs.update_one(
            {"run_id": run_id, "state": RunState.VALIDATING.value},
            {"$set": {"state": RunState.READY.value, "ready_at": ready_at}},
        )
        if result.matched_count != 1:
            raise MongoStorageError("validating -> ready transition rejected")

    def store_operational_manifest(
        self,
        file_manifest: Mapping[str, Any],
        *,
        mongodb_validation_status: str,
    ) -> None:
        if mongodb_validation_status not in {"pass", "fail"}:
            raise ValueError("mongodb_validation_status must be pass or fail")
        if file_manifest.get("pipeline_status") != "pending":
            raise MongoStorageError("initial pipeline_status must be pending")
        document = deepcopy(dict(file_manifest))
        document["mongodb_validation_status"] = mongodb_validation_status
        try:
            self.manifests.insert_one(document)
        except DuplicateKeyError as exc:
            raise MongoStorageError(
                f"operational manifest already exists: {file_manifest.get('run_id')}"
            ) from exc
