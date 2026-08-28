# MongoDB–Silver 인수 계약

> 목적: MongoDB 원본부터 표준화·최종검증·적재까지 단계 사이의 입력과 출력을 고정한다.

## 1. 원본 소비 gate

`get_raw_data_from_mongoDB()`는 raw 문서가 실제로 존재하는 `pending` Manifest를 찾고 다음 조건을 검사한다.

```text
Manifest.status = success
Manifest.mongodb_validation_status = pass
Manifest.pipeline_status = pending
Manifest.run_id = 모든 legacy_records._ingest.run_id
legacy_records._ingest.source_name = biz_legacy_integrated
record_id 결측·중복 = 0건
Manifest.row_count = 실제 조회 문서 수
```

하나라도 다르면 표준화를 시작하지 않는다. 실행을 시작하면 `main.run_all()`이 Manifest를 `processing`으로 변경한다.

## 2. MongoDB 원본 구조

조회 함수는 MongoDB 문서 전체를 `list[dict]`로 반환한다.

```text
payload               표준화 대상 업무 컬럼 한 행
_ingest.run_id        수집·실행 회차
_ingest.collected_at  수집 시각
```

`main.run_all()`은 한 실행에 하나의 `run_id`만 있는지 확인하고 `payload` 목록을 표준화 입력으로 만든다.

## 3. 표준화 반환 계약

표준화 이후 다음 다섯 값만 다음 단계로 넘긴다.

```python
{
    "run_id": run_id,
    "accepted_candidate_row_count": n,
    "rejected_row_count": m,
    "accepted_candidate_row_list": [...],
    "rejected_row_list": [...],
}
```

두 count는 각 list의 실제 길이와 같아야 한다.

## 4. Accepted Candidate 업무 컬럼

| 그룹 | 컬럼 |
|---|---|
| Manager | `manager_id`, `manager_name`, `manager_department_name`, `manager_position_name`, `manager_hire_datetime`, `manager_active_yn` |
| Area | `business_area_id`, `business_area_name`, `parent_business_area_id`, `business_area_registration_datetime` |
| Top Area | `top_business_area_id`, `top_business_area_name`, `top_business_area_level_code`, `top_business_area_registration_datetime` |

`parent_business_area_name`은 검증용으로 전달하지만 MySQL에는 저장하지 않는다.

## 5. 최종검증과 출력

`run_normalization()`은 표준화 Accepted Candidate만 다음 기준으로 검사한다.

- 필수값, ID 형식, 날짜 형식, 허용 코드
- 동일 Area·Manager·Top ID의 속성 충돌
- Parent·Top 관계와 Final Accepted 기준 FK 대상 존재 여부

출력은 다음 다섯 값이다.

```python
{
    "run_id": run_id,
    "final_accepted_row_count": x,
    "final_rejected_row_count": y,
    "final_accepted_row_list": [...],
    "final_rejected_row_list": [...],
}
```

Final Rejected에는 `rejection_reason`을 추가한다. 같은 결과를 `final_accepted.csv`, `final_rejected.csv`, `final_validation.json`으로 저장한다.

## 6. 행 수 보존식

```text
MongoDB 원본 = 표준화 Accepted + 표준화 Rejected
표준화 Accepted = Final Accepted + Final Rejected
MongoDB 원본 = 표준화 Rejected + Final Accepted + Final Rejected
```

세 식이 모두 맞아야 적재한다.

## 7. 적재 계약

1. Final Accepted를 `manager → top_area → area` 순서로 MySQL UPSERT한다.
2. 세 업무 테이블은 하나의 MySQL 트랜잭션으로 처리한다.
3. 표준화·최종 Rejected를 MongoDB의 두 컬렉션에 `run_id` 기준으로 교체 저장한다.
4. 모든 작업이 끝나면 Manifest를 `pass`, 배치 요약을 `SUCCESS`로 변경한다.
5. 오류가 나면 배치 요약에 `FAILED` 또는 `PARTIAL_FAILURE`, Manifest에 `failed`를 기록한다.

MongoDB와 MySQL은 하나의 ACID 트랜잭션이 아니다. MySQL 내부 실패만 전체 rollback하며, MySQL commit 뒤 MongoDB 저장이 실패하면 같은 `run_id`를 다시 pending으로 전환해 멱등 재실행한다.

## 8. 환경변수

- Raw MongoDB: `RAW_MONGO_URI`, `RAW_MONGO_DATABASE`, `MONGO_RAW_DATA_COLLECTION`, `MONGO_RAW_MANIFEST_COLLECTION`
- Rejected MongoDB: `MONGO_URI`, `MONGO_DATABASE`, `MONGO_STANDARDIZATION_REJECTED_COLLECTION`, `MONGO_NORMALIZATION_REJECTED_COLLECTION`
- MySQL: `DB1_NAME`, `DB1_USER`, `DB1_PASSWORD`, `DB1_HOST`, `DB1_PORT`
