from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from legacy_crawler.client import CollectedPage, HttpBody
from legacy_crawler.config import Settings
from legacy_crawler.main import run_once
from legacy_crawler.models import PAYLOAD_FIELDS, ValidationCheck, ValidationReport


def source_record(record_id: int) -> dict[str, object]:
    return {
        "record_id": record_id,
        "source_row_no": record_id,
        "source_record_sha256": f"hash-{record_id}",
        "release_slot": 1,
        "scheduled_release_at": "",
        "payload": {field: "" for field in PAYLOAD_FIELDS},
    }


class FakeClient:
    def __init__(self) -> None:
        self.raw = b'{\n "items": [], "count": 0, "has_more": false, "next_cursor": null\n}\n'

    def fetch_api_key(self) -> str:
        return "test-api-secret"

    def fetch_metadata(self, *, api_key: str):
        return {
            "dataset_id": "dataset",
            "dataset_name": "biz_legacy_integrated",
            "server_time": "2026-08-27T10:00:10+09:00",
            "next_refresh_at": "2026-08-27T10:03:00+09:00",
        }

    def resolve_dataset_id(self, metadata, *, source_name: str) -> str:
        return "dataset"

    def iter_record_pages(self, *, dataset_id: str, api_key: str):
        record = source_record(1)
        parsed = {
            "items": [record],
            "count": 1,
            "has_more": False,
            "next_cursor": None,
        }
        raw = json.dumps(parsed, ensure_ascii=False, indent=2).encode()
        self.raw = raw
        yield CollectedPage(
            number=1,
            response=HttpBody(
                status=200,
                headers={"content-type": "application/json"},
                body=raw,
            ),
            parsed=parsed,
            requested_cursor=None,
        )


class FakeStorage:
    def __init__(self) -> None:
        self.database = {"legacy_records_staging_test_run": object()}
        self.operational_manifest = None
        self.state = None
        self.closed = False

    def ping(self): pass
    def create_run(self, **kwargs): self.state = "loading"
    def set_expected_rows(self, run_id, expected_rows): self.expected_rows = expected_rows
    def insert_full_snapshot(self, run_id, records, **kwargs): return len(records)
    def set_inserted_rows(self, run_id, inserted_rows): self.inserted_rows = inserted_rows
    def transition_to_validating(self, run_id, **kwargs): self.state = "validating"
    def staging_name(self, run_id): return "legacy_records_staging_test_run"
    def record_validation(self, report): self.report = report
    def store_operational_manifest(self, manifest, **kwargs): self.operational_manifest = dict(manifest) | kwargs
    def mark_failed(self, *args, **kwargs): self.state = "failed"
    def close(self): self.closed = True


class OrchestrationContractTests(unittest.TestCase):
    def test_one_run_id_connects_raw_csv_manifest_and_staging(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            root = Path(temp)
            values = {
                "DATA_ROOT": str(root / "data"),
                "BACKUP_ROOT": str(root / "backup"),
                "LOG_ROOT": str(root / "logs"),
                "STATE_ROOT": str(root / "state"),
            }
            settings = Settings.from_env(values)
            client = FakeClient()
            storage = FakeStorage()
            report = ValidationReport(
                run_id="test-run",
                checks=(ValidationCheck("mongo", True, True, True),),
            )
            with patch("legacy_crawler.main.validate_staging", return_value=report):
                result = run_once(
                    settings,
                    client=client,
                    storage=storage,
                    run_id="test-run",
                )

            manifest_path = result.data_path / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(result.run_id, "test-run")
            self.assertEqual(storage.state, "validating")
            self.assertTrue(storage.closed)
            self.assertEqual(
                (result.data_path / "raw" / "page_0001.json").read_bytes(),
                client.raw,
            )
            self.assertEqual(manifest["run_id"], "test-run")
            self.assertEqual(manifest["pipeline_status"], "pending")
            self.assertEqual(storage.operational_manifest["run_id"], "test-run")
            self.assertEqual(
                storage.operational_manifest["mongodb_validation_status"], "pass"
            )
            log_text = next((root / "logs" / "crawler").glob("*.log")).read_text(
                encoding="utf-8"
            )
            self.assertNotIn("test-api-secret", log_text)
            self.assertFalse((root / "state" / "crawler.lock").exists())


if __name__ == "__main__":
    unittest.main()
