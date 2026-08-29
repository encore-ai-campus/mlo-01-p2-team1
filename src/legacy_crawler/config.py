"""Environment-backed crawler configuration without secret persistence."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
import os


PRODUCTION_COLLECTION = "legacy_records"
STAGING_COLLECTION_PREFIX = "legacy_records_staging_"


def _positive_int(values: Mapping[str, str], key: str, default: int) -> int:
    raw = values.get(key, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{key} must be an integer") from exc
    if value <= 0:
        raise ValueError(f"{key} must be greater than zero")
    return value


def _non_negative_float(
    values: Mapping[str, str], key: str, default: float
) -> float:
    raw = values.get(key, str(default))
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{key} must be numeric") from exc
    if value < 0:
        raise ValueError(f"{key} must not be negative")
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    api_base_url: str
    api_key_endpoint: str
    api_meta_endpoint: str
    api_records_endpoint: str
    source_name: str
    mongodb_uri: str
    mongodb_database: str
    mongodb_records_collection: str
    mongodb_manifest_collection: str
    mongodb_runs_collection: str
    mongodb_staging_prefix: str
    user_agent: str
    request_timeout_seconds: int
    page_limit: int
    max_retries: int
    backoff_base_seconds: float
    backoff_max_seconds: float
    jitter_max_seconds: float
    safety_delay_seconds: float
    data_root: Path
    backup_root: Path
    log_root: Path
    state_root: Path

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "Settings":
        values = os.environ if environ is None else environ
        settings = cls(
            api_base_url=values.get(
                "BRONZE_API_BASE_URL", "http://192.168.0.51:8000"
            ).rstrip("/"),
            api_key_endpoint=values.get(
                "BRONZE_API_KEY_ENDPOINT", "/public/v1/key"
            ),
            api_meta_endpoint=values.get("BRONZE_API_META_ENDPOINT", "/api/v1/meta"),
            api_records_endpoint=values.get(
                "BRONZE_API_RECORDS_ENDPOINT", "/api/v1/records"
            ),
            source_name=values.get(
                "BRONZE_SOURCE_NAME", "biz_legacy_integrated"
            ),
            mongodb_uri=values.get(
                "MONGODB_URI", "mongodb://192.168.0.33:27017/legacy_bronze"
            ),
            mongodb_database=values.get("MONGODB_DATABASE", "legacy_bronze"),
            mongodb_records_collection=values.get(
                "MONGODB_RECORDS_COLLECTION", PRODUCTION_COLLECTION
            ),
            mongodb_manifest_collection=values.get(
                "MONGODB_MANIFEST_COLLECTION", "crawl_manifests"
            ),
            mongodb_runs_collection=values.get(
                "MONGODB_RUNS_COLLECTION", "crawler_runs"
            ),
            mongodb_staging_prefix=values.get(
                "MONGODB_STAGING_PREFIX", STAGING_COLLECTION_PREFIX
            ),
            user_agent=values.get("CRAWLER_USER_AGENT", "legacy-crawler/1.0"),
            request_timeout_seconds=_positive_int(
                values, "CRAWLER_REQUEST_TIMEOUT_SECONDS", 15
            ),
            page_limit=_positive_int(values, "CRAWLER_PAGE_LIMIT", 1000),
            max_retries=_positive_int(values, "CRAWLER_MAX_RETRIES", 3),
            backoff_base_seconds=_non_negative_float(
                values, "CRAWLER_BACKOFF_BASE_SECONDS", 2
            ),
            backoff_max_seconds=_non_negative_float(
                values, "CRAWLER_BACKOFF_MAX_SECONDS", 30
            ),
            jitter_max_seconds=_non_negative_float(
                values, "CRAWLER_JITTER_MAX_SECONDS", 1
            ),
            safety_delay_seconds=_non_negative_float(
                values, "CRAWLER_SAFETY_DELAY_SECONDS", 5
            ),
            data_root=Path(values.get("DATA_ROOT", "data")),
            backup_root=Path(values.get("BACKUP_ROOT", "backup")),
            log_root=Path(values.get("LOG_ROOT", "logs")),
            state_root=Path(values.get("STATE_ROOT", "state")),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if self.source_name != "biz_legacy_integrated":
            raise ValueError("BRONZE_SOURCE_NAME must be biz_legacy_integrated")
        if self.mongodb_records_collection != PRODUCTION_COLLECTION:
            raise ValueError("MONGODB_RECORDS_COLLECTION must be legacy_records")
        if self.mongodb_staging_prefix == PRODUCTION_COLLECTION:
            raise ValueError("staging prefix must not equal the production collection")
        if not self.mongodb_staging_prefix.startswith(STAGING_COLLECTION_PREFIX):
            raise ValueError(
                "MONGODB_STAGING_PREFIX must start with legacy_records_staging_"
            )
        if self.backoff_max_seconds < self.backoff_base_seconds:
            raise ValueError(
                "CRAWLER_BACKOFF_MAX_SECONDS must be at least the base delay"
            )
        for endpoint in (
            self.api_key_endpoint,
            self.api_meta_endpoint,
            self.api_records_endpoint,
        ):
            if not endpoint.startswith("/"):
                raise ValueError("API endpoint paths must start with '/'")

    @property
    def production_promotion_enabled(self) -> bool:
        """Production promotion stays disabled until an explicit safe call path exists."""

        return False
