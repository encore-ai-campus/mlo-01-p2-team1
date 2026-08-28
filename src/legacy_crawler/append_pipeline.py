"""Page-run append orchestration driven only by signed continuation cursors."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any

from . import __version__
from .client import BronzeRelayClient
from .config import Settings
from .continuation import ContinuationState, ContinuationStateError, ContinuationStore
from .logging_config import StructuredRunLogger
from .main import generate_run_id
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
from .validator import validate_accumulated_production, validate_appended_page


class PageAppendError(RuntimeError):
    """A page append cycle failed and must not fall back to page one."""


@dataclass(frozen=True, slots=True)
class PageAppendResult:
    last_run_id: str
    appended_rows: int
    page_count: int
    production_rows: int
    next_schedule: NextRunSchedule
    backup_collection: str | None = None


def _required_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise PageAppendError(f"records response missing {name}")
    return value


def run_page_append_cycle(
    settings: Settings,
    *,
    initialize: bool = False,
    client: BronzeRelayClient | None = None,
    storage: MongoStorage | None = None,
) -> PageAppendResult:
    relay = client or BronzeRelayClient(settings)
    mongo = storage or MongoStorage(settings)
    state_store = ContinuationStore(settings.state_root / "records_continuation.json")
    cycle_started = datetime.now().astimezone()
    timestamp = cycle_started.strftime("%Y%m%dT%H%M%S%z")
    backup_collection: str | None = None
    page_run_ids: list[str] = []
    current_run_id: str | None = None
    current_page_inserted = False

    try:
        with RunLock(settings.state_root / "crawler.lock", run_id="page-append-service"):
            mongo.ping()
            if initialize:
                if state_store.path.exists():
                    raise PageAppendError(
                        "initialization refused because continuation state exists"
                    )
                backup_collection = mongo.initialize_page_append_production(
                    timestamp=timestamp
                )
                previous_state = None
                initial_cursor = None
            else:
                previous_state = state_store.load()
                initial_cursor = previous_state.cursor

            api_key = relay.fetch_api_key()
            metadata = dict(relay.fetch_metadata(api_key=api_key))
            dataset_id = relay.resolve_dataset_id(
                metadata, source_name=settings.source_name
            )
            if previous_state is not None and dataset_id != previous_state.dataset_id:
                raise PageAppendError("metadata dataset_id changed")
            server_time = _required_text(metadata.get("server_time"), "server_time")
            metadata_next_refresh = _required_text(
                metadata.get("next_refresh_at"), "next_refresh_at"
            )
            expected_checkpoint = (
                previous_state.checkpoint
                if previous_state is not None and previous_state.has_more
                else None
            )
            expected_released_rows = (
                previous_state.released_rows
                if previous_state is not None and previous_state.has_more
                else None
            )

            appended_rows = 0
            last_run_id = ""
            pages_seen = 0
            for source_page in relay.iter_record_pages(
                dataset_id=dataset_id,
                api_key=api_key,
                initial_cursor=initial_cursor,
                expected_checkpoint=expected_checkpoint,
                expected_released_rows=expected_released_rows,
            ):
                pages_seen += 1
                current_run_id = generate_run_id()
                last_run_id = current_run_id
                page_run_ids.append(current_run_id)
                records = [dict(item) for item in source_page.items]
                collected_at = datetime.now().astimezone().isoformat()
                ingest_date = datetime.now().astimezone().date().isoformat()
                logger = StructuredRunLogger(
                    log_root=settings.log_root,
                    run_id=current_run_id,
                    source_name=settings.source_name,
                )
                logger.register_secret(api_key)
                paths = build_run_paths(
                    data_root=settings.data_root,
                    backup_root=settings.backup_root,
                    source_name=settings.source_name,
                    ingest_date=ingest_date,
                    run_id=current_run_id,
                )
                mongo.create_run(
                    run_id=current_run_id,
                    source_name=settings.source_name,
                    started_at=collected_at,
                    expected_rows=len(records),
                    append_mode=True,
                )
                prepare_staging(paths)
                stored_page = replace(source_page, number=1)
                raw = write_raw_page(stored_page, paths.data_staging / "raw")
                exchange = paths.data_staging / "exchange" / "legacy_full_15cols.csv"
                backup = paths.backup_staging / "raw_full_20cols.csv"
                write_exchange_csv(records, exchange)
                write_backup_csv(records, backup)
                file_report = validate_staged_files(
                    run_id=current_run_id,
                    raw_artifacts=(raw,),
                    exchange_csv=exchange,
                    backup_csv=backup,
                    expected_rows=len(records),
                )
                if not file_report.passed:
                    raise PageAppendError("page file validation failed")

                inserted = mongo.append_page(
                    current_run_id,
                    records,
                    source_name=settings.source_name,
                    collected_at=collected_at,
                )
                current_page_inserted = inserted > 0
                mongo.set_inserted_rows(current_run_id, inserted)
                mongo.transition_to_validating(
                    current_run_id,
                    started_at=datetime.now().astimezone().isoformat(),
                )
                page_report = validate_appended_page(
                    mongo.production,
                    api_records=records,
                    run_id=current_run_id,
                    source_name=settings.source_name,
                )
                mongo.record_validation(page_report)
                if not page_report.passed:
                    raise PageAppendError("page MongoDB validation failed")

                publish_run_directories(paths)
                final_raw = RawArtifact(
                    page=1,
                    path=paths.data_final / "raw" / raw.path.name,
                    file_size_bytes=raw.file_size_bytes,
                    checksum_sha256=raw.checksum_sha256,
                )
                final_exchange = paths.data_final / "exchange" / exchange.name
                final_backup = paths.backup_final / backup.name
                has_more = source_page.parsed["has_more"]
                manifest = build_file_manifest(
                    run_id=current_run_id,
                    source_name=settings.source_name,
                    source_uri=f"{settings.api_base_url}{settings.api_records_endpoint}",
                    collected_at=collected_at,
                    ingest_date=ingest_date,
                    content_type=source_page.response.content_type,
                    http_status=source_page.response.status,
                    retry_count=source_page.response.retry_count,
                    crawler_version=__version__,
                    status=BronzeStatus.SUCCESS,
                    run_dir=paths.data_final,
                    raw_artifacts=(final_raw,),
                    exchange_csv=final_exchange,
                    backup_csv=final_backup,
                    row_count=len(records),
                    page_count=1,
                    dataset_id=dataset_id,
                    source_server_time=_required_text(
                        source_page.parsed.get("server_time"), "server_time"
                    ),
                    next_refresh_at=_required_text(
                        source_page.parsed.get("next_refresh_at"), "next_refresh_at"
                    ),
                    pagination_complete=not has_more,
                    source_page_number=source_page.number,
                )
                mongo.store_operational_manifest(
                    manifest, mongodb_validation_status="pass"
                )
                write_file_manifest(manifest, paths.data_final / "manifest.json")
                mongo.mark_ready_after_page_append(
                    current_run_id,
                    ready_at=datetime.now().astimezone().isoformat(),
                    validation=page_report,
                )

                next_cursor = _required_text(
                    source_page.parsed.get("next_cursor"), "next_cursor"
                )
                state_store.save(
                    ContinuationState(
                        cursor=next_cursor,
                        checkpoint=_required_text(
                            source_page.parsed.get("checkpoint"), "checkpoint"
                        ),
                        dataset_id=dataset_id,
                        released_rows=source_page.parsed["released_rows"],
                        next_refresh_at=_required_text(
                            source_page.parsed.get("next_refresh_at"),
                            "next_refresh_at",
                        ),
                        has_more=has_more,
                    )
                )
                current_page_inserted = False
                current_run_id = None
                appended_rows += len(records)
                logger.event(
                    stage="page_append",
                    event="page_run_ready",
                    status="success",
                    source_page=source_page.number,
                    row_count=len(records),
                )

            if not last_run_id:
                raise PageAppendError("records endpoint returned no page")
            final_state = state_store.load()
            production_report = validate_accumulated_production(
                mongo.production,
                expected_rows=final_state.released_rows,
                source_name=settings.source_name,
                run_id=last_run_id,
            )
            if not production_report.passed:
                raise PageAppendError("accumulated production validation failed")
            schedule = calculate_next_run(
                server_time=server_time,
                next_refresh_at=metadata_next_refresh,
                safety_delay_seconds=settings.safety_delay_seconds,
            )
            return PageAppendResult(
                last_run_id=last_run_id,
                appended_rows=appended_rows,
                page_count=pages_seen,
                production_rows=final_state.released_rows,
                next_schedule=schedule,
                backup_collection=backup_collection,
            )
    except Exception as exc:
        if current_run_id is not None:
            if current_page_inserted:
                try:
                    mongo.rollback_appended_page(current_run_id)
                except Exception:
                    pass
            try:
                mongo.mark_failed(
                    current_run_id,
                    failed_at=datetime.now().astimezone().isoformat(),
                    error=f"page append failed: {type(exc).__name__}",
                )
            except Exception:
                pass
        if initialize and backup_collection is not None:
            try:
                mongo.rollback_page_append_initialization(
                    backup_collection=backup_collection,
                    timestamp=timestamp,
                )
                mongo.mark_page_runs_rolled_back(
                    page_run_ids, error="initial page append rolled back"
                )
                state_store.path.unlink(missing_ok=True)
            except Exception as rollback_exc:
                raise PageAppendError(
                    f"initial page append and rollback failed: {type(rollback_exc).__name__}"
                ) from exc
        if isinstance(exc, (PageAppendError, ContinuationStateError)):
            raise
        raise PageAppendError(f"page append cycle failed: {type(exc).__name__}") from exc
    finally:
        mongo.close()

