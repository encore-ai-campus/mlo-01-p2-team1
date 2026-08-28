"""Source-clock-aware next-run calculation without service registration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True, slots=True)
class NextRunSchedule:
    source_target_time: datetime
    local_run_time: datetime
    clock_offset_seconds: float


def _aware_timestamp(value: str, name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{name} must include a timezone")
    return parsed


def calculate_next_run(
    *,
    server_time: str,
    next_refresh_at: str,
    safety_delay_seconds: float = 5,
    observed_local_time: datetime | None = None,
) -> NextRunSchedule:
    if safety_delay_seconds < 0:
        raise ValueError("safety delay must not be negative")
    server = _aware_timestamp(server_time, "server_time")
    refresh = _aware_timestamp(next_refresh_at, "next_refresh_at")
    observed = observed_local_time or datetime.now().astimezone()
    if observed.tzinfo is None:
        raise ValueError("observed_local_time must include a timezone")
    offset = server - observed.astimezone(server.tzinfo)
    source_target = refresh + timedelta(seconds=safety_delay_seconds)
    local_target = source_target - offset
    return NextRunSchedule(
        source_target_time=source_target,
        local_run_time=local_target.astimezone(observed.tzinfo),
        clock_offset_seconds=offset.total_seconds(),
    )
