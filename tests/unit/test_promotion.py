from __future__ import annotations

from datetime import datetime
import unittest
from unittest.mock import MagicMock

from legacy_crawler.config import Settings
from legacy_crawler.models import ValidationCheck, ValidationReport
from legacy_crawler.mongo_storage import MongoStorage
from legacy_crawler.promotion import ProductionPromoter, PromotionError


class PromotionUnitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = MagicMock()
        self.database = MagicMock()
        self.storage = MongoStorage(
            Settings.from_env({}), client=self.client, database=self.database
        )
        self.promoter = ProductionPromoter(self.storage, state_root=MagicMock())

    def test_initial_mixed_backup_name_is_explicit_and_collection_safe(self) -> None:
        promotion_time = datetime.fromisoformat("2026-08-27T14:05:00+09:00")
        self.assertEqual(
            self.promoter._mixed_backup_name(promotion_time),
            "legacy_records_backup_legacy_mixed_16runs_20260827T140500_0900",
        )

    def test_rename_command_never_sends_drop_target(self) -> None:
        self.database.list_collection_names.return_value = ["source"]
        self.client.admin.command.return_value = {"ok": 1}

        self.promoter._rename("source", "target")

        command = self.client.admin.command.call_args.args[0]
        self.assertEqual(
            command,
            {
                "renameCollection": "legacy_bronze.source",
                "to": "legacy_bronze.target",
            },
        )
        self.assertNotIn("dropTarget", command)

    def test_rename_refuses_to_overwrite_existing_target(self) -> None:
        self.database.list_collection_names.return_value = ["source", "target"]
        with self.assertRaisesRegex(RuntimeError, "target already exists"):
            self.promoter._rename("source", "target")
        self.client.admin.command.assert_not_called()

    def _ready_guard_promoter(
        self,
        *,
        document_count: int = 10,
        run_ids: list[str] | None = None,
        source_names: list[str] | None = None,
        latest_ready_run_id: str | None = "run-a",
    ) -> ProductionPromoter:
        database = MagicMock()
        production = MagicMock()
        runs = MagicMock()
        production.count_documents.return_value = document_count

        def distinct(field: str) -> list[str]:
            if field == "_ingest.run_id":
                return ["run-a"] if run_ids is None else run_ids
            if field == "_ingest.source_name":
                return (
                    ["biz_legacy_integrated"]
                    if source_names is None
                    else source_names
                )
            raise AssertionError(f"unexpected distinct field: {field}")

        production.distinct.side_effect = distinct
        runs.find_one.return_value = (
            None
            if latest_ready_run_id is None
            else {"run_id": latest_ready_run_id, "state": "ready"}
        )

        def collection(name: str) -> MagicMock:
            if name == "legacy_records":
                return production
            if name == "crawler_runs":
                return runs
            return MagicMock()

        database.__getitem__.side_effect = collection
        storage = MongoStorage(
            Settings.from_env({}), client=MagicMock(), database=database
        )
        return ProductionPromoter(storage, state_root=MagicMock())

    def test_ready_production_guard_accepts_one_matching_ready_run(self) -> None:
        promoter = self._ready_guard_promoter()
        self.assertEqual(
            promoter._ready_production_run_id(
                source_name="biz_legacy_integrated"
            ),
            "run-a",
        )

    def test_ready_production_guard_rejects_unsafe_shapes(self) -> None:
        cases = (
            ({"document_count": 0}, "at least one document"),
            ({"run_ids": ["run-a", "run-b"]}, "exactly one valid run_id"),
            ({"source_names": ["wrong"]}, "approved source_name"),
            ({"latest_ready_run_id": "other"}, "does not match"),
            ({"latest_ready_run_id": None}, "does not match"),
        )
        for kwargs, message in cases:
            with self.subTest(kwargs=kwargs):
                promoter = self._ready_guard_promoter(**kwargs)
                with self.assertRaisesRegex(PromotionError, message):
                    promoter._ready_production_run_id(
                        source_name="biz_legacy_integrated"
                    )

    def test_candidate_manifest_guard_blocks_before_any_rename(self) -> None:
        database = MagicMock()
        manifests = MagicMock()
        manifests.find_one.return_value = {
            "run_id": "run-b",
            "status": "success",
            "mongodb_validation_status": "fail",
            "pipeline_status": "pending",
        }
        database.__getitem__.side_effect = lambda name: (
            manifests if name == "crawl_manifests" else MagicMock()
        )
        storage = MongoStorage(
            Settings.from_env({}), client=MagicMock(), database=database
        )
        promoter = ProductionPromoter(storage, state_root=MagicMock())
        promoter._rename = MagicMock()
        report = ValidationReport(
            run_id="run-b",
            checks=(ValidationCheck("candidate", True, True, True),),
        )

        with self.assertRaisesRegex(PromotionError, "not pass"):
            promoter.promote_ready_to_ready(
                run_id="run-b",
                source_name="biz_legacy_integrated",
                expected_rows=2,
                candidate_report=report,
            )
        promoter._rename.assert_not_called()


if __name__ == "__main__":
    unittest.main()
