"""Read-only audit for the multi-run page-append production contract."""

from __future__ import annotations

import json

from .config import Settings
from .continuation import ContinuationStore
from .mongo_storage import MongoStorage


def _duplicate_groups(collection, field: str) -> int:
    rows = list(collection.aggregate([
        {"$group": {"_id": f"${field}", "count": {"$sum": 1}}},
        {"$match": {"count": {"$gt": 1}}},
        {"$count": "groups"},
    ]))
    return rows[0]["groups"] if rows else 0


def main() -> int:
    settings = Settings.from_env()
    storage = MongoStorage(settings)
    try:
        state = ContinuationStore(
            settings.state_root / "records_continuation.json"
        ).load()
        production = storage.production
        run_ids = production.distinct("_ingest.run_id")
        count = production.count_documents({})
        distinct_record_ids = len(production.distinct("record_id"))
        distinct_source_rows = len(production.distinct("source_row_no"))
        ready_runs = storage.runs.count_documents(
            {"run_id": {"$in": run_ids}, "state": "ready"}
        )
        passing_manifests = storage.manifests.count_documents(
            {
                "run_id": {"$in": run_ids},
                "status": "success",
                "mongodb_validation_status": "pass",
                "pipeline_status": "pending",
            }
        )
        indexes = production.index_information()
        unique = indexes.get("uq_record_id", {})
        unique_ok = bool(
            unique.get("unique") is True
            and unique.get("key") == [("record_id", 1)]
        )
        backups = sorted(
            name
            for name in storage.database.list_collection_names()
            if name.startswith("legacy_records_backup_pre_page_append_")
        )
        checks = {
            "row_count_matches_released_rows": count == state.released_rows,
            "record_id_unique": distinct_record_ids == count
            and _duplicate_groups(production, "record_id") == 0,
            "source_row_no_unique": distinct_source_rows == count
            and _duplicate_groups(production, "source_row_no") == 0,
            "all_page_runs_ready": ready_runs == len(run_ids),
            "all_page_manifests_pass_pending": passing_manifests == len(run_ids),
            "source_name_contract": production.distinct("_ingest.source_name")
            == [settings.source_name],
            "continuation_is_terminal_checkpoint": not state.has_more
            and state.cursor == state.checkpoint,
            "uq_record_id": unique_ok,
            "backup_preserved": bool(backups),
        }
        result = {
            "status": "pass" if all(checks.values()) else "fail",
            "checks": checks,
            "production_documents": count,
            "page_run_count": len(run_ids),
            "ready_page_runs": ready_runs,
            "passing_page_manifests": passing_manifests,
            "released_rows": state.released_rows,
            "continuation_cursor_present": bool(state.cursor),
            "checkpoint_present": bool(state.checkpoint),
            "backup_collections": [
                {
                    "name": name,
                    "documents": storage.database[name].count_documents({}),
                }
                for name in backups
            ],
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["status"] == "pass" else 1
    finally:
        storage.close()


if __name__ == "__main__":
    raise SystemExit(main())
