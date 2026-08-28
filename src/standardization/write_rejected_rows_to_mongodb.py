"""표준화/정규화 거부 행을 MongoDB rejected-data 저장소에 기록한다."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any


REQUIRED_ENVIRONMENT_VARIABLES = (
    "MONGO_URI",
    "MONGO_DATABASE",
    "MONGO_STANDARDIZATION_REJECTED_COLLECTION",
    "MONGO_NORMALIZATION_REJECTED_COLLECTION",
)


class RejectedMongoConfigurationError(RuntimeError):
    """MongoDB rejected-data 저장소 설정이 올바르지 않을 때 발생한다."""


class RejectedMongoDataError(RuntimeError):
    """저장할 거부 결과가 예상 스키마와 다를 때 발생한다."""


def _default_dotenv_path() -> Path:
    return Path(__file__).resolve().parents[2] / ".env"


def _environment_from_dotenv(dotenv_path: str | Path | None) -> Mapping[str, str]:
    path = Path(dotenv_path).resolve() if dotenv_path else _default_dotenv_path()
    if not path.is_file():
        raise RejectedMongoConfigurationError(f".env 파일이 없습니다: {path}")
    try:
        from dotenv import load_dotenv
    except ModuleNotFoundError as exc:
        raise RejectedMongoConfigurationError(
            "python-dotenv가 필요합니다. requirements.txt를 설치하세요."
        ) from exc
    load_dotenv(dotenv_path=path, override=False)
    return os.environ


def _validated_settings(environment: Mapping[str, str]) -> dict[str, str]:
    settings = {
        name: str(environment.get(name, "")).strip()
        for name in REQUIRED_ENVIRONMENT_VARIABLES
    }
    missing = [name for name, value in settings.items() if not value]
    if missing:
        raise RejectedMongoConfigurationError(
            "필수 MongoDB 환경변수가 없습니다: " + ", ".join(missing)
        )
    return settings


def _rejected_rows(
    result: Mapping[str, Any],
    *,
    result_name: str,
    row_keys: Sequence[str],
) -> list[dict[str, Any]]:

    if not isinstance(result, Mapping):
        raise RejectedMongoDataError(f"{result_name}는 객체여야 합니다.")
    run_id = result.get("run_id")
    if not isinstance(run_id, str) or not run_id.strip():
        raise RejectedMongoDataError(f"{result_name}에 유효한 run_id가 없습니다.")

    selected_key = next((key for key in row_keys if key in result), None)
    if selected_key is None:
        raise RejectedMongoDataError(
            f"{result_name}에 {', '.join(row_keys)} 중 하나가 필요합니다."
        )
    rows = result[selected_key]
    if not isinstance(rows, list):
        raise RejectedMongoDataError(f"{result_name}.{selected_key}는 list여야 합니다.")

    documents: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise RejectedMongoDataError(
                f"{result_name}.{selected_key}[{index}]는 객체여야 합니다."
            )

        errors = row.get("errors", [])
        if not isinstance(errors, list):
            raise RejectedMongoDataError(
                f"{result_name}.{selected_key}[{index}].errors는 list여야 합니다."
            )

        rejected_reasons: list[str] = []
        for error_index, error in enumerate(errors):
            if not isinstance(error, Mapping):
                raise RejectedMongoDataError(
                    f"{result_name}.{selected_key}[{index}].errors[{error_index}]는 "
                    "객체여야 합니다."
                )
            reason = error.get("reason")
            if reason is not None:
                rejected_reasons.append(str(reason))

        # dict 삽입 순서를 이용해 run_id는 첫 필드, rejected_reason은 마지막
        # 필드가 되게 한다. 호출자가 준 row는 변경하지 않는다.
        row_fields = {
            key: value
            for key, value in row.items()
            if key not in {"run_id", "rejected_reason"}
        }
        documents.append(
            {
                "run_id": run_id,
                **row_fields,
                "rejected_reason": rejected_reasons,
            }
        )
    return documents


def write_rejected_rows_to_mongodb(
    rejected_standardization_result: Mapping[str, Any],
    rejected_normalization_result: Mapping[str, Any],
    dotenv_path: str | Path | None = None,
    *,
    environment: Mapping[str, str] | None = None,
    mongo_client_factory: Callable[..., Any] | None = None,
) -> dict[str, int]:
    """표준화/정규화 거부 행을 각각 설정된 컬렉션에 저장한다.

    정규화 결과의 정식 키는 ``final_rejected_row_list``이다. 기존 호출부와의
    호환성을 위해 ``rejected_row_list``도 허용한다. 반환값은 컬렉션별 실제
    저장 문서 수다.
    """
    source_environment = (
        environment
        if environment is not None
        else _environment_from_dotenv(dotenv_path)
    )
    settings = _validated_settings(source_environment)

    standardization_documents = _rejected_rows(
        rejected_standardization_result,
        result_name="rejected_standardization_result",
        row_keys=("rejected_row_list",),
    )
    normalization_documents = _rejected_rows(
        rejected_normalization_result,
        result_name="rejected_normalization_result",
        row_keys=("final_rejected_row_list", "rejected_row_list"),
    )

    if mongo_client_factory is None:
        try:
            from pymongo import MongoClient
        except ModuleNotFoundError as exc:
            raise RejectedMongoConfigurationError(
                "pymongo가 필요합니다. requirements.txt를 설치하세요."
            ) from exc
        mongo_client_factory = MongoClient

    client = mongo_client_factory(settings["MONGO_URI"])
    try:
        # 실제 서버 연결 여부를 저장 전에 확인해 접속 실패를 즉시 드러낸다.
        client.admin.command("ping")
        database = client[settings["MONGO_DATABASE"]]
        collection_names = set(database.list_collection_names())
        required_collections = {
            settings["MONGO_STANDARDIZATION_REJECTED_COLLECTION"],
            settings["MONGO_NORMALIZATION_REJECTED_COLLECTION"],
        }
        missing_collections = sorted(required_collections - collection_names)
        if missing_collections:
            raise RejectedMongoConfigurationError(
                "MongoDB에 필수 rejected-data 컬렉션이 없습니다: "
                + ", ".join(missing_collections)
            )
        standardization_collection = database[
            settings["MONGO_STANDARDIZATION_REJECTED_COLLECTION"]
        ]
        normalization_collection = database[
            settings["MONGO_NORMALIZATION_REJECTED_COLLECTION"]
        ]

        standardization_count = 0
        normalization_count = 0
        if standardization_documents:
            result = standardization_collection.insert_many(
                standardization_documents, ordered=True
            )
            standardization_count = len(result.inserted_ids)
        if normalization_documents:
            result = normalization_collection.insert_many(
                normalization_documents, ordered=True
            )
            normalization_count = len(result.inserted_ids)

        return {
            "standardization_inserted_count": standardization_count,
            "normalization_inserted_count": normalization_count,
        }
    finally:
        client.close()


__all__ = [
    "RejectedMongoConfigurationError",
    "RejectedMongoDataError",
    "write_rejected_rows_to_mongodb",
]
