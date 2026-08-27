"""Immutable file manifest creation and validation.

The file manifest captures Bronze collection-time evidence. It always starts
with ``pipeline_status=pending`` and intentionally omits
``mongodb_validation_status`` until Stage 4 produces a real validation result
in the operational MongoDB manifest.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
from pathlib import Path
from typing import Any

from .models import BronzeStatus, PipelineStatus, RawArtifact
from .serializers import sha256_file


REQUIRED_FIELDS = (
    "run_id",
    "source_name",
    "source_uri",
    "collected_at",
    "ingest_date",
    "raw_path",
    "content_type",
    "file_size_bytes",
    "checksum_sha256",
    "http_status",
    "retry_count",
    "crawler_version",
    "status",
)


class ManifestError(ValueError):
    """The immutable file manifest violates its approved contract."""


def _relative_path(path: Path, run_dir: Path) -> str:
    try:
        return path.relative_to(run_dir).as_posix()
    except ValueError as exc:
        raise ManifestError(f"artifact is outside run directory: {path}") from exc


def build_file_manifest(
    *,
    run_id: str,
    source_name: str,
    source_uri: str,
    collected_at: str,
    ingest_date: str,
    content_type: str,
    http_status: int,
    retry_count: int,
    crawler_version: str,
    status: BronzeStatus,
    run_dir: Path,
    raw_artifacts: Sequence[RawArtifact],
    exchange_csv: Path | None = None,
    backup_csv: Path | None = None,
    row_count: int | None = None,
    page_count: int | None = None,
    dataset_id: str | None = None,
    source_server_time: str | None = None,
    next_refresh_at: str | None = None,
) -> dict[str, Any]:
    if not raw_artifacts:
        raise ManifestError("raw_artifacts must contain at least one real file")
    primary = raw_artifacts[0]
    manifest: dict[str, Any] = {
        "run_id": run_id,
        "source_name": source_name,
        "source_uri": source_uri,
        "collected_at": collected_at,
        "ingest_date": ingest_date,
        "raw_path": _relative_path(primary.path, run_dir),
        "content_type": content_type,
        "file_size_bytes": primary.file_size_bytes,
        "checksum_sha256": primary.checksum_sha256,
        "http_status": http_status,
        "retry_count": retry_count,
        "crawler_version": crawler_version,
        "status": status.value,
        "pipeline_status": PipelineStatus.PENDING.value,
        "raw_artifacts": [
            {
                "page": artifact.page,
                "path": _relative_path(artifact.path, run_dir),
                "file_size_bytes": artifact.file_size_bytes,
                "checksum_sha256": artifact.checksum_sha256,
            }
            for artifact in raw_artifacts
        ],
        "raw_file_count": len(raw_artifacts),
        "raw_total_size_bytes": sum(
            artifact.file_size_bytes for artifact in raw_artifacts
        ),
    }
    optional_values = {
        "dataset_id": dataset_id,
        "row_count": row_count,
        "page_count": page_count,
        "source_server_time": source_server_time,
        "next_refresh_at": next_refresh_at,
    }
    manifest.update(
        {key: value for key, value in optional_values.items() if value is not None}
    )
    if exchange_csv is not None:
        manifest["csv_file"] = _relative_path(exchange_csv, run_dir)
        manifest["csv_sha256"] = sha256_file(exchange_csv)
    if backup_csv is not None:
        manifest["backup_csv_file"] = backup_csv.as_posix()
        manifest["backup_csv_sha256"] = sha256_file(backup_csv)
    validate_file_manifest(manifest, run_dir=run_dir)
    return manifest


def validate_file_manifest(manifest: Mapping[str, Any], *, run_dir: Path) -> None:
    missing = [field for field in REQUIRED_FIELDS if field not in manifest]
    if missing:
        raise ManifestError(f"manifest is missing required fields: {missing}")
    if manifest.get("pipeline_status") != PipelineStatus.PENDING.value:
        raise ManifestError("file manifest pipeline_status must be pending")
    if "mongodb_validation_status" in manifest:
        raise ManifestError(
            "file manifest must not claim MongoDB validation before Stage 4"
        )
    if manifest.get("status") not in {status.value for status in BronzeStatus}:
        raise ManifestError("manifest status is invalid")
    artifacts = manifest.get("raw_artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise ManifestError("raw_artifacts must be a non-empty list")
    if manifest.get("raw_file_count") != len(artifacts):
        raise ManifestError("raw_file_count does not match raw_artifacts")

    total_size = 0
    for expected_page, artifact in enumerate(artifacts, start=1):
        if not isinstance(artifact, Mapping):
            raise ManifestError("raw artifact must be an object")
        if artifact.get("page") != expected_page:
            raise ManifestError("raw artifact pages must be contiguous from 1")
        path_value = artifact.get("path")
        if not isinstance(path_value, str):
            raise ManifestError("raw artifact path must be a string")
        path = run_dir / path_value
        if not path.is_file():
            raise ManifestError(f"raw artifact does not exist: {path_value}")
        size = path.stat().st_size
        if artifact.get("file_size_bytes") != size:
            raise ManifestError(f"raw artifact size mismatch: {path_value}")
        if artifact.get("checksum_sha256") != sha256_file(path):
            raise ManifestError(f"raw artifact checksum mismatch: {path_value}")
        total_size += size

    if manifest.get("raw_total_size_bytes") != total_size:
        raise ManifestError("raw_total_size_bytes does not match real files")
    if "page_count" in manifest and manifest.get("page_count") != len(artifacts):
        raise ManifestError("page_count does not match raw_artifacts")
    primary = artifacts[0]
    if manifest.get("raw_path") != primary["path"]:
        raise ManifestError("top-level raw_path must identify the first real page")
    if manifest.get("file_size_bytes") != primary["file_size_bytes"]:
        raise ManifestError("top-level file size must belong to raw_path")
    if manifest.get("checksum_sha256") != primary["checksum_sha256"]:
        raise ManifestError("top-level checksum must belong to raw_path")

    if manifest.get("status") == BronzeStatus.SUCCESS.value:
        last_path = run_dir / artifacts[-1]["path"]
        try:
            final_page = json.loads(last_path.read_bytes())
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ManifestError("final Raw page is not valid JSON") from exc
        if not isinstance(final_page, dict) or final_page.get("has_more") is not False:
            raise ManifestError(
                "success requires the final real Raw page to have has_more=false"
            )


def write_file_manifest(manifest: Mapping[str, Any], path: Path) -> None:
    """Create the immutable evidence file once; never overwrite it."""

    validate_file_manifest(manifest, run_dir=path.parent)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(manifest, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
