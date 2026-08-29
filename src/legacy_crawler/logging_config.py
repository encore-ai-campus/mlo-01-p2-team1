"""Structured JSON logging with recursive secret masking."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any


SECRET_FIELD_MARKERS = (
    "api_key",
    "x-api-key",
    "authorization",
    "password",
    "secret",
    "token",
)


def mask_value(value: Any, *, secrets: tuple[str, ...] = ()) -> Any:
    if isinstance(value, dict):
        return {
            key: (
                "***REDACTED***"
                if any(marker in key.lower() for marker in SECRET_FIELD_MARKERS)
                else mask_value(item, secrets=secrets)
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [mask_value(item, secrets=secrets) for item in value]
    if isinstance(value, str):
        masked = value
        for secret in secrets:
            if secret:
                masked = masked.replace(secret, "***REDACTED***")
        return masked
    return value


class StructuredRunLogger:
    def __init__(
        self,
        *,
        log_root: Path,
        run_id: str,
        source_name: str,
    ) -> None:
        date = datetime.now().astimezone().date().isoformat()
        self.normal_path = log_root / "crawler" / f"crawler_{date}.log"
        self.error_path = log_root / "errors" / f"crawler_error_{date}.log"
        self.normal_path.parent.mkdir(parents=True, exist_ok=True)
        self.error_path.parent.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id
        self.source_name = source_name
        self._secrets: tuple[str, ...] = ()

    def register_secret(self, secret: str) -> None:
        if secret and secret not in self._secrets:
            self._secrets += (secret,)

    def event(
        self,
        *,
        stage: str,
        event: str,
        status: str,
        error: str | None = None,
        **details: Any,
    ) -> None:
        record: dict[str, Any] = {
            "timestamp": datetime.now().astimezone().isoformat(),
            "run_id": self.run_id,
            "source_name": self.source_name,
            "stage": stage,
            "event": event,
            "status": status,
        }
        record.update(details)
        if error is not None:
            record["error"] = error
        safe_record = mask_value(record, secrets=self._secrets)
        line = json.dumps(safe_record, ensure_ascii=False, separators=(",", ":"))
        with self.normal_path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(line + "\n")
        if status == "error":
            with self.error_path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(line + "\n")
