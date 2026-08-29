"""MongoDB Bronze 저장소에서 표준화 대상 원본 문서를 조회한다.

이 모듈은 표준화·정규화 함수와 연결되지 않는 독립 조회 모듈이다.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable, Mapping
from dotenv import load_dotenv
from pymongo import MongoClient

REQUIRED_ENVIRONMENT_VARIABLES = (
    "RAW_MONGO_URI",
    "RAW_MONGO_DATABASE",
    "MONGO_RAW_DATA_COLLECTION",
    "MONGO_RAW_MANIFEST_COLLECTION",
)

class RawMongoConfigurationError(RuntimeError):
    """MongoDB 접속 환경변수가 준비되지 않았을 때 발생한다."""


class RawMongoDataError(RuntimeError):
    """조회한 MongoDB 문서가 예상 스키마와 다를 때 발생한다."""

def _environment_from_dotenv() -> Mapping[str, str]:
    path = Path(__file__).resolve().parents[2] / ".env"
    load_dotenv(dotenv_path=path, override=False)
    return os.environ


def _validated_settings(environment: Mapping[str, str]) -> dict[str, str]:
    settings = {
        name: str(environment.get(name, "")).strip()
        for name in REQUIRED_ENVIRONMENT_VARIABLES
    }
    missing = [name for name, value in settings.items() if not value]
    if missing:
        raise RawMongoConfigurationError(
            "필수 MongoDB 환경변수가 없습니다: " + ", ".join(missing)
        )
    return settings


def get_raw_data_from_mongoDB() -> list[dict[str, Any]]:
    """pending 중 실제 raw record가 존재하는 첫 run의 문서 전체를 반환한다.

    기본 실행에서는 프로젝트 루트의 ``.env``를 읽고 PyMongo로 접속한다.
    ``environment``와 ``mongo_client_factory``는 MongoDB에 연결하지 않는 단위
    테스트를 위한 선택적 의존성 주입 지점이다.

    처리 순서:
      1. ``pipeline_status == 'pending'`` manifest를 ``_id`` 오름차순으로 조회
      2. ``legacy_records._ingest.run_id``가 실제 존재하는 첫 manifest 선택
      3. 선택한 run의 문서를 ``source_row_no``, ``_id`` 오름차순으로 조회
      4. 조회 전·후 행 수가 같을 때 원본 문서 전체를 ``list[dict]``로 반환

    pending manifest 또는 일치하는 raw record가 없으면 빈 리스트를 반환한다.
    조회 도중 수집기가 run_id를 교체하면 최대 3회 다시 선택한다. MongoDB
    상태는 변경하지 않는다.
    """
    source_environment = _environment_from_dotenv() # .env 읽어서 os.environ 반환
    settings = _validated_settings(source_environment) # os.environ으로부터 환경변수 읽어서 필요한게 하나라도 없으면 except
    mongo_client_factory = MongoClient # mongo client 객체 생성

    client = mongo_client_factory(settings["RAW_MONGO_URI"]) # raw mongodb에 연결 시도

    try:
        database = client[settings["RAW_MONGO_DATABASE"]]
        manifest_collection = database[settings["MONGO_RAW_MANIFEST_COLLECTION"]]
        raw_data_collection = database[settings["MONGO_RAW_DATA_COLLECTION"]]

        for attempt in range(3):
            manifests = list( # crawl_manifest collection에서 pipiline_status:pending인 것들 _id값 순으로 정렬
                manifest_collection.find(
                    {"pipeline_status": "pending"},
                    {"_id": 1, "run_id": 1},
                ).sort([("_id", 1)])
            )
            if not manifests:
                return []

            pending_run_ids: list[str] = []
            for manifest in manifests:
                run_id = manifest.get("run_id") # pending되어있는 manifest에서 run_id만 얻어서 list로 생성
                pending_run_ids.append(run_id)

            existing_run_ids = set(
                raw_data_collection.distinct( # 위에서 생성한 run_id list에 매칭되는 raw_data있는지 체크
                    "_ingest.run_id",
                    {"_ingest.run_id": {"$in": pending_run_ids}},
                )
            )
            # 즉, selected_run_id는 우리가 타게팅할 단 하나의 run_id값임.
            selected_run_id = next(
                (run_id for run_id in pending_run_ids if run_id in existing_run_ids),
                None,
            ) # 매칭되는 run_id 단 하나만 가져옴
            if selected_run_id is None:
                return []

            query = {"_ingest.run_id": selected_run_id}
            count_before = raw_data_collection.count_documents(query)
            documents = list( # 타겟한 run_id를 대상으로 raw_data bulk로 가져옴
                raw_data_collection.find(query).sort(
                    [("source_row_no", 1), ("_id", 1)]
                )
            )
            count_after = raw_data_collection.count_documents(query)

			# race condition 발생을 체크하는 로직. find할 때 소요되는 시간이 있으니까 그 작업 중에 혹시
            # 데이터 변경이 생길 수 있으므로 체크
            if count_before == len(documents) == count_after and count_after > 0:
                return [dict(document) for document in documents]

            if attempt == 2:
                raise RawMongoDataError(
                    "조회 중 legacy_records의 run_id가 계속 변경되어 안정적인 "
                    "payload 묶음을 만들 수 없습니다."
                )

        raise RawMongoDataError("raw payload 조회 재시도 한도를 초과했습니다.")
    finally:
        client.close()

# Python 관례에 맞는 별칭도 제공하되, 요청된 함수 이름을 그대로 유지한다.
get_raw_data_from_mongodb = get_raw_data_from_mongoDB

__all__ = [
    "RawMongoConfigurationError",
    "RawMongoDataError",
    "get_raw_data_from_mongoDB",
    "get_raw_data_from_mongodb",
]
