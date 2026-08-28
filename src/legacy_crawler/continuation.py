"""Atomic persistence for the server-issued records continuation cursor."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
from typing import Any, Mapping


class ContinuationStateError(RuntimeError):
    """Continuation state is absent or violates the source contract."""


@dataclass(frozen=True, slots=True)
class ContinuationState:
    cursor: str
    checkpoint: str
    dataset_id: str
    released_rows: int
    next_refresh_at: str
    has_more: bool

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ContinuationState":
        cursor = value.get("cursor")
        checkpoint = value.get("checkpoint")
        dataset_id = value.get("dataset_id")
        released_rows = value.get("released_rows")
        next_refresh_at = value.get("next_refresh_at")
        has_more = value.get("has_more")
        if not all(isinstance(item, str) and item for item in (
            cursor, checkpoint, dataset_id, next_refresh_at
        )):
            raise ContinuationStateError("continuation state contains invalid text fields")
        if not isinstance(released_rows, int) or released_rows < 0:
            raise ContinuationStateError("continuation released_rows is invalid")
        if not isinstance(has_more, bool):
            raise ContinuationStateError("continuation has_more is invalid")
        return cls(cursor, checkpoint, dataset_id, released_rows, next_refresh_at, has_more)


class ContinuationStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> ContinuationState:
        if not self.path.is_file():
            raise ContinuationStateError("continuation state does not exist")
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ContinuationStateError("continuation state cannot be read") from exc
        if not isinstance(value, Mapping):
            raise ContinuationStateError("continuation state must be an object")
        return ContinuationState.from_mapping(value)

    def save(self, state: ContinuationState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.unlink(missing_ok=True)
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(asdict(state), stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.path)
