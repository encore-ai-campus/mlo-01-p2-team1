from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from legacy_crawler.models import PAYLOAD_FIELDS
from legacy_crawler.validator import validate_staging


def record(record_id: int) -> dict[str, object]:
    return {
        "record_id": record_id,
        "source_row_no": record_id,
        "source_record_sha256": f"hash-{record_id}",
        "release_slot": 1,
        "scheduled_release_at": "",
        "payload": {field: "" for field in PAYLOAD_FIELDS},
    }


class ValidatorUnitTests(unittest.TestCase):
    def test_empty_values_are_not_missing_keys(self) -> None:
        records = [record(1), record(2)]
        collection = MagicMock()
        collection.count_documents.side_effect = [2, 0, 0, 0, 0]
        collection.distinct.side_effect = [[1, 2], [1, 2]]
        collection.aggregate.return_value = []
        collection.find.return_value = [
            {"record_id": 1, "source_record_sha256": "hash-1"},
            {"record_id": 2, "source_record_sha256": "hash-2"},
        ]

        report = validate_staging(
            collection,
            api_records=records,
            run_id="run",
            source_name="biz_legacy_integrated",
        )

        self.assertTrue(report.passed)
        self.assertEqual(report.as_dict()["status"], "pass")

    def test_checksum_is_compared_not_recalculated(self) -> None:
        records = [record(1)]
        collection = MagicMock()
        collection.count_documents.side_effect = [1, 0, 0, 0, 0]
        collection.distinct.side_effect = [[1], [1]]
        collection.aggregate.return_value = []
        collection.find.return_value = [
            {"record_id": 1, "source_record_sha256": "changed"}
        ]

        report = validate_staging(
            collection,
            api_records=records,
            run_id="run",
            source_name="biz_legacy_integrated",
        )

        self.assertFalse(report.passed)
        checksum = next(
            check for check in report.checks if check.name == "source_record_sha256_mismatch"
        )
        self.assertEqual(checksum.actual, 1)


if __name__ == "__main__":
    unittest.main()
