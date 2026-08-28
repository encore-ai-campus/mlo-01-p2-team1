"""Shared immutable contracts for source fields, lineage, and run states."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Mapping


WRAPPER_FIELDS = (
    "record_id",
    "source_row_no",
    "source_record_sha256",
    "release_slot",
    "scheduled_release_at",
)

PAYLOAD_FIELDS = (
    "mgr_nm",
    "mgr_no",
    "area_nm",
    "area_no",
    "p_area_nm",
    "p_area_no",
    "mgr_act_yn",
    "mgr_pos_nm",
    "mgr_dept_nm",
    "top_area_nm",
    "top_area_no",
    "area_reg_dtm",
    "mgr_hire_dtm",
    "top_area_lvl",
    "top_area_reg_dtm",
)


class BronzeStatus(StrEnum):
    SUCCESS = "success"
    PARTIAL_FAILURE = "partial_failure"
    FAILED = "failed"


class MongoValidationStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"


class PipelineStatus(StrEnum):
    PENDING = "pending"
    PASS = "pass"


class RunState(StrEnum):
    LOADING = "loading"
    VALIDATING = "validating"
    READY = "ready"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class IngestMetadata:
    run_id: str
    source_name: str
    collected_at: str


@dataclass(frozen=True, slots=True)
class RawArtifact:
    page: int
    path: Path
    file_size_bytes: int
    checksum_sha256: str


@dataclass(frozen=True, slots=True)
class ValidationCheck:
    name: str
    passed: bool
    expected: Any = None
    actual: Any = None
    message: str = ""


@dataclass(frozen=True, slots=True)
class ValidationReport:
    run_id: str
    checks: tuple[ValidationCheck, ...] = field(default_factory=tuple)

    @property
    def passed(self) -> bool:
        return bool(self.checks) and all(check.passed for check in self.checks)

    def as_dict(self) -> Mapping[str, Any]:
        return {
            "run_id": self.run_id,
            "status": "pass" if self.passed else "fail",
            "checks": [
                {
                    "name": check.name,
                    "passed": check.passed,
                    "expected": check.expected,
                    "actual": check.actual,
                    "message": check.message,
                }
                for check in self.checks
            ],
        }
