# Final Accepted 물리 모델

> 목적: 품질검증을 통과한 Final Accepted를 MySQL에 적재하기 위한 물리 구조를 정의한다.

[물리 ERD PNG](normalized_silver_physical_erd.png)

> 주의: 위 PNG는 `SILVER_*` 테이블명과 `run_id` 추가 전의 초기 초안이다. 현재 물리 모델의 정본은 아래 표와 `src/schema/schema.sql`이며, ERD 이미지는 별도 수정 요청이 있을 때 갱신한다.

## 1. 테이블 구성

### manager — 7개 컬럼

| 컬럼 | 자료형 | 키 | NULL |
|---|---|---|---|
| `manager_id` | `VARCHAR(9)` | PK | N |
| `run_id` | `VARCHAR(100)` | INDEX | N |
| `manager_name` | `VARCHAR(100)` |  | N |
| `manager_department_name` | `VARCHAR(100)` |  | N |
| `manager_position_name` | `VARCHAR(10)` |  | N |
| `manager_hire_datetime` | `DATETIME` |  | N |
| `manager_active_yn` | `CHAR(1)` | CHECK `Y/N` | N |

### top_area — 5개 컬럼

| 컬럼 | 자료형 | 키 | NULL |
|---|---|---|---|
| `top_business_area_id` | `VARCHAR(9)` | PK | N |
| `run_id` | `VARCHAR(100)` | INDEX | N |
| `top_business_area_name` | `VARCHAR(100)` |  | N |
| `top_business_area_level_code` | `VARCHAR(3)` | CHECK `TOP` | N |
| `top_business_area_registration_datetime` | `DATETIME` |  | N |

### area — 7개 컬럼

| 컬럼 | 자료형 | 키 | NULL |
|---|---|---|---|
| `business_area_id` | `VARCHAR(9)` | PK | N |
| `run_id` | `VARCHAR(100)` | INDEX | N |
| `business_area_name` | `VARCHAR(100)` |  | N |
| `manager_id` | `VARCHAR(9)` | FK → Manager | N |
| `parent_business_area_id` | `VARCHAR(9)` | FK → Top Area | Y |
| `top_business_area_id` | `VARCHAR(9)` | FK → Top Area | N |
| `business_area_registration_datetime` | `DATETIME` |  | N |

### pipeline_run_summary — 배치 실행 사실값

`run_id`별로 파이프라인이 어디까지 처리됐는지와 대시보드가 계산에 사용할 원시 건수를 저장한다. 비율·상태 문구 같은 표현용 KPI는 Django service가 계산한다.

| 컬럼 | 의미 |
|---|---|
| `run_id` | 실행 회차 PK |
| `raw_row_count` | Mongo 원본 입력 행 수 |
| `standardization_accepted_count` / `standardization_rejected_count` | 표준화 단계 Accepted Candidate / Rejected 행 수 |
| `final_accepted_count` / `final_rejected_count` | 최종 관계검증 Accepted / Rejected 행 수 |
| `*_target_count` | 이번 Final Accepted에서 PK 중복 제거 후 MySQL에 반영할 엔터티 수 |
| `*_loaded_count` | MySQL UPSERT 성공 처리한 엔터티 수 |
| `started_at` / `completed_at` | 배치 시작·종료 시각 |
| `batch_status` | `RUNNING`, `SUCCESS`, `PARTIAL_FAILURE`, `FAILED` |
| `error_message` | 기술 실패 시 오류 메시지 |

업무 컬럼은 16개이고 세 테이블에 추적용 `run_id`가 하나씩 추가되어 물리 컬럼 수는 `7 + 5 + 7 = 19개`다. `run_id`는 업무 PK가 아니라 크롤링 회차와 마지막 갱신 run을 추적하는 데 사용한다.

## 2. FK와 카디널리티

| 관계 | 카디널리티 |
|---|---|
| Manager 1 — 0..N Area | Manager는 Area가 없을 수 있고 Area는 Manager 한 명을 반드시 참조 |
| Top Area 1 — 0..N Area(Parent) | Area의 Parent는 없거나 한 건 |
| Top Area 1 — 0..N Area(Top) | Area는 Top Area 한 건을 반드시 참조 |

삭제 정책은 세 FK 모두 `RESTRICT`를 기본으로 한다.

Parent가 `top_area`를 참조하는 구조는 현재 데이터에서 Parent ID와 Top 기준 ID 집합이 같다는 프로파일링 결과를 사용한 MVP다. 향후 중간 계층이 별도 ID 집합으로 들어오면 Parent 전용 기준 테이블 또는 Area 자기참조로 확장한다.

## 3. 제약조건

