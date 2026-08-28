# 모델링 분석

> 목적: 표준화된 통합 데이터를 품질검증하고 MySQL용 엔터티로 분리하는 근거를 기록한다.

## 1. 입력과 담당 경계

크롤링 원본은 MongoDB에 먼저 적재된다. `main.run_all()`은 `get_raw_data_from_mongoDB()`로 한 run의 원본 문서를 읽고, 각 문서의 `payload`와 `_ingest.run_id`를 표준화 입력으로 바꾼다. 그중 `accepted_candidate_row_list`만 최종 품질검증하며, 표준화 Rejected 목록은 전체 행 수 대사에 사용한다.

모델링·적재 담당자는 전달받은 값을 다시 보정하지 않고 다음 작업을 수행한다.

1. 필수값·도메인·중복·PK·FK·계층 품질검증
2. Manager·Area·Top Area 관계 검증과 분리
3. Final Accepted와 Rejected 판정, 사유와 검증 로그 작성
4. 표준화·최종 Rejected와 사유를 MongoDB의 단계별 컬렉션에 저장
5. 추적용 `run_id`를 붙인 Final Accepted 엔터티의 MySQL 적재 준비
6. MySQL DDL·View와 컬럼 계약을 대시보드 담당자에게 인계

현재 `run_all()`은 원본 조회부터 표준화·최종검증·결과 파일 생성·MySQL 적재·Manifest 상태 변경까지 실행한다. 대시보드 담당자는 이 저장소의 Python 모듈을 호출하지 않고 DB 서버에 직접 접속한다.

## 2. 데이터 Grain

- 표준화 입력 한 행: Area 한 건에 담당 Manager, Parent, Top 정보가 결합된 관측 행
- Manager Grain: 담당 직원 한 명
- Area Grain: 현재 업무영역 한 건
- Top Area Grain: Parent 또는 Top 기준정보 한 건

수집 메타데이터는 품질 결과의 원천 추적에 사용한다. 이 중 `run_id`는 각 RDB 행을 마지막으로 관측·갱신한 회차를 확인하기 위해 업무 테이블에도 저장한다.

## 3. 엔터티와 식별자

| 엔터티 | PK | 추적 컬럼 | 주요 속성 |
|---|---|---|---|
| Manager | `manager_id` | `run_id` | 이름, 부서명, 직위명, 입사일시, 활성 여부 |
| Area | `business_area_id` | `run_id` | 이름, 담당자, Parent ID, Top ID, 등록일시 |
| Top Area | `top_business_area_id` | `run_id` | 이름, Top 레벨, 등록일시 |

Manager는 여러 Area를 담당할 수 있다. Area 한 건은 Final Accepted에서 Manager 한 명, Top Area 한 건을 반드시 참조하고 Parent는 없을 수 있다.

## 4. Parent와 Top 모델링 근거

특정 시점의 프로파일링 스냅샷에서는 현재 Area ID 8,299개, Parent·Top ID 각각 999개가 확인됐으며 Parent와 Top의 ID 집합은 같다. 이 수치는 누적 파이프라인의 고정 계약값이 아니므로 실행할 때마다 다시 계산한다. 이 스냅샷에서 841개는 현재 Area PK로 등장하지 않고, Parent ID와 Top ID가 다른 행은 107개다.

841개는 누락 데이터가 아니라 Parent·Top 역할로만 등장한 기준정보다. 따라서 현재 Area PK에 없다는 이유만으로 Rejected 처리하지 않고 Top Area 기준 테이블로 추출한다.
Parent와 Top이 다른 107개 행을 잃지 않도록 Area에는 `parent_business_area_id`와 `top_business_area_id`를 모두 저장한다.

이 설계는 현재 데이터에서 Parent ID 집합과 Top ID 집합이 같다는 프로파일링 결과를 이용한 MVP다. 향후 중간 계층 ID가 Top 기준정보 집합 밖에 등장하면 Parent 전용 기준 테이블이나 Area 자기참조 구조를 다시 검토한다.

## 5. 관계

```text
AREA.manager_id
→ MANAGER.manager_id
```

```text
AREA.parent_business_area_id
→ TOP_AREA.top_business_area_id
```

```text
AREA.top_business_area_id
→ TOP_AREA.top_business_area_id
```

Parent FK는 선택 관계이고 Top FK는 필수 관계다.

## 6. 정규화 근거

이 문서의 정규화에는 두 의미가 있다. `src/normailization/normalization.py`는 표준화 Accepted 통합 행을 최종 검증하고 Manager·Area·Top Area로 분리하는 파이프라인 단계명이다. 1NF·2NF·3NF는 분리된 RDB 테이블의 중복과 종속성을 점검하는 데이터베이스 설계 규칙이다.

