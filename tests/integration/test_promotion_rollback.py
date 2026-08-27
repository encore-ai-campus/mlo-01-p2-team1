from __future__ import annotations

import os
import unittest

from pymongo import MongoClient

from legacy_crawler.config import Settings


@unittest.skipUnless(
    os.environ.get("RUN_PROMOTION_ROLLBACK_PROBE") == "1",
    "set RUN_PROMOTION_ROLLBACK_PROBE=1 for the isolated rename/rollback probe",
)
class PromotionRollbackIntegrationTests(unittest.TestCase):
    def test_isolated_failed_promotion_restores_original_collection(self) -> None:
        settings = Settings.from_env()
        client = MongoClient(settings.mongodb_uri, serverSelectionTimeoutMS=5000)
        database = client[settings.mongodb_database]
        names = {
            "production": "codex_promotion_rollback_20260827_01_production",
            "staging": "codex_promotion_rollback_20260827_01_staging",
            "backup": "codex_promotion_rollback_20260827_01_backup",
            "failed": "codex_promotion_rollback_20260827_01_failed",
        }
        try:
            existing = set(database.list_collection_names())
            collisions = sorted(existing.intersection(names.values()))
            self.assertEqual(collisions, [], f"probe targets already exist: {collisions}")

            original = database[names["production"]]
            original.insert_many(
                [
                    {"record_id": 1, "_ingest": {"run_id": "old-a"}},
                    {"record_id": 2, "_ingest": {"run_id": "old-b"}},
                ]
            )
            original.create_index("_ingest.run_id", name="ix_old_run_id")
            staging = database[names["staging"]]
            staging.insert_many(
                [
                    {
                        "record_id": value,
                        "_ingest": {
                            "run_id": "new-ready-run",
                            "source_name": "biz_legacy_integrated",
                        },
                    }
                    for value in (10, 11, 12)
                ]
            )
            staging.create_index("record_id", name="uq_record_id", unique=True)

            def rename(source: str, target: str) -> None:
                command = {
                    "renameCollection": f"{settings.mongodb_database}.{source}",
                    "to": f"{settings.mongodb_database}.{target}",
                }
                self.assertNotIn("dropTarget", command)
                result = client.admin.command(command)
                self.assertEqual(result.get("ok"), 1)

            rename(names["production"], names["backup"])
            rename(names["staging"], names["production"])
            self.assertEqual(database[names["production"]].count_documents({}), 3)
            self.assertEqual(
                database[names["production"]].distinct("_ingest.run_id"),
                ["new-ready-run"],
            )
            self.assertTrue(
                database[names["production"]].index_information()["uq_record_id"][
                    "unique"
                ]
            )

            # Deliberately exercise the approved post-validation failure rollback.
            rename(names["production"], names["failed"])
            rename(names["backup"], names["production"])
            restored = database[names["production"]]
            self.assertEqual(restored.count_documents({}), 2)
            self.assertEqual(
                sorted(restored.distinct("_ingest.run_id")), ["old-a", "old-b"]
            )
            self.assertIn("ix_old_run_id", restored.index_information())
            self.assertEqual(database[names["failed"]].count_documents({}), 3)
            self.assertIn(
                "uq_record_id", database[names["failed"]].index_information()
            )
        finally:
            client.close()


if __name__ == "__main__":
    unittest.main()