- PK는 NULL·중복을 허용하지 않는다.
- `manager_id`와 `top_business_area_id`는 필수 FK다.
- `parent_business_area_id`만 NULL을 허용한다.
- `manager_active_yn`은 `Y`, `N`만 허용한다.
- `top_business_area_level_code`는 `TOP`만 허용한다.
- 품질검증을 통과한 Final Accepted만 UPSERT한다.
- 표준 사전의 nullable은 Candidate 단계 기준이고, 이 DDL은 Final Accepted 기준이라 Parent ID 외에는 더 엄격하게 `NOT NULL`을 적용한다.
- DDL은 정제 기능이 아니라 최종 무결성 안전장치다.
- DDL은 중복 ID의 대표 행을 고르거나 등록일시 충돌을 해결하지 않는다. 해당 판정은 `src/normailization/normalization.py`에서 끝내야 한다.

## 4. 인덱스

PK 인덱스는 MySQL이 자동 생성한다. 추가 인덱스는 조회에 사용하는 FK 세 개와 추적용 `run_id`에만 우선 적용한다.

```text
area(manager_id)
area(parent_business_area_id)
area(top_business_area_id)
manager(run_id)
top_area(run_id)
area(run_id)
```

## 5. 생성·적재 순서

FK 대상을 먼저 만들기 위해 다음 순서를 사용한다.

```text
1. manager
2. top_area
3. area
4. pipeline_run_summary 상태·사실값
```

세 테이블 적재는 하나의 MySQL 트랜잭션으로 묶는다. 로그용 메타데이터 중 `run_id`만 세 테이블에 저장하고 나머지는 `final_validation.json`에 남긴다. 통합 행을 PK 기준 엔터티로 분리·중복 제거하므로 RDB 행 수는 `final_accepted.csv` 행 수와 직접 비교하지 않는다.

`src/loader/mysql_loader.py`는 Final Accepted 목록에서 PK별 행을 한 번씩 추출하고 같은 `run_id`를 붙여 위 순서로 UPSERT한다. 처음 보는 PK는 INSERT하고 기존 PK는 정상 최신 값과 `run_id`로 UPDATE한다. 세 테이블 중 하나라도 실패하면 MySQL 트랜잭션을 `rollback()`한다.

`pipeline_run_summary`는 `run_id`를 PK로 사용해 RUNNING 행을 먼저 만들고 같은 행을 SUCCESS·FAILED·PARTIAL_FAILURE로 UPSERT한다. `manager_target_count`와 `manager_loaded_count`처럼 엔터티별 건수를 별도로 두는 이유는 통합 원본 행 수와 RDB 엔터티 수가 같지 않을 수 있기 때문이다.

같은 run 내부의 PK 중복은 이미 최종 품질검증에서 처리한다. 속성이 같으면 한 엔터티로 중복 제거하고 속성이 다르면 Final Rejected로 보낸다. 다른 run에서 같은 업무 ID가 다시 수집되면 오류로 보지 않고 팀이 정한 반복 관측 규칙에 따라 UPSERT한다. RDB는 최신 정상 상태를 보관하고 원본 run 이력은 MongoDB에 보존한다.

## 6. 외부 대시보드 DB 접속 계약

`dashboard_area_view`는 업무 PK/FK인 `manager_id`, `parent_business_area_id`, `top_business_area_id`로 조인하고 SELECT 결과에는 `run_id`를 포함하지 않는다. 정규화로 저장하지 않은 `parent_business_area_name`은 Parent FK가 가리키는 `top_area`에서 복원한다. 각 테이블의 `run_id`는 마지막 갱신 회차라 서로 다를 수 있으므로 View의 조인 조건으로 사용하지 않는다. 이 저장소는 Django 앱·API·Template을 구현하지 않는다. 대시보드 담당자는 자신의 Django repository에서 MySQL 서버에 직접 접속해 이 View와 `dashboard_pipeline_run_view`를 SELECT한다. Django Model로 매핑할 경우에만 담당자가 실제 View명에 `db_table`을 지정하고 `managed = False`를 사용한다.

신규 또는 필요한 컬럼이 이미 준비된 DB에는 프로젝트 루트에서 아래 명령으로 전체 DDL과 View를 반영한다. `CREATE TABLE IF NOT EXISTS`와 `CREATE OR REPLACE VIEW`를 사용하므로 기존 테이블과 데이터는 삭제하지 않는다.

```powershell
python -c "from src.loader.mysql_loader import connect_mysql, apply_schema; c=connect_mysql(); apply_schema(c, r'src/schema/schema.sql'); c.close()"
```

기존 테이블에 `run_id`나 `pipeline_run_summary`가 아직 없다면 이 통합 파일을 실행하기 전에 DB 담당자가 현재 구조에 맞는 ALTER 작업을 별도로 확인해야 한다.
