from __future__ import annotations

from dataclasses import replace
from datetime import datetime
import json
import os
from pathlib import Path
import tempfile
import unittest
import uuid

from legacy_crawler.config import Settings
from legacy_crawler.client import CollectedPage, HttpBody
from legacy_crawler.append_pipeline import run_page_append_cycle
from legacy_crawler.models import PAYLOAD_FIELDS
from legacy_crawler.mongo_storage import MongoStorage, SourceContractError
from legacy_crawler.validator import (
    validate_accumulated_production,
    validate_appended_page,
)


def record(value: int) -> dict[str, object]:
    return {
        "record_id": value,
        "source_row_no": value,
        "source_record_sha256": f"source-{value}",
        "release_slot": 1,
        "scheduled_release_at": "",
        "payload": {field: "" for field in PAYLOAD_FIELDS},
    }


class FakeClient:
    def __init__(self, pages: list[dict[str, object]]) -> None:
        self.pages = pages
        self.initial_cursors: list[str | None] = []

    def fetch_api_key(self) -> str:
        return "fake-secret"

    def fetch_metadata(self, *, api_key: str):
        return {
            "dataset_id": "dataset",
            "dataset_name": "biz_legacy_integrated",
            "server_time": "2026-08-28T10:00:10+09:00",
            "next_refresh_at": "2026-08-28T10:03:00+09:00",
        }

    def resolve_dataset_id(self, metadata, *, source_name: str) -> str:
        return "dataset"

    def iter_record_pages(self, *, initial_cursor=None, **kwargs):
        self.initial_cursors.append(initial_cursor)
        for number, parsed in enumerate(self.pages, start=1):
            raw = json.dumps(parsed, ensure_ascii=False).encode()
            yield CollectedPage(
                number=number,
                response=HttpBody(200, {"content-type": "application/json"}, raw),
                parsed=parsed,
                requested_cursor=initial_cursor if number == 1 else None,
            )


@unittest.skipUnless(
    os.environ.get("RUN_MONGODB_INTEGRATION") == "1",
    "set RUN_MONGODB_INTEGRATION=1 for the isolated MongoDB test",
)
class MongoPageAppendIntegrationTests(unittest.TestCase):
    def test_backup_append_multi_run_and_unique_guard(self) -> None:
        database_name = f"legacy_bronze_page_append_test_{uuid.uuid4().hex}"
        settings = replace(Settings.from_env(), mongodb_database=database_name)
        storage = MongoStorage(settings)
        now = datetime.now().astimezone().isoformat()
        try:
            storage.database["legacy_records"].insert_one({"legacy": True})
            backup = storage.initialize_page_append_production(
                timestamp="20260828T100000+0900"
            )
            self.assertEqual(storage.database[backup].count_documents({}), 1)
            self.assertIn("uq_record_id", storage.production.index_information())

            for run_id, rows in (
                ("page-run-a", [record(1), record(2)]),
                ("page-run-b", [record(3), record(4)]),
            ):
                storage.create_run(
                    run_id=run_id,
                    source_name="biz_legacy_integrated",
                    started_at=now,
                    expected_rows=len(rows),
                    append_mode=True,
                )
                inserted = storage.append_page(
                    run_id,
                    rows,
                    source_name="biz_legacy_integrated",
                    collected_at=now,
                )
                storage.set_inserted_rows(run_id, inserted)
                storage.transition_to_validating(run_id, started_at=now)
                report = validate_appended_page(
                    storage.production,
                    api_records=rows,
                    run_id=run_id,
                    source_name="biz_legacy_integrated",
                )
                storage.record_validation(report)
                storage.mark_ready_after_page_append(
                    run_id, ready_at=now, validation=report
                )

            final = validate_accumulated_production(
                storage.production,
                expected_rows=4,
                source_name="biz_legacy_integrated",
                run_id="page-run-b",
            )
            self.assertTrue(final.passed)
            self.assertEqual(
                set(storage.production.distinct("_ingest.run_id")),
                {"page-run-a", "page-run-b"},
            )
            with self.assertRaises(SourceContractError):
                storage.append_page(
                    "page-run-c",
                    [record(4)],
                    source_name="biz_legacy_integrated",
                    collected_at=now,
                )
        finally:
            storage._client.drop_database(database_name)
            storage.close()

    def test_orchestration_initializes_then_continues_from_saved_cursor(self) -> None:
        database_name = f"legacy_bronze_page_append_test_{uuid.uuid4().hex}"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            settings = replace(
                Settings.from_env(),
                mongodb_database=database_name,
                data_root=root / "data",
                backup_root=root / "backup",
                log_root=root / "logs",
                state_root=root / "state",
            )
            storage = MongoStorage(settings)
            try:
                storage.database["legacy_records"].insert_one({"legacy": True})
            finally:
                storage.close()
            first_client = FakeClient([
                {
                    "items": [record(1), record(2)],
                    "count": 2,
                    "has_more": True,
                    "next_cursor": "cursor-2",
                    "checkpoint": "checkpoint-3",
                    "dataset_id": "dataset",
                    "released_rows": 3,
                    "server_time": "2026-08-28T10:00:11+09:00",
                    "next_refresh_at": "2026-08-28T10:03:00+09:00",
                },
                {
                    "items": [record(3)],
                    "count": 1,
                    "has_more": False,
                    "next_cursor": "checkpoint-3",
                    "checkpoint": "checkpoint-3",
                    "dataset_id": "dataset",
                    "released_rows": 3,
                    "server_time": "2026-08-28T10:00:12+09:00",
                    "next_refresh_at": "2026-08-28T10:03:00+09:00",
                },
            ])
            first = run_page_append_cycle(
                settings, initialize=True, client=first_client
            )
            self.assertEqual(first.appended_rows, 3)
            self.assertEqual(first.page_count, 2)
            self.assertEqual(first_client.initial_cursors, [None])

            second_client = FakeClient([{
                "items": [record(4), record(5)],
                "count": 2,
                "has_more": False,
                "next_cursor": "checkpoint-5",
                "checkpoint": "checkpoint-5",
                "dataset_id": "dataset",
                "released_rows": 5,
                "server_time": "2026-08-28T10:03:11+09:00",
                "next_refresh_at": "2026-08-28T10:06:00+09:00",
            }])
            second = run_page_append_cycle(
                settings, initialize=False, client=second_client
            )
            self.assertEqual(second.appended_rows, 2)
            self.assertEqual(second_client.initial_cursors, ["checkpoint-3"])

            verify = MongoStorage(settings)
            try:
                self.assertEqual(verify.production.count_documents({}), 5)
                self.assertEqual(len(verify.production.distinct("_ingest.run_id")), 3)
                self.assertEqual(verify.manifests.count_documents({}), 3)
                self.assertEqual(
                    set(verify.manifests.distinct("pipeline_status")), {"pending"}
                )
            finally:
                verify._client.drop_database(database_name)
                verify.close()


if __name__ == "__main__":
    unittest.main()
