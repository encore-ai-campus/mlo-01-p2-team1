"""Read-only production contract audit for operational handoff."""

from __future__ import annotations

import argparse
import json

from .config import PRODUCTION_COLLECTION, Settings
from .mongo_storage import MongoStorage


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit one promoted production run")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--backup-collection", required=True)
    args = parser.parse_args()
    settings = Settings.from_env()
    storage = MongoStorage(settings)
    try:
        production = storage.database[PRODUCTION_COLLECTION]
        backup = storage.database[args.backup_collection]
        run = storage.runs.find_one(
            {"run_id": args.run_id},
            {"_id": 0, "run_id": 1, "state": 1, "ready_at": 1, "validation": 1},
        )
        manifest = storage.manifests.find_one(
            {"run_id": args.run_id},
            {
                "_id": 0,
                "run_id": 1,
                "status": 1,
                "mongodb_validation_status": 1,
                "pipeline_status": 1,
                "row_count": 1,
                "page_count": 1,
            },
        )
        all_names = sorted(storage.database.list_collection_names())
        relevant = [
            name
            for name in all_names
            if name.startswith(
                ("legacy_records_staging_", "legacy_records_backup_", "legacy_records_failed_", "codex_")
            )
        ]
        result = {
            "production": {
                "documents": production.count_documents({}),
                "distinct_record_id": len(production.distinct("record_id")),
                "run_ids": production.distinct("_ingest.run_id"),
                "source_names": production.distinct("_ingest.source_name"),
                "indexes": production.index_information(),
            },
            "backup": {
                "name": args.backup_collection,
                "documents": backup.count_documents({}),
                "run_ids": sorted(backup.distinct("_ingest.run_id")),
                "source_names": backup.distinct("_ingest.source_name"),
                "indexes": backup.index_information(),
            },
            "crawler_run": run,
            "crawl_manifest": manifest,
            "relevant_collections": relevant,
            "promotion_lock_exists": (settings.state_root / "promotion.lock").exists(),
        }
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0
    finally:
        storage.close()


if __name__ == "__main__":
    raise SystemExit(main())
