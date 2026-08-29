"""File validation, run locking, and manifest-last publication."""

from __future__ import annotations

import csv
from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Any

from .models import PAYLOAD_FIELDS, WRAPPER_FIELDS, ValidationCheck, ValidationReport
from .serializers import sha256_file


class PublishingError(RuntimeError):
    """A staging or publication invariant was violated."""


@dataclass(frozen=True, slots=True)
class RunPaths:
    data_staging: Path
    backup_staging: Path
    data_final: Path
    backup_final: Path


def build_run_paths(
    *,
    data_root: Path,
    backup_root: Path,
    source_name: str,
    ingest_date: str,
    run_id: str,
) -> RunPaths:
    partition = Path("bronze") / source_name / f"ingest_date={ingest_date}" / f"run_id={run_id}"
    return RunPaths(
        data_staging=data_root / ".publishing" / f"run_id={run_id}",
        backup_staging=backup_root / ".publishing" / f"run_id={run_id}",
        data_final=data_root / partition,
        backup_final=backup_root / partition,
    )


class RunLock:
    def __init__(self, path: Path, *, run_id: str) -> None:
        self.path = path
        self.run_id = run_id
        self._acquired = False

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise PublishingError(
                f"another run lock exists and requires manual inspection: {self.path}"
            ) from exc
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump({"run_id": self.run_id, "pid": os.getpid()}, stream)
        self._acquired = True

    def release(self) -> None:
        if self._acquired:
            self.path.unlink(missing_ok=False)
            self._acquired = False

    def __enter__(self) -> "RunLock":
        self.acquire()
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.release()


def prepare_staging(paths: RunPaths) -> None:
    for path in (paths.data_staging, paths.backup_staging):
        if path.exists():
            raise PublishingError(f"run staging path already exists: {path}")
        path.mkdir(parents=True)
    if paths.data_final.exists() or paths.backup_final.exists():
        raise PublishingError("final run path already exists; overwrite is forbidden")


def _csv_contract(path: Path, expected_headers: tuple[str, ...], expected_rows: int) -> tuple[ValidationCheck, ...]:
    raw = path.read_bytes()
    bom_ok = raw.startswith(b"\xef\xbb\xbf")
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.reader(stream, delimiter=","))
    header = tuple(rows[0]) if rows else ()
    data_rows = rows[1:] if rows else []
    width_ok = all(len(row) == len(expected_headers) for row in data_rows)
    return (
        ValidationCheck(f"{path.name}_bom", bom_ok, True, bom_ok),
        ValidationCheck(f"{path.name}_headers", header == expected_headers, expected_headers, header),
        ValidationCheck(f"{path.name}_row_count", len(data_rows) == expected_rows, expected_rows, len(data_rows)),
        ValidationCheck(f"{path.name}_column_count", width_ok, len(expected_headers), "all rows" if width_ok else "mismatch"),
    )


def validate_staged_files(
    *,
    run_id: str,
    raw_artifacts: tuple[Any, ...],
    exchange_csv: Path,
    backup_csv: Path,
    expected_rows: int,
) -> ValidationReport:
    checks: list[ValidationCheck] = []
    for artifact in raw_artifacts:
        exists = artifact.path.is_file()
        checks.append(ValidationCheck(f"raw_page_{artifact.page}_exists", exists, True, exists))
        if exists:
            size = artifact.path.stat().st_size
            checksum = sha256_file(artifact.path)
            checks.append(ValidationCheck(f"raw_page_{artifact.page}_size", size == artifact.file_size_bytes, artifact.file_size_bytes, size))
            checks.append(ValidationCheck(f"raw_page_{artifact.page}_checksum", checksum == artifact.checksum_sha256, artifact.checksum_sha256, checksum))
    checks.extend(_csv_contract(exchange_csv, PAYLOAD_FIELDS, expected_rows))
    checks.extend(_csv_contract(backup_csv, WRAPPER_FIELDS + PAYLOAD_FIELDS, expected_rows))
    return ValidationReport(run_id=run_id, checks=tuple(checks))


def publish_run_directories(paths: RunPaths) -> None:
    for target in (paths.data_final, paths.backup_final):
        if target.exists():
            raise PublishingError(f"final run path already exists: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
    os.rename(paths.data_staging, paths.data_final)
    os.rename(paths.backup_staging, paths.backup_final)
