"""One-shot exact-name cleanup for approved test/probe collections."""

from __future__ import annotations

import json

from .config import PRODUCTION_COLLECTION, Settings
from .mongo_storage import MongoStorage


KNOWN_TEST_COLLECTIONS = (
    "codex_probe_20260827_01_drop_target",
    "codex_probe_20260827_01_rename_target",
    "codex_probe_20260827_02_control",
    "codex_probe_20260827_02_target",
    "codex_promotion_rollback_20260827_01_failed",
    "codex_promotion_rollback_20260827_01_production",
    "legacy_records_staging_codex_stage4_integration_20260827_01",
)


def main() -> int:
    if PRODUCTION_COLLECTION in KNOWN_TEST_COLLECTIONS:
        raise RuntimeError("production must never be a cleanup target")
    settings = Settings.from_env()
    storage = MongoStorage(settings)
    removed: list[str] = []
    try:
        existing = set(storage.database.list_collection_names())
        targets = [name for name in KNOWN_TEST_COLLECTIONS if name in existing]
        print(json.dumps({"verified_cleanup_targets": targets}, indent=2))
        for name in targets:
            storage.database[name].drop()
            removed.append(name)
        remaining = sorted(
            set(storage.database.list_collection_names()).intersection(
                KNOWN_TEST_COLLECTIONS
            )
        )
        print(json.dumps({"removed": removed, "remaining_known": remaining}, indent=2))
        return 0 if not remaining else 2
    finally:
        storage.close()


if __name__ == "__main__":
    raise SystemExit(main())
