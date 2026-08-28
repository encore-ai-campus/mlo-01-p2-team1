from __future__ import annotations

from copy import deepcopy
import unittest
from unittest.mock import MagicMock

from legacy_crawler.config import Settings
from legacy_crawler.models import PAYLOAD_FIELDS
from legacy_crawler.mongo_storage import (
    MongoStorage,
    ProductionProtectionError,
    prepare_staging_document,
    safe_run_id,
    staging_collection_name,
)


def record() -> dict[str, object]:
    return {
        "record_id": 1,
        "source_row_no": 1,
        "source_record_sha256": "source-hash",
        "release_slot": 1,
        "scheduled_release_at": " 2026/08/27 01:02:03 ",
        "payload": {field: f" {field} " for field in PAYLOAD_FIELDS},
    }


class MongoStorageUnitTests(unittest.TestCase):
    def test_safe_run_id_changes_only_collection_token(self) -> None:
        original = "20260827T112500+0900-abcd1234"
        safe = safe_run_id(original)
        self.assertEqual(safe, "20260827T112500_0900_abcd1234")
        self.assertEqual(
            staging_collection_name(original, "legacy_records_staging_"),
            "legacy_records_staging_20260827T112500_0900_abcd1234",
        )

    def test_prepare_document_preserves_source_and_adds_only_ingest(self) -> None:
        source = record()
        before = deepcopy(source)
        document = prepare_staging_document(
            source,
            run_id="20260827T112500+0900-abcd1234",
            source_name="biz_legacy_integrated",
            collected_at="2026-08-27T11:25:10+09:00",
        )
        self.assertEqual(source, before)
        self.assertEqual(document["payload"], source["payload"])
        self.assertIsNot(document["payload"], source["payload"])
        self.assertEqual(
            set(document),
            {
                "record_id",
                "source_row_no",
                "source_record_sha256",
                "release_slot",
                "scheduled_release_at",
                "payload",
                "_ingest",
            },
        )
        self.assertNotIn("pipeline_status", document)
        self.assertNotIn("standardization_status", document)
        self.assertEqual(
            document["_ingest"]["run_id"], "20260827T112500+0900-abcd1234"
        )

    def test_ready_transition_is_unconditionally_blocked(self) -> None:
        storage = MongoStorage(
            Settings.from_env({}), client=MagicMock(), database=MagicMock()
        )
        with self.assertRaises(ProductionProtectionError):
            storage.mark_ready("run")

    def test_production_collection_is_never_a_staging_target(self) -> None:
        storage = MongoStorage(
            Settings.from_env({}), client=MagicMock(), database=MagicMock()
        )
        with self.assertRaises(ProductionProtectionError):
            storage._assert_staging_target("legacy_records")


if __name__ == "__main__":
    unittest.main()
