"""No-dropTarget production promotion with rollback preservation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import csv
import json
from pathlib import Path
from typing import Any, Mapping

from pymongo.collection import Collection

from .config import PRODUCTION_COLLECTION
from .manifest import validate_file_manifest
from .models import PAYLOAD_FIELDS, WRAPPER_FIELDS, RawArtifact, ValidationCheck, ValidationReport
from .mongo_storage import MongoStorage, ProductionProtectionError, safe_run_id
from .publisher import RunLock, validate_staged_files
from .serializers import sha256_file


class PromotionError(RuntimeError):
    """Promotion was blocked or rolled back."""


@dataclass(frozen=True, slots=True)
class PromotionResult:
    run_id: str
    previous_run_ids: tuple[str, ...]
    backup_collection: str
    production_collection: str
    post_validation: ValidationReport
    ready_at: str


def validate_collection_shape(
    collection: Collection[Mapping[str, Any]],
    *,
    run_id: str,
    source_name: str,
    expected_rows: int,
) -> ValidationReport:
    count = collection.count_documents({})
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
    run_ids = collection.distinct("_ingest.run_id")
    source_names = collection.distinct("_ingest.source_name")
    missing_wrapper = collection.count_documents(
        {"$or": [{field: {"$exists": False}} for field in WRAPPER_FIELDS]}
    )
    missing_payload = collection.count_documents(
        {
            "$or": [
                {f"payload.{field}": {"$exists": False}} for field in PAYLOAD_FIELDS
            ]
        }
    )
    indexes = {index["name"]: index for index in collection.list_indexes()}
    unique_index = indexes.get("uq_record_id")
    index_ok = bool(
        unique_index
        and unique_index.get("key") == {"record_id": 1}
        and unique_index.get("unique") is True
    )
    checks = (
        ValidationCheck("production_row_count", count == expected_rows, expected_rows, count),
        ValidationCheck("production_distinct_record_id", distinct_record_ids == expected_rows, expected_rows, distinct_record_ids),
        ValidationCheck("production_duplicate_record_id", duplicate_count == 0, 0, duplicate_count),
        ValidationCheck("production_distinct_run_id", run_ids == [run_id], [run_id], run_ids),
        ValidationCheck("production_source_name", source_names == [source_name], [source_name], source_names),
        ValidationCheck("production_missing_wrapper", missing_wrapper == 0, 0, missing_wrapper),
        ValidationCheck("production_missing_payload", missing_payload == 0, 0, missing_payload),
        ValidationCheck("production_uq_record_id", index_ok, True, index_ok),
    )
    return ValidationReport(run_id=run_id, checks=checks)


def validate_promotion_candidate(
    storage: MongoStorage,
    *,
    run_id: str,
    run_dir: Path,
    project_root: Path,
) -> ValidationReport:
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.is_file():
        raise PromotionError("immutable file manifest is missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    validate_file_manifest(manifest, run_dir=run_dir)
    if manifest.get("run_id") != run_id:
        raise PromotionError("file manifest run_id does not match candidate")
    if manifest.get("status") != "success" or manifest.get("pipeline_status") != "pending":
        raise PromotionError("file manifest status contract failed")
    expected_rows = manifest.get("row_count")
    if not isinstance(expected_rows, int) or expected_rows < 0:
        raise PromotionError("manifest row_count is invalid")
    operational = storage.manifests.find_one({"run_id": run_id})
    if not operational:
        raise PromotionError("operational manifest is missing")
    if (
        operational.get("status") != "success"
        or operational.get("mongodb_validation_status") != "pass"
        or operational.get("pipeline_status") != "pending"
    ):
        raise PromotionError("operational manifest status contract failed")
    run = storage.runs.find_one({"run_id": run_id})
    if not run or run.get("state") != "validating":
        raise PromotionError("candidate run must be in validating state")
    saved_validation = run.get("validation")
    if not isinstance(saved_validation, Mapping) or saved_validation.get("status") != "pass":
        raise PromotionError("saved MongoDB validation is not pass")
    if any(not check.get("passed") for check in saved_validation.get("checks", [])):
        raise PromotionError("saved MongoDB validation contains failed checks")

    artifacts = tuple(
        RawArtifact(
            page=item["page"],
            path=run_dir / item["path"],
            file_size_bytes=item["file_size_bytes"],
            checksum_sha256=item["checksum_sha256"],
        )
        for item in manifest["raw_artifacts"]
    )
    exchange = run_dir / manifest["csv_file"]
    backup_value = Path(manifest["backup_csv_file"])
    backup = backup_value if backup_value.is_absolute() else project_root / backup_value
    if manifest.get("csv_sha256") != sha256_file(exchange):
        raise PromotionError("exchange CSV checksum mismatch")
    if manifest.get("backup_csv_sha256") != sha256_file(backup):
        raise PromotionError("backup CSV checksum mismatch")
    file_report = validate_staged_files(
        run_id=run_id,
        raw_artifacts=artifacts,
        exchange_csv=exchange,
        backup_csv=backup,
        expected_rows=expected_rows,
    )
    staging_report = validate_collection_shape(
        storage.database[storage.staging_name(run_id)],
        run_id=run_id,
        source_name=manifest["source_name"],
        expected_rows=expected_rows,
    )
    with backup.open("r", encoding="utf-8-sig", newline="") as stream:
        source_hashes = {
            row["record_id"]: row["source_record_sha256"]
            for row in csv.DictReader(stream)
        }
    preservation_mismatches = 0
    staging = storage.database[storage.staging_name(run_id)]
    for document in staging.find({}, {"record_id": 1, "source_record_sha256": 1}):
        if source_hashes.get(str(document.get("record_id"))) != document.get(
            "source_record_sha256"
        ):
            preservation_mismatches += 1
    preservation_check = ValidationCheck(
        "staging_source_record_sha256_preservation",
        preservation_mismatches == 0 and len(source_hashes) == expected_rows,
        {"mismatch": 0, "rows": expected_rows},
        {"mismatch": preservation_mismatches, "rows": len(source_hashes)},
    )
    checks = file_report.checks + staging_report.checks + (preservation_check,)
    return ValidationReport(run_id=run_id, checks=checks)


class ProductionPromoter:
    def __init__(self, storage: MongoStorage, *, state_root: Path) -> None:
        self.storage = storage
        self.state_root = state_root
        self.database_name = storage.settings.mongodb_database

    def _rename(self, source: str, target: str) -> None:
        if target in self.storage.database.list_collection_names():
            raise PromotionError(f"rename target already exists: {target}")
        result = self.storage._client.admin.command(
            {
                "renameCollection": f"{self.database_name}.{source}",
                "to": f"{self.database_name}.{target}",
            }
        )
        if result.get("ok") != 1:
            raise PromotionError(f"rename failed: {source} -> {target}")

    @staticmethod
    def _mixed_backup_name(promotion_time: datetime) -> str:
        token = promotion_time.strftime("%Y%m%dT%H%M%S%z")
        return f"legacy_records_backup_legacy_mixed_16runs_{safe_run_id(token)}"

    def _ready_production_run_id(self, *, source_name: str) -> str:
        production = self.storage.database[PRODUCTION_COLLECTION]
        document_count = production.count_documents({})
        if document_count <= 0:
            raise PromotionError("production must contain at least one document")
        run_ids = production.distinct("_ingest.run_id")
        if len(run_ids) != 1 or not isinstance(run_ids[0], str) or not run_ids[0]:
            raise PromotionError("production must contain exactly one valid run_id")
        source_names = production.distinct("_ingest.source_name")
        if source_names != [source_name]:
            raise PromotionError(
                "production must contain exactly the approved source_name"
            )
        latest_ready = self.storage.runs.find_one(
            {"source_name": source_name, "state": "ready"},
            sort=[("ready_at", -1)],
        )
        if not latest_ready or latest_ready.get("run_id") != run_ids[0]:
            raise PromotionError(
                "latest READY run_id does not match production run_id"
            )
        return run_ids[0]

    def _assert_candidate_operational_guard(self, *, run_id: str) -> None:
        operational = self.storage.manifests.find_one({"run_id": run_id})
        if not operational:
            raise PromotionError("candidate operational manifest is missing")
        if operational.get("status") != "success":
            raise PromotionError("candidate Bronze status is not success")
        if operational.get("mongodb_validation_status") != "pass":
            raise PromotionError("candidate MongoDB validation status is not pass")
        if operational.get("pipeline_status") != "pending":
            raise PromotionError("candidate pipeline_status is not pending")
        candidate_run = self.storage.runs.find_one({"run_id": run_id})
        if not candidate_run or candidate_run.get("state") != "validating":
            raise PromotionError("candidate run must be in validating state")
        validation = candidate_run.get("validation")
        if not isinstance(validation, Mapping) or validation.get("status") != "pass":
            raise PromotionError("candidate saved validation is not pass")
        if any(not check.get("passed") for check in validation.get("checks", [])):
            raise PromotionError("candidate saved validation contains failed checks")

    def promote_first_mixed_legacy(
        self,
        *,
        run_id: str,
        source_name: str,
        expected_rows: int,
        candidate_report: ValidationReport,
        expected_legacy_documents: int,
        promotion_time: datetime | None = None,
    ) -> PromotionResult:
        if not candidate_report.passed or candidate_report.run_id != run_id:
            raise PromotionError("candidate validation must pass before promotion")
        staging = self.storage.staging_name(run_id)
        now = promotion_time or datetime.now().astimezone()
        backup = self._mixed_backup_name(now)
        failed = f"legacy_records_failed_{safe_run_id(run_id)}"
        lock = RunLock(self.state_root / "promotion.lock", run_id=run_id)
        production_renamed = False
        staging_promoted = False
        previous_run_ids: tuple[str, ...] = ()

        with lock:
            names = self.storage.database.list_collection_names()
            if PRODUCTION_COLLECTION not in names or staging not in names:
                raise PromotionError("production or staging collection is missing")
            if backup in names or failed in names:
                raise PromotionError("backup or failed target already exists")
            production = self.storage.database[PRODUCTION_COLLECTION]
            legacy_documents = production.count_documents({})
            if legacy_documents != expected_legacy_documents:
                raise PromotionError(
                    "mixed legacy document count changed before promotion: "
                    f"expected {expected_legacy_documents}, got {legacy_documents}"
                )
            previous_run_ids = tuple(sorted(production.distinct("_ingest.run_id")))
            previous_sources = production.distinct("_ingest.source_name")
            if len(previous_run_ids) != 16 or previous_sources:
                raise PromotionError(
                    "first mixed-legacy exception requires exactly 16 run IDs and no source_name"
                )
            # Revalidate staging while the promotion lock is held.
            locked_report = validate_collection_shape(
                self.storage.database[staging],
                run_id=run_id,
                source_name=source_name,
                expected_rows=expected_rows,
            )
            if not locked_report.passed:
                raise PromotionError("locked staging revalidation failed")
            try:
                self._rename(PRODUCTION_COLLECTION, backup)
                production_renamed = True
                self._rename(staging, PRODUCTION_COLLECTION)
                staging_promoted = True
                post = validate_collection_shape(
                    self.storage.database[PRODUCTION_COLLECTION],
                    run_id=run_id,
                    source_name=source_name,
                    expected_rows=expected_rows,
                )
                if not post.passed:
                    raise PromotionError("production post-validation failed")
                self.storage.mark_ready_after_promotion(
                    run_id,
                    ready_at=now.isoformat(),
                    post_validation=post,
                )
            except Exception as exc:
                rollback_error: Exception | None = None
                try:
                    if staging_promoted:
                        self._rename(PRODUCTION_COLLECTION, failed)
                    if production_renamed:
                        self._rename(backup, PRODUCTION_COLLECTION)
                except Exception as rollback_exc:
                    rollback_error = rollback_exc
                try:
                    self.storage.mark_failed(
                        run_id,
                        failed_at=datetime.now().astimezone().isoformat(),
                        error=f"promotion failed: {type(exc).__name__}",
                    )
                except Exception:
                    pass
                if rollback_error is not None:
                    raise PromotionError(
                        f"promotion and rollback both failed: {rollback_error}"
                    ) from exc
                raise PromotionError("promotion failed and previous production restored") from exc

        return PromotionResult(
            run_id=run_id,
            previous_run_ids=previous_run_ids,
            backup_collection=backup,
            production_collection=PRODUCTION_COLLECTION,
            post_validation=post,
            ready_at=now.isoformat(),
        )

    def promote_ready_to_ready(
        self,
        *,
        run_id: str,
        source_name: str,
        expected_rows: int,
        candidate_report: ValidationReport,
        promotion_time: datetime | None = None,
    ) -> PromotionResult:
        """Promote a validated staging run over one matching READY production run."""

        if not candidate_report.passed or candidate_report.run_id != run_id:
            raise PromotionError("candidate validation must pass before promotion")
        if expected_rows <= 0:
            raise PromotionError("candidate expected_rows must be greater than zero")
        self._assert_candidate_operational_guard(run_id=run_id)
        previous_run_id = self._ready_production_run_id(source_name=source_name)
        if previous_run_id == run_id:
            raise PromotionError("candidate run_id already identifies production")

        staging = self.storage.staging_name(run_id)
        backup = f"legacy_records_backup_{safe_run_id(previous_run_id)}"
        failed = f"legacy_records_failed_{safe_run_id(run_id)}"
        now = promotion_time or datetime.now().astimezone()
        lock = RunLock(self.state_root / "promotion.lock", run_id=run_id)
        production_renamed = False
        staging_promoted = False

        with lock:
            # Repeat every mutable guard while holding the promotion lock.
            locked_previous_run_id = self._ready_production_run_id(
                source_name=source_name
            )
            if locked_previous_run_id != previous_run_id:
                raise PromotionError("production READY run changed before lock")
            self._assert_candidate_operational_guard(run_id=run_id)
            names = self.storage.database.list_collection_names()
            if PRODUCTION_COLLECTION not in names or staging not in names:
                raise PromotionError("production or staging collection is missing")
            if backup in names or failed in names:
                raise PromotionError("backup or failed target already exists")
            locked_report = validate_collection_shape(
                self.storage.database[staging],
                run_id=run_id,
                source_name=source_name,
                expected_rows=expected_rows,
            )
            if not locked_report.passed:
                raise PromotionError("locked staging revalidation failed")

            try:
                self._rename(PRODUCTION_COLLECTION, backup)
                production_renamed = True
                self._rename(staging, PRODUCTION_COLLECTION)
                staging_promoted = True
                post = validate_collection_shape(
                    self.storage.database[PRODUCTION_COLLECTION],
                    run_id=run_id,
                    source_name=source_name,
                    expected_rows=expected_rows,
                )
                if not post.passed:
                    raise PromotionError("production post-validation failed")
                self.storage.mark_ready_after_promotion(
                    run_id,
                    ready_at=now.isoformat(),
                    post_validation=post,
                )
            except Exception as exc:
                rollback_error: Exception | None = None
                try:
                    if staging_promoted:
                        self._rename(PRODUCTION_COLLECTION, failed)
                    if production_renamed:
                        self._rename(backup, PRODUCTION_COLLECTION)
                except Exception as rollback_exc:
                    rollback_error = rollback_exc
                try:
                    self.storage.mark_failed(
                        run_id,
                        failed_at=datetime.now().astimezone().isoformat(),
                        error=f"promotion failed: {type(exc).__name__}",
                    )
                except Exception:
                    pass
                if rollback_error is not None:
                    raise PromotionError(
                        f"promotion and rollback both failed: {rollback_error}"
                    ) from exc
                raise PromotionError(
                    "promotion failed and previous READY production restored"
                ) from exc

        return PromotionResult(
            run_id=run_id,
            previous_run_ids=(previous_run_id,),
            backup_collection=backup,
            production_collection=PRODUCTION_COLLECTION,
            post_validation=post,
            ready_at=now.isoformat(),
        )
