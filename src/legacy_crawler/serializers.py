"""Lossless Raw-body storage and source-preserving CSV serialization."""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from .client import CollectedPage
from .models import PAYLOAD_FIELDS, WRAPPER_FIELDS, RawArtifact


class SerializationError(ValueError):
    """Input records do not satisfy the approved source contract."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_raw_page(page: CollectedPage, raw_dir: Path) -> RawArtifact:
    """Write the exact records response bytes without JSON reserialization."""

    raw_dir.mkdir(parents=True, exist_ok=True)
    path = raw_dir / f"page_{page.number:04d}.json"
    with path.open("xb") as stream:
        stream.write(page.response.body)
    return RawArtifact(
        page=page.number,
        path=path,
        file_size_bytes=path.stat().st_size,
        checksum_sha256=sha256_file(path),
    )


def write_raw_pages(
    pages: Iterable[CollectedPage], raw_dir: Path
) -> tuple[RawArtifact, ...]:
    artifacts = tuple(write_raw_page(page, raw_dir) for page in pages)
    if not artifacts:
        raise SerializationError("at least one Raw JSON page is required")
    return artifacts


def _validate_record(record: Mapping[str, Any], row_number: int) -> Mapping[str, Any]:
    missing_wrapper = [field for field in WRAPPER_FIELDS if field not in record]
    if missing_wrapper:
        raise SerializationError(
            f"row {row_number} is missing wrapper fields: {missing_wrapper}"
        )
    payload = record.get("payload")
    if not isinstance(payload, Mapping):
        raise SerializationError(f"row {row_number} payload must be an object")
    missing_payload = [field for field in PAYLOAD_FIELDS if field not in payload]
    if missing_payload:
        raise SerializationError(
            f"row {row_number} is missing payload fields: {missing_payload}"
        )
    return payload


def _write_csv(
    path: Path,
    headers: Sequence[str],
    rows: Iterable[Sequence[Any]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream, delimiter=",", quoting=csv.QUOTE_MINIMAL)
        writer.writerow(headers)
        writer.writerows(rows)


def write_exchange_csv(records: Iterable[Mapping[str, Any]], path: Path) -> None:
    def rows() -> Iterable[Sequence[Any]]:
        for row_number, record in enumerate(records, start=1):
            payload = _validate_record(record, row_number)
            yield [payload[field] for field in PAYLOAD_FIELDS]

    _write_csv(path, PAYLOAD_FIELDS, rows())


def write_backup_csv(records: Iterable[Mapping[str, Any]], path: Path) -> None:
    headers = WRAPPER_FIELDS + PAYLOAD_FIELDS

    def rows() -> Iterable[Sequence[Any]]:
        for row_number, record in enumerate(records, start=1):
            payload = _validate_record(record, row_number)
            yield [record[field] for field in WRAPPER_FIELDS] + [
                payload[field] for field in PAYLOAD_FIELDS
            ]

    _write_csv(path, headers, rows())
