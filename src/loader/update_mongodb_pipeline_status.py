"""MongoDB Manifest의 pipeline_status를 갱신한다."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any


REQUIRED_ENVIRONMENT_VARIABLES = (
    "RAW_MONGO_URI",
    "RAW_MONGO_DATABASE",
    "MONGO_RAW_MANIFEST_COLLECTION",
)


class MongoPipelineStatusError(RuntimeError):
    """MongoDB Manifest 상태 변경에 실패했을 때 발생한다."""


def _default_dotenv_path() -> Path:
    """프로젝트 루트의 .env 경로를 반환한다."""
    return Path(__file__).resolve().parents[2] / ".env"


def _environment_from_dotenv(dotenv_path: str | Path | None) -> Mapping[str, str]:
    """.env를 읽고 현재 프로세스 환경변수를 반환한다."""
    path = Path(dotenv_path).resolve() if dotenv_path else _default_dotenv_path()
    if not path.is_file():
        raise MongoPipelineStatusError(f".env 파일이 없습니다: {path}")

    try:
        from dotenv import load_dotenv
    except ModuleNotFoundError as exc:
        raise MongoPipelineStatusError(
            "python-dotenv가 필요합니다. requirements.txt를 설치하세요."
        ) from exc

    load_dotenv(dotenv_path=path, override=False)
    return os.environ


def _validated_settings(environment: Mapping[str, str]) -> dict[str, str]:
    """상태 변경에 필요한 MongoDB 환경변수를 확인한다."""
    settings = {
        name: str(environment.get(name, "")).strip()
        for name in REQUIRED_ENVIRONMENT_VARIABLES
    }
    missing = [name for name, value in settings.items() if not value]
    if missing:
        raise MongoPipelineStatusError(
            "필수 MongoDB 환경변수가 없습니다: " + ", ".join(missing)
        )
    return settings


def update_pipeline_status(
    run_id: str,
    status: str = "pass",
    dotenv_path: str | Path | None = None,
    *,
    environment: Mapping[str, str] | None = None,
    mongo_client_factory: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    """지정한 run_id의 Manifest pipeline_status를 변경한다."""
    if not isinstance(run_id, str) or not run_id.strip():
        raise MongoPipelineStatusError("pipeline 상태를 바꿀 run_id가 비어 있습니다.")
    if status not in {"pending", "processing", "pass", "failed"}:
        raise MongoPipelineStatusError(
            f"허용되지 않은 pipeline_status입니다: {status}"
        )

    source_environment = (
        environment
        if environment is not None
        else _environment_from_dotenv(dotenv_path)
    )
    settings = _validated_settings(source_environment)

    if mongo_client_factory is None:
        try:
            from pymongo import MongoClient
        except ModuleNotFoundError as exc:
            raise MongoPipelineStatusError(
                "pymongo가 필요합니다. requirements.txt를 설치하세요."
            ) from exc
        mongo_client_factory = MongoClient

    client = mongo_client_factory(settings["RAW_MONGO_URI"])
    try:
        collection = client[settings["RAW_MONGO_DATABASE"]][
            settings["MONGO_RAW_MANIFEST_COLLECTION"]
        ]
        result = collection.update_one(
            {"run_id": run_id},
            {"$set": {"pipeline_status": status}},
        )
        if result.matched_count != 1:
            raise MongoPipelineStatusError(
                f"run_id={run_id} Manifest를 하나 찾지 못했습니다."
            )

        return {
            "run_id": run_id,
            "pipeline_status": status,
            "matched_count": result.matched_count,
            "modified_count": result.modified_count,
        }
    finally:
        client.close()


__all__ = ["MongoPipelineStatusError", "update_pipeline_status"]
