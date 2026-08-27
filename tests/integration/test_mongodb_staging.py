from __future__ import annotations

from datetime import datetime
import os
import unittest
import uuid

from legacy_crawler.config import Settings
from legacy_crawler.models import PAYLOAD_FIELDS
from legacy_crawler.mongo_storage import MongoStorage, ProductionProtectionError
from legacy_crawler.validator import validate_staging


def record(record_id: int) -> dict[str, object]:
    return {
        "record_id": record_id,
        "source_row_no": record_id,
        "source_record_sha256": f"source-{record_id}",
        "release_slot": 1,
        "scheduled_release_at": "",
        "payload": {field: "" for field in PAYLOAD_FIELDS},
    }


@unittest.skipUnless(
    os.environ.get("RUN_MONGODB_INTEGRATION") == "1",
    "set RUN_MONGODB_INTEGRATION=1 for the approved staging-only test",
)
class MongoStagingIntegrationTests(unittest.TestCase):
    def test_staging_validation_and_history_without_ready(self) -> None:
        run_id = os.environ.get("MONGODB_TEST_RUN_ID") or f"codex-stage4-{uuid.uuid4().hex}"
        source_name = "biz_legacy_integrated"
        now = datetime.now().astimezone().isoformat()
        records = [record(1), record(2)]
        storage = MongoStorage(Settings.from_env())
        try:
            storage.ping()
            storage.create_run(
                run_id=run_id,
                source_name=source_name,
                started_at=now,
                expected_rows=len(records),
            )
            inserted = storage.insert_full_snapshot(
                run_id,
                records,
                source_name=source_name,
                collected_at=now,
            )
            storage.set_inserted_rows(run_id, inserted)
            storage.transition_to_validating(run_id, started_at=now)
            staging = storage.database[storage.staging_name(run_id)]
            report = validate_staging(
                staging,
                api_records=records,
                run_id=run_id,
                source_name=source_name,
            )
            storage.record_validation(report)
            storage.store_operational_manifest(
                {"run_id": run_id, "pipeline_status": "pending", "status": "success"},
                mongodb_validation_status="pass" if report.passed else "fail",
            )

            self.assertTrue(report.passed)
            self.assertEqual(staging.count_documents({}), 2)
            self.assertEqual(staging.distinct("_ingest.run_id"), [run_id])
            self.assertEqual(
                storage.runs.find_one({"run_id": run_id})["state"], "validating"
            )
            self.assertEqual(
                storage.manifests.find_one({"run_id": run_id})["pipeline_status"],
                "pending",
            )
            with self.assertRaises(ProductionProtectionError):
                storage.mark_ready(run_id)
        finally:
            storage.close()


if __name__ == "__main__":
    unittest.main()
