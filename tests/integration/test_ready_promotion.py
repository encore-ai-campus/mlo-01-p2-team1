from __future__ import annotations

from dataclasses import replace
from datetime import datetime
import os
from pathlib import Path
import tempfile
import unittest

from pymongo import MongoClient

from legacy_crawler.config import Settings
from legacy_crawler.models import PAYLOAD_FIELDS, ValidationCheck, ValidationReport
from legacy_crawler.mongo_storage import MongoStorage
from legacy_crawler.promotion import ProductionPromoter, PromotionError


PROBE_DATABASE = "legacy_bronze_ready_promotion_probe_20260827_01"
SOURCE_NAME = "biz_legacy_integrated"
OLD_RUN_ID = "ready-run-a"
NEW_RUN_ID = "candidate-run-b"


def stored_record(record_id: int, *, run_id: str) -> dict[str, object]:
    return {
        "record_id": record_id,
        "source_row_no": record_id,
        "source_record_sha256": f"source-{record_id}",
        "release_slot": 1,
        "scheduled_release_at": "",
        "payload": {field: "" for field in PAYLOAD_FIELDS},
        "_ingest": {
            "run_id": run_id,
            "source_name": SOURCE_NAME,
            "collected_at": "2026-08-27T15:00:00+09:00",
        },
    }


@unittest.skipUnless(
    os.environ.get("RUN_READY_PROMOTION_INTEGRATION") == "1",
    "set RUN_READY_PROMOTION_INTEGRATION=1 for the isolated READY promotion test",
)
class ReadyPromotionIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        base = Settings.from_env()
        self.settings = replace(base, mongodb_database=PROBE_DATABASE)
        self.client = MongoClient(base.mongodb_uri, serverSelectionTimeoutMS=5000)
        self.client.drop_database(PROBE_DATABASE)
        database = self.client[PROBE_DATABASE]
        self.storage = MongoStorage(
            self.settings, client=self.client, database=database
        )
        self.storage.ping()
        self.temp = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self.temp.cleanup()
        self.client.drop_database(PROBE_DATABASE)
        self.assertNotIn(PROBE_DATABASE, self.client.list_database_names())
        self.client.close()

    def _seed(self) -> ValidationReport:
        production = self.storage.database["legacy_records"]
        production.insert_many(
            [stored_record(value, run_id=OLD_RUN_ID) for value in (1, 2)]
        )
        production.create_index("record_id", name="uq_record_id", unique=True)

        staging_name = self.storage.staging_name(NEW_RUN_ID)
        staging = self.storage.database[staging_name]
        staging.insert_many(
            [stored_record(value, run_id=NEW_RUN_ID) for value in (10, 11, 12)]
        )
        staging.create_index("record_id", name="uq_record_id", unique=True)

        self.storage.ensure_history_indexes()
        self.storage.runs.insert_many(
            [
                {
                    "run_id": OLD_RUN_ID,
                    "source_name": SOURCE_NAME,
                    "state": "ready",
                    "ready_at": "2026-08-27T14:00:00+09:00",
                },
                {
                    "run_id": NEW_RUN_ID,
                    "source_name": SOURCE_NAME,
                    "state": "validating",
                    "validation": {
                        "status": "pass",
                        "checks": [{"name": "seed", "passed": True}],
                    },
                },
            ]
        )
        self.storage.manifests.insert_one(
            {
                "run_id": NEW_RUN_ID,
                "status": "success",
                "mongodb_validation_status": "pass",
                "pipeline_status": "pending",
            }
        )
        return ValidationReport(
            run_id=NEW_RUN_ID,
            checks=(ValidationCheck("candidate", True, True, True),),
        )

    def test_ready_to_ready_success_preserves_old_snapshot_as_backup(self) -> None:
        report = self._seed()
        promoter = ProductionPromoter(
            self.storage, state_root=Path(self.temp.name)
        )
        result = promoter.promote_ready_to_ready(
            run_id=NEW_RUN_ID,
            source_name=SOURCE_NAME,
            expected_rows=3,
            candidate_report=report,
            promotion_time=datetime.fromisoformat("2026-08-27T15:05:00+09:00"),
        )

        production = self.storage.database["legacy_records"]
        backup = self.storage.database["legacy_records_backup_ready_run_a"]
        self.assertEqual(production.count_documents({}), 3)
        self.assertEqual(production.distinct("_ingest.run_id"), [NEW_RUN_ID])
        self.assertEqual(backup.count_documents({}), 2)
        self.assertEqual(backup.distinct("_ingest.run_id"), [OLD_RUN_ID])
        self.assertIn("uq_record_id", production.index_information())
        self.assertIn("uq_record_id", backup.index_information())
        self.assertEqual(result.previous_run_ids, (OLD_RUN_ID,))
        self.assertEqual(
            self.storage.runs.find_one({"run_id": NEW_RUN_ID})["state"],
            "ready",
        )
        self.assertFalse((Path(self.temp.name) / "promotion.lock").exists())

    def test_post_validation_failure_restores_ready_production(self) -> None:
        report = self._seed()
        staging_name = self.storage.staging_name(NEW_RUN_ID)

        class FailingPostValidationPromoter(ProductionPromoter):
            def _rename(self, source: str, target: str) -> None:
                super()._rename(source, target)
                if source == staging_name and target == "legacy_records":
                    self.storage.database[target].update_one(
                        {"record_id": 10}, {"$unset": {"payload.mgr_nm": ""}}
                    )

        promoter = FailingPostValidationPromoter(
            self.storage, state_root=Path(self.temp.name)
        )
        with self.assertRaisesRegex(PromotionError, "previous READY production restored"):
            promoter.promote_ready_to_ready(
                run_id=NEW_RUN_ID,
                source_name=SOURCE_NAME,
                expected_rows=3,
                candidate_report=report,
                promotion_time=datetime.fromisoformat(
                    "2026-08-27T15:05:00+09:00"
                ),
            )

        production = self.storage.database["legacy_records"]
        failed = self.storage.database["legacy_records_failed_candidate_run_b"]
        self.assertEqual(production.count_documents({}), 2)
        self.assertEqual(production.distinct("_ingest.run_id"), [OLD_RUN_ID])
        self.assertIn("uq_record_id", production.index_information())
        self.assertEqual(failed.count_documents({}), 3)
        self.assertIn("uq_record_id", failed.index_information())
        self.assertNotIn(
            "legacy_records_backup_ready_run_a",
            self.storage.database.list_collection_names(),
        )
        self.assertEqual(
            self.storage.runs.find_one({"run_id": NEW_RUN_ID})["state"],
            "failed",
        )
        self.assertFalse((Path(self.temp.name) / "promotion.lock").exists())


if __name__ == "__main__":
    unittest.main()