입력은 컬럼 하나에 값 하나만 가지므로 1NF를 충족한다. 분리 테이블은 모두 단일 PK를 사용하므로 복합키 일부에 의존하는 속성이 없어 2NF를 충족한다.

3NF 관점에서 Manager 속성은 Manager에, 현재 Area 속성은 Area에, Parent·Top 기준 속성은 Top Area에 한 번만 저장한다. `parent_business_area_name`은 저장하지 않고 Parent FK가 가리키는 Top Area 행의 이름을 조회한다.

## 7. 품질검증 기준

모델링·적재 담당자는 표준화 데이터를 다음 기준으로 판정한다.

- PK·필수 FK의 NULL과 형식 오류
- 동일 PK의 속성 충돌
- Manager·Top 기준정보의 필수 속성과 동일 ID 속성 일관성
- Parent ID가 추출된 Top 기준정보에 존재하는지 여부
- Top 판정 조건과 계층 모순
- 자료형·길이·허용값 위반

### 디스커션 1·2 적용 상태

- 중복 `business_area_id`: 같은 ID에서 서로 다른 유효 속성이 발견되면 해당 ID 그룹 전체를 Final Rejected로 판정하도록 구현했다. 빈 값이 있는 행은 필수값 검사에서 Rejected되고 유효값이 있는 행은 남을 수 있다.
- 등록일시 충돌: 표준화 이후 같은 ID에 서로 다른 유효 등록일시가 남아 있으면 해당 ID 그룹 전체를 Final Rejected로 판정하도록 구현했다. sentinel 변환 자체는 표준화 담당 범위다.
- 위 두 규칙은 `src/normailization/normalization.py`의 동일 ID 속성 충돌 검사에 포함했고 단위 테스트로 확인했다. 실제 Accepted 데이터에 대한 최종 호환성 검사는 아직 남아 있다.
- `schema.sql`은 위 판단을 대신하지 않고 잘못된 데이터의 INSERT를 마지막에 막는 안전장치다.

표준 사전의 `nullable=Y`는 표준화 Candidate에서 결측을 표현할 수 있다는 뜻이다. Final Accepted와 DDL은 업무 관리용 완전성을 더 엄격하게 적용해 `parent_business_area_id`만 NULL을 허용한다.

Top Area 기준정보 후보는 모든 행의 `top_*` 네 컬럼에서 추출하고 `top_business_area_id`로 중복 제거한다. 다음 세 조건은 현재 Area 자체가 Top 역할인지 확인할 때만 사용한다.

```text
parent_business_area_id IS NULL
AND business_area_id = top_business_area_id
AND top_business_area_level_code = 'TOP'
```

하위 Area는 현재 ID와 Top ID가 달라도 정상이다. 이 경우에도 해당 행의 `top_*` 값은 Top Area 기준정보 후보로 사용한다.

## 8. 판정 결과

```text
final_accepted.csv
final_rejected.csv
final_validation.json
```

`final_accepted.csv`와 `final_rejected.csv`는 표준화 Accepted와 같은 통합 행 Grain을 유지한다. `final_rejected.csv`에는 `rejection_reason` 컬럼 하나를 추가해 구체적인 실패 사유를 기록한다. `final_validation.json`에는 `run_id`, 단계별 건수, 보존식 결과와 사유별 건수를 기록한다.

```text
표준화 인계 기준 행 수
= standardization_result.rejected_row_count
 + final_result.final_accepted_row_count
 + final_result.final_rejected_row_count
```

MongoDB 원본과 표준화 결과의 대사는 `main.run_all()`이 원본 문서 수와 표준화 결과를 함께 가지고 검사한다. 각 count가 실제 list 길이와 같은지, `표준화 Accepted = Final Accepted + Final Rejected`인지, 세 결과의 합이 원본 행 수와 같은지 검사한다. 실행 중에는 `pipeline_run_summary=RUNNING`을 기록하고, MySQL UPSERT와 MongoDB Rejected 저장이 끝난 뒤 Manifest를 `processing → pass`로 바꾸면서 배치 요약을 `SUCCESS`로 갱신한다. 오류 시 요약에는 `FAILED` 또는 `PARTIAL_FAILURE`를 남긴다. 대시보드 화면 구현은 별도 담당 작업이다.

`final_accepted.csv`는 `manager`, `area`, `top_area`로 분리하고 같은 실행의 `run_id`를 각 행에 저장한다. 이후 UPSERT에 따라 관련 엔터티의 마지막 갱신 run은 서로 달라질 수 있으므로 대시보드 View는 업무 PK/FK로 조인하고 화면에서는 `run_id`를 제외한다.
