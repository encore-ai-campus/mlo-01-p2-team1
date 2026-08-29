"""One-shot Bronze run orchestration with production promotion disabled."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import secrets
from typing import Any

from . import __version__
from .client import BronzeRelayClient
from .config import Settings
from .logging_config import StructuredRunLogger
from .manifest import build_file_manifest, write_file_manifest
from .models import BronzeStatus, RawArtifact
from .mongo_storage import MongoStorage
from .publisher import (
    RunLock,
    build_run_paths,
    prepare_staging,
    publish_run_directories,
    validate_staged_files,
)
from .scheduler import NextRunSchedule, calculate_next_run
from .serializers import write_backup_csv, write_exchange_csv, write_raw_page
from .validator import validate_staging


class RunExecutionError(RuntimeError):
    """The run failed and must never be treated as a published success."""


@dataclass(frozen=True, slots=True)
class RunResult:
    run_id: str
    row_count: int
    page_count: int
    data_path: Path
    backup_path: Path
    staging_collection: str
    next_schedule: NextRunSchedule


def generate_run_id(now: datetime | None = None) -> str:
    timestamp = now or datetime.now().astimezone()
    return f"{timestamp.strftime('%Y%m%dT%H%M%S%z')}-{secrets.token_hex(4)}"


def _metadata_timestamp(metadata: dict[str, Any], field: str) -> str:
    value = metadata.get(field)
    if not isinstance(value, str) or not value:
        raise RunExecutionError(f"metadata missing timezone-aware {field}")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise RunExecutionError(f"metadata {field} has no timezone")
    return value


def run_once(
    settings: Settings,
    *,
    client: BronzeRelayClient | None = None,
    storage: MongoStorage | None = None,
    run_id: str | None = None,
) -> RunResult:
    real_run_id = run_id or generate_run_id()
    source_name = settings.source_name
    started_at = datetime.now().astimezone()
    ingest_date = started_at.date().isoformat()
    paths = build_run_paths(
        data_root=settings.data_root,
        backup_root=settings.backup_root,
        source_name=source_name,
        ingest_date=ingest_date,
        run_id=real_run_id,
    )
    logger = StructuredRunLogger(
        log_root=settings.log_root, run_id=real_run_id, source_name=source_name
    )
    relay = client or BronzeRelayClient(settings)
    mongo = storage or MongoStorage(settings)
    lock = RunLock(settings.state_root / "crawler.lock", run_id=real_run_id)
    stage = "initialization"
    run_created = False
    run_already_failed = False

    try:
        with lock:
            logger.event(stage=stage, event="run_start", status="started")
            stage = "mongodb_connection"
            mongo.ping()
            mongo.create_run(
                run_id=real_run_id,
                source_name=source_name,
                started_at=started_at.isoformat(),
                expected_rows=0,
            )
            run_created = True
            prepare_staging(paths)

            stage = "metadata"
            api_key = relay.fetch_api_key()
            logger.register_secret(api_key)
            metadata_mapping = relay.fetch_metadata(api_key=api_key)
            metadata = dict(metadata_mapping)
            dataset_id = relay.resolve_dataset_id(metadata, source_name=source_name)
            server_time = _metadata_timestamp(metadata, "server_time")
            next_refresh_at = _metadata_timestamp(metadata, "next_refresh_at")
            logger.event(
                stage=stage,
                event="metadata_resolved",
                status="success",
                dataset_id=dataset_id,
                released_rows=metadata.get("released_rows"),
            )

            stage = "pagination"
            raw_artifacts: list[RawArtifact] = []
            records: list[dict[str, Any]] = []
            pages = []
            for page in relay.iter_record_pages(dataset_id=dataset_id, api_key=api_key):
                artifact = write_raw_page(page, paths.data_staging / "raw")
                raw_artifacts.append(artifact)
                pages.append(page)
                records.extend(dict(item) for item in page.items)
                logger.event(
                    stage=stage,
                    event="page_collected",
                    status="success",
                    page=page.number,
                    page_row_count=len(page.items),
                    total_row_count=len(records),
                    retry_count=page.response.retry_count,
                )
            if not pages or pages[-1].parsed.get("has_more") is not False:
                raise RunExecutionError("pagination did not terminate with has_more=false")
            collected_at = datetime.now().astimezone().isoformat()
            mongo.set_expected_rows(real_run_id, len(records))

            stage = "csv_serialization"
            exchange_csv = paths.data_staging / "exchange" / "legacy_full_15cols.csv"
            backup_csv = paths.backup_staging / "raw_full_20cols.csv"
            write_exchange_csv(records, exchange_csv)
            write_backup_csv(records, backup_csv)

            stage = "file_validation"
            file_report = validate_staged_files(
                run_id=real_run_id,
                raw_artifacts=tuple(raw_artifacts),
                exchange_csv=exchange_csv,
                backup_csv=backup_csv,
                expected_rows=len(records),
            )
            if not file_report.passed:
                raise RunExecutionError("staged file validation failed")

            stage = "mongodb_insert"
            inserted = mongo.insert_full_snapshot(
                real_run_id,
                records,
                source_name=source_name,
                collected_at=collected_at,
            )
            mongo.set_inserted_rows(real_run_id, inserted)
            mongo.transition_to_validating(
                real_run_id, started_at=datetime.now().astimezone().isoformat()
            )

            stage = "mongodb_validation"
            staging_name = mongo.staging_name(real_run_id)
            mongo_report = validate_staging(
                mongo.database[staging_name],
                api_records=records,
                run_id=real_run_id,
                source_name=source_name,
            )
            mongo.record_validation(mongo_report)
            if not mongo_report.passed:
                run_already_failed = True
                raise RunExecutionError("MongoDB staging validation failed")

            stage = "publishing"
            publish_run_directories(paths)
            final_artifacts = tuple(
                RawArtifact(
                    page=artifact.page,
                    path=paths.data_final / "raw" / artifact.path.name,
                    file_size_bytes=artifact.file_size_bytes,
                    checksum_sha256=artifact.checksum_sha256,
                )
                for artifact in raw_artifacts
            )
            final_exchange = paths.data_final / "exchange" / exchange_csv.name
            final_backup = paths.backup_final / backup_csv.name

            stage = "manifest"
            manifest = build_file_manifest(
                run_id=real_run_id,
                source_name=source_name,
                source_uri=f"{settings.api_base_url}{settings.api_records_endpoint}",
                collected_at=collected_at,
                ingest_date=ingest_date,
                content_type=pages[0].response.content_type,
                http_status=pages[-1].response.status,
                retry_count=sum(page.response.retry_count for page in pages),
                crawler_version=__version__,
                status=BronzeStatus.SUCCESS,
                run_dir=paths.data_final,
                raw_artifacts=final_artifacts,
                exchange_csv=final_exchange,
                backup_csv=final_backup,
                row_count=len(records),
                page_count=len(pages),
                dataset_id=dataset_id,
                source_server_time=server_time,
                next_refresh_at=next_refresh_at,
            )
            mongo.store_operational_manifest(
                manifest, mongodb_validation_status="pass"
            )
            write_file_manifest(manifest, paths.data_final / "manifest.json")

            schedule = calculate_next_run(
                server_time=server_time,
                next_refresh_at=next_refresh_at,
                safety_delay_seconds=settings.safety_delay_seconds,
            )
            logger.event(
                stage="complete",
                event="run_validated_not_promoted",
                status="success",
                row_count=len(records),
                page_count=len(pages),
                staging_collection=staging_name,
                crawler_state="validating",
                next_source_time=schedule.source_target_time.isoformat(),
                next_local_time=schedule.local_run_time.isoformat(),
            )
            return RunResult(
                run_id=real_run_id,
                row_count=len(records),
                page_count=len(pages),
                data_path=paths.data_final,
                backup_path=paths.backup_final,
                staging_collection=staging_name,
                next_schedule=schedule,
            )
    except Exception as exc:
        logger.event(
            stage=stage,
            event="run_failed",
            status="error",
            error=f"{type(exc).__name__}: {exc}",
        )
        if run_created and not run_already_failed:
            try:
                mongo.mark_failed(
                    real_run_id,
                    failed_at=datetime.now().astimezone().isoformat(),
                    error=f"{stage}: {type(exc).__name__}",
                )
            except Exception as state_exc:
                logger.event(
                    stage="crawler_runs",
                    event="failed_state_recording_failed",
                    status="error",
                    error=f"{type(state_exc).__name__}: {state_exc}",
                )
        raise
    finally:
        mongo.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect one complete Bronze run")
    parser.add_argument("--run-id", help="Explicit run ID for controlled testing")
    args = parser.parse_args()
    result = run_once(Settings.from_env(), run_id=args.run_id)
    print(
        f"run_id={result.run_id} rows={result.row_count} "
        f"pages={result.page_count} state=validating"
    )
    return 0
