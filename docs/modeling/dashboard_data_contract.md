# 대시보드 데이터 계약

## 책임 경계

DB·ETL 파이프라인은 표준화/최종검증 건수, MySQL 엔터티 목표·적재 건수, 실행 상태를 MySQL에 기록하고 두 단계의 Rejected 행을 MongoDB에 저장한다. 대시보드 담당자는 자신의 Django repository에서 두 DB를 읽어 KPI와 반려 사유 집계를 계산한다. 이 저장소는 Django API·context·화면을 제공하지 않는다.

## MySQL 조회 대상

### `dashboard_area_view`

현재 최종 Accepted 업무 데이터를 조회한다. `run_id`는 화면용 컬럼에서 숨기고, 표준 업무 컬럼 15개는 모두 제공한다. 테이블에 중복 저장하지 않은 `parent_business_area_name`은 `parent_business_area_id`로 `top_area`를 `LEFT JOIN`해 복원한다.

### `dashboard_pipeline_run_view`

`pipeline_run_summary`의 배치별 사실값을 조회한다.

| 사실값 | 의미 |
|---|---|
| `raw_row_count` | 해당 `run_id`의 원본 입력 행 수 |
| `standardization_accepted_count` / `standardization_rejected_count` | 표준화 단계의 Accepted Candidate / Rejected 수 |
| `final_accepted_count` / `final_rejected_count` | 최종 관계검증의 Accepted / Rejected 수 |
| `manager_target_count`, `top_area_target_count`, `area_target_count` | 이번 배치에서 PK 중복 제거 후 적재할 엔터티 수 |
| `manager_loaded_count`, `top_area_loaded_count`, `area_loaded_count` | UPSERT 성공 엔터티 수 |
| `batch_status` | `RUNNING`, `SUCCESS`, `PARTIAL_FAILURE`, `FAILED` |
| `started_at`, `completed_at` | 실행 시작·종료 시각 |
| `error_message` | 실패 원인 |

대시보드 담당자는 별도 Django repository에서 다음처럼 View를 직접 조회한다.

```sql
SELECT *
FROM dashboard_pipeline_run_view
ORDER BY started_at DESC;

SELECT *
FROM dashboard_area_view
ORDER BY business_area_id;
```

## KPI 계산식

분모가 0이면 0% 또는 `N/A` 중 하나로 화면 정책을 정해 일관되게 표시한다.

```text
표준화 Accepted율
= standardization_accepted_count / raw_row_count * 100

표준화 Rejected율
= standardization_rejected_count / raw_row_count * 100

최종 Accepted율(표준화 Accepted 기준)
= final_accepted_count / standardization_accepted_count * 100

manager 적재율
= manager_loaded_count / manager_target_count * 100

top_area 적재율
= top_area_loaded_count / top_area_target_count * 100

area 적재율
= area_loaded_count / area_target_count * 100
```

`final_accepted_count`와 MySQL `area_loaded_count`를 직접 같은 의미로 표시하지 않는다. 통합 행에서 PK별 엔터티를 중복 제거하기 때문에 하나의 Final Accepted 행 수와 실제 RDB 엔터티 수는 다를 수 있다.

## 화면 매핑

| 화면 카드/표 | 데이터 원천 |
|---|---|
| 전체 수집량 | MySQL `raw_row_count` 또는 MongoDB 원본 count |
| 단계별 Accepted/Rejected | MySQL `dashboard_pipeline_run_view`의 단계별 count |
| 테이블별 적재 건수·적재율 | `*_target_count`, `*_loaded_count`와 위 KPI 식 |
| 최근 적재 시각 | `completed_at` 또는 세 테이블의 최신 `run_id` 기준 시각 정책 |
| 배치 성공/실패 | `batch_status`와 `error_message` |
| 반려 사유별 집계·최근 반려 문서 | 이 파이프라인이 저장한 MongoDB Rejected 컬렉션 |

MySQL 데이터는 읽기 전용 계정으로 조회한다. Django Model로 View를 매핑할 때는 대시보드 담당자의 repository에서 `managed = False`와 실제 View명(`dashboard_area_view`, `dashboard_pipeline_run_view`)을 사용한다. 이 저장소에서 대시보드용 Python loader나 JSON 전달 코드를 실행하지 않는다.
