# run_id와 실패 상태 처리

`run_id`는 업무 PK가 아니라 각 크롤링 회차를 식별하는 값이다. 세 업무 테이블에는 마지막으로 해당 엔터티를 갱신한 `run_id`를 저장하고, `pipeline_run_summary`에는 회차 전체의 처리 사실값과 상태를 저장한다.

## 처리 순서

```text
MongoDB 원본 조회
→ pipeline_run_summary = RUNNING
→ Manifest pipeline_status = processing
→ 표준화·정규화와 행 수 보존식 PASS
→ Final Accepted를 MySQL에 run_id와 함께 UPSERT
→ MySQL commit
→ 표준화·정규화 Rejected를 단계별 MongoDB 컬렉션에 저장
→ Manifest pipeline_status = pass
→ pipeline_run_summary = SUCCESS
```

실행 중 오류가 나면 `pipeline_run_summary`의 상태를 `FAILED` 또는 `PARTIAL_FAILURE`로 갱신하고 오류 메시지를 남긴다. MySQL 세 업무 테이블 UPSERT는 하나의 트랜잭션이므로 중간 실패 시 `rollback()`한다.

## 원자성의 범위

MongoDB와 MySQL은 서로 다른 DB이므로 하나의 ACID 트랜잭션이 아니다. 이 저장소가 보장하는 범위는 다음과 같다.

| 구간 | 보장 |
|---|---|
| MySQL `manager`·`top_area`·`area` | 하나의 트랜잭션으로 성공 또는 전체 rollback |
| MySQL `pipeline_run_summary` | `run_id` PK 기준 멱등 UPSERT |
| Manifest 상태 | MySQL commit 이후 `pass`, 오류 시 `failed`를 best-effort 반영 |
| MongoDB Rejected 컬렉션 | 같은 `run_id`의 기존 문서를 지우고 현재 결과로 교체하여 재실행 중복 방지 |

따라서 `pipeline_run_summary.SUCCESS`는 표준화·최종검증·MySQL 적재·MongoDB Rejected 저장·Manifest 상태 변경이 모두 끝났다는 뜻이다. Rejected 저장이 MySQL commit 뒤에 실패하면 MySQL까지 자동으로 되돌릴 수는 없으므로 `PARTIAL_FAILURE`와 Manifest `failed`를 기록한다. 같은 `run_id`를 다시 pending으로 전환해 재실행하면 MySQL은 UPSERT하고 Rejected 컬렉션은 해당 run 결과로 교체한다.

## 재실행

같은 `run_id`로 재실행하면 업무 테이블과 요약 테이블 모두 UPSERT하므로 중복 행이 생기지 않는다. Manifest가 `failed`인 run을 다시 처리하려면 MongoDB 담당자가 해당 run을 재처리 가능한 상태로 되돌린 뒤 실행한다.
