from __future__ import annotations

import csv
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest

from legacy_crawler.client import CollectedPage, HttpBody
from legacy_crawler.manifest import (
    ManifestError,
    build_file_manifest,
    validate_file_manifest,
    write_file_manifest,
)
from legacy_crawler.models import BronzeStatus, PAYLOAD_FIELDS, WRAPPER_FIELDS
from legacy_crawler.serializers import (
    sha256_file,
    write_backup_csv,
    write_exchange_csv,
    write_raw_pages,
)


def source_record(record_id: int) -> dict[str, object]:
    payload = {field: f"value-{field}" for field in PAYLOAD_FIELDS}
    payload["mgr_nm"] = "  홍 길동  "
    payload["area_nm"] = "R&D, 플랫폼\n2팀"
    payload["mgr_dept_nm"] = ""
    payload["mgr_act_yn"] = "y"
    return {
        "record_id": record_id,
        "source_row_no": record_id,
        "source_record_sha256": f"sha-{record_id}",
        "release_slot": 1,
        "scheduled_release_at": " 2026/08/27 01:02:03 ",
        "payload": payload,
    }


def page(number: int, raw_body: bytes) -> CollectedPage:
    return CollectedPage(
        number=number,
        response=HttpBody(
            status=200,
            headers={"content-type": "application/json"},
            body=raw_body,
        ),
        parsed=json.loads(raw_body),
        requested_cursor=None,
    )


class FileArtifactContractTests(unittest.TestCase):
    def test_raw_bytes_csv_contract_and_immutable_manifest(self) -> None:
        raw_one = b'{\n  "items": [], "count": 0, "has_more": true, "next_cursor": "x"\n}\n'
        raw_two = b'{"items":[],"count":0,"has_more":false,"next_cursor":null}'
        records = [source_record(1), source_record(2)]

        # Keep test writes inside the repository workspace. This also mirrors
        # the crawler contract that publishing and final paths share a volume.
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            root = Path(temp)
            run_dir = root / "data" / "bronze" / "biz_legacy_integrated" / "ingest_date=2026-08-27" / "run_id=test"
            raw_dir = run_dir / "raw"
            exchange = run_dir / "exchange" / "legacy_full_15cols.csv"
            backup = root / "backup" / "raw_full_20cols.csv"

            artifacts = write_raw_pages(
                [page(1, raw_one), page(2, raw_two)], raw_dir
            )
            write_exchange_csv(records, exchange)
            write_backup_csv(records, backup)

            self.assertEqual((raw_dir / "page_0001.json").read_bytes(), raw_one)
            self.assertEqual((raw_dir / "page_0002.json").read_bytes(), raw_two)
            self.assertEqual(artifacts[0].checksum_sha256, sha256_file(artifacts[0].path))

            exchange_bytes = exchange.read_bytes()
            backup_bytes = backup.read_bytes()
            self.assertTrue(exchange_bytes.startswith(b"\xef\xbb\xbf"))
            self.assertTrue(backup_bytes.startswith(b"\xef\xbb\xbf"))
            exchange_rows = list(
                csv.reader(StringIO(exchange_bytes.decode("utf-8-sig")))
            )
            backup_rows = list(csv.reader(StringIO(backup_bytes.decode("utf-8-sig"))))
            self.assertEqual(len(exchange_rows[0]), 15)
            self.assertEqual(len(backup_rows[0]), 20)
            self.assertEqual(exchange_rows[1][0], "  홍 길동  ")
            self.assertEqual(exchange_rows[1][2], "R&D, 플랫폼\n2팀")
            self.assertEqual(exchange_rows[1][8], "")
            self.assertEqual(exchange_rows[1][6], "y")

            manifest = build_file_manifest(
                run_id="test",
                source_name="biz_legacy_integrated",
                source_uri="http://example/api/v1/records",
                collected_at="2026-08-27T11:25:10+09:00",
                ingest_date="2026-08-27",
                content_type="application/json",
                http_status=200,
                retry_count=0,
                crawler_version="test",
                status=BronzeStatus.SUCCESS,
                run_dir=run_dir,
                raw_artifacts=artifacts,
                exchange_csv=exchange,
                backup_csv=backup,
                row_count=2,
                page_count=2,
            )
            self.assertEqual(manifest["pipeline_status"], "pending")
            self.assertNotIn("mongodb_validation_status", manifest)
            self.assertEqual(manifest["raw_file_count"], 2)
            self.assertEqual(manifest["checksum_sha256"], sha256_file(artifacts[0].path))
            manifest_path = run_dir / "manifest.json"
            write_file_manifest(manifest, manifest_path)
            with self.assertRaises(FileExistsError):
                write_file_manifest(manifest, manifest_path)

            artifacts[1].path.write_bytes(b"tampered")
            with self.assertRaises(ManifestError):
                validate_file_manifest(manifest, run_dir=run_dir)

    def test_success_manifest_rejects_incomplete_pagination(self) -> None:
        incomplete = b'{"items":[],"count":0,"has_more":true,"next_cursor":"more"}'
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            run_dir = Path(temp) / "run_id=incomplete"
            artifacts = write_raw_pages([page(1, incomplete)], run_dir / "raw")
            with self.assertRaisesRegex(ManifestError, "has_more=false"):
                build_file_manifest(
                    run_id="incomplete",
                    source_name="biz_legacy_integrated",
                    source_uri="http://example/api/v1/records",
                    collected_at="2026-08-27T11:25:10+09:00",
                    ingest_date="2026-08-27",
                    content_type="application/json",
                    http_status=200,
                    retry_count=0,
                    crawler_version="test",
                    status=BronzeStatus.SUCCESS,
                    run_dir=run_dir,
                    raw_artifacts=artifacts,
                    page_count=1,
                )


if __name__ == "__main__":
    unittest.main()
