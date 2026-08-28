# PRD — DX 전환을 위한 조직·구성원 데이터 표준화 및 품질 진단

> - 상태: 초안 v0.4
> - 기준 문서: BRD v0.4, 데이터 표준화 및 AI Ready Data 구축 프로젝트 가이드, AS-IS/TO-BE 분석 세부 작업 리스트
> - 대상 기간: 2026-08-27 ~ 2026-08-28
> - 범위: Medallion 아키텍처의 Bronze·Silver·Gold 논리 레이어 및 결과 조회 서비스
> - 제외: AI 모델 학습·추론·추천, 근거 없는 자동 보정 및 Gold 외 분석 마트 확장
> - 문서 유형: 제품 요구사항·산출물·수용 기준 명세

## 1. 제품 개요

### 1.1 제품 목표

본 제품은 레거시 조직·구성원 데이터를 회차별로 원본 보존(Bronze)하고 합의된 표준 사전과 품질 규칙으로 표준화·1차 검증한다. 1차 검증을 통과한 데이터를 To-Be 엔터티로 분리·정규화하고 관계 무결성까지 검증하여 DX 전환에 사용할 수 있는 Final Accepted 데이터와 개선이 필요한 Rejected 데이터로 구분해 제공한다. 이후 Silver `Final Accepted`를 담당자 단위 Gold 분석 피처로 재구성하여 반복 집계와 대시보드 조회의 공통 결과로 제공한다.

제품은 원천값의 업무적 사실성을 추정하거나 임의로 수정하지 않는다. 근거가 있는 표현·형식 차이만 표준화하며, 기본 품질 오류는 `REJECTED_STANDARDIZATION`, 엔터티 추출·PK·FK·관계 오류는 `REJECTED_RELATIONSHIP`으로 구분하여 품질 이슈와 함께 남긴다.

Gold는 Silver를 다시 정제하는 계층이 아니다. Silver의 정규화된 상세 원장을 입력으로 하여 실행 회차별 담당자 지표를 계산하고, 계산 기준과 계보를 함께 보존한다.

### 1.2 사용자와 해결 과제

| 사용자 | 해결할 과제 | 제공 결과 |
| --- | --- | --- |
| DX 전환 담당자 | 전환 가능한 데이터 범위와 개선 우선순위 판단 | Accepted Candidate·Final Accepted·Rejected 비율, 단계별 이슈 분포 |
| 조직·인사 데이터 담당자 | 표준명·도메인·관계에 대한 합의와 검토 | 표준 사전, Legacy→표준 매핑, 검증 근거 |
| 데이터·IT 운영 담당자 | 원천부터 결과까지 재현 가능한 실행 관리 | Bronze 원본, 매니페스트, 실행·검증·계보 로그 |
| 내부 검토 사용자 | 표준 데이터와 단계별 오류 데이터를 구분하여 조회 | Django 조회 화면, RDB Final Accepted, MongoDB 품질 이슈 |
| 분석·대시보드 담당자 | 담당자별 관리 범위와 조직 계층 지표를 일관되게 조회 | Gold 담당자 피처 테이블, 최신 성공 회차 View |

### 1.3 성공 기준

Accepted Candidate 비율과 Final Accepted 비율은 원천 품질과 To-Be 모델 적합성을 보여주는 진단값이며 성공 목표가 아니다. 제품 성공은 다음 기준으로 판단한다.

| 지표 | 목표 |
| --- | ---: |
| 공식 CSV 4종 기준선 재현율 | 100% |
| Bronze 원본 데이터·매니페스트 필수 항목 완전성 | 100% |
| Silver 입력의 `ACCEPTED_CANDIDATE` 또는 `REJECTED_STANDARDIZATION` 판정률 | 100% |
| 엔터티 후보의 Final Accepted 또는 모델·관계 Rejected 판정률 | 100% |
| Final Accepted의 표준·정규화·관계 규칙 준수율 | 100% |
| Rejected 이슈의 원본·필드·관계·규칙·사유 추적률 | 100% |
| 최종 결과의 원천 실행 역추적률 | 100% |
| 미분류 오류 비율 | 0% |
| Gold 입력의 Silver Final Accepted 유래율 | 100% |
| Gold `(run_id, manager_id)` 중복률 | 0% |
| Gold 피처 재계산 정합성 | 100% |
| Gold 행의 실행 시각·계보·피처 버전 완전성 | 100% |

## 2. 범위 및 입력 데이터

### 2.1 범위

#### In-Scope

- 공식 CSV 4종의 인벤토리, AS-IS 프로파일링 및 품질 기준선
- 프로젝트 기간 동안 합의된 웹 원천의 3분 간격 반복 수집
- 회차별 원본 데이터·매니페스트를 포함하는 Bronze 저장
- 16개 고유 필드에 대한 표준 단어·용어·도메인·명명·매핑 규칙
- Silver 표준화, 1차 품질 검증, `ACCEPTED_CANDIDATE`·`REJECTED_STANDARDIZATION` 판정
- Accepted Candidate의 To-Be 엔터티 분리·정규화 및 관계 무결성 검증
- Final Accepted 엔터티의 RDB 적재와 단계별 Rejected·이슈의 MongoDB 적재
- Silver `Final Accepted`를 기반으로 한 Gold 담당자 분석 피처 생성·검증·RDB 적재
- 실행 회차별 Gold 이력과 최신 `SUCCESS` 회차 Gold 조회 View 제공
- Django 기반 결과 조회, 실행 로그·검증 결과·계보 제공

#### Out-of-Scope

사업 범위 제외 항목은 BRD의 `6.2 Out-of-Scope`를 따르며, 다음 구현은 현재 제품 범위에 포함하지 않는다.

- 근거 없는 값 보정, 수정 후보 추천 및 사용자 승인 워크플로
- AI 모델 학습·추론·추천, Gold 피처 외 별도 분석 마트 확장
- 원천 시스템 자동 반영, 실시간 양방향 연동 및 상시 운영·고가용성
- 프로젝트 중 원천 스키마 변화에 따른 규칙 자동 재설계

### 2.2 공식 입력 데이터 계약

다음 CSV 4종을 표준 사전 구축과 품질 검증의 공식 기준 입력으로 사용한다.

| 원천 파일 | 기준 행 수 | 컬럼 수 | 처리 목적 |
| --- | ---: | ---: | --- |
| `biz_employee_master.csv` | 3,000 | 6 | 직원 마스터와 관리자 참조 검증 |
| `biz_meta_area_50000.csv` | 50,000 | 5 | 업무 영역 마스터 |
| `biz_meta_area_join_ready.csv` | 50,000 | 9 | 표준화 후 조인 결과 대조 |
| `biz_meta_area_parent_lookup.csv` | 1,000 | 4 | 상위 영역 및 계층 관계 검증 |
| **합계** | **104,000** | **24** | 파일별 컬럼 수 합계 |

파일 간 중복 컬럼을 제거한 공식 분석 대상은 16개 고유 필드이다. 구현 시 다음 항목을 확인한다.

- 파일 존재 여부와 SHA-256 체크섬
- 실제 행·컬럼 수와 기준값의 일치 여부
- 16개 고유 필드의 프로파일링 및 표준 매핑 상태
- 관계 후보의 참조 성공·실패 현황
- 표준화 후 조인 결과와 대조 데이터의 일치 여부

`biz_legacy_integrated.csv`는 공식 평가 집계와 분리된 확장 검증 입력으로 관리한다. 이 파일을 공식 범위에 편입하려면 인벤토리, 기준 행 수, 표준 사전 및 품질 규칙을 함께 개정해야 한다.

## 3. 목표 아키텍처와 책임 경계

```mermaid
flowchart TD
    SOURCE["공식 CSV 4종 / 웹 수집 원천"] --> BRONZE["Bronze<br/>원본 + 매니페스트"]
    BRONZE --> STANDARDIZE["Silver<br/>컬럼·값 표준화"]
    STANDARDIZE --> FIRST_GATE{"1차 품질 검증"}
    FIRST_GATE -->|통과| CANDIDATE["Accepted Candidate<br/>표준화된 원천 데이터"]
    FIRST_GATE -->|실패| REJECT_STD["REJECTED_STANDARDIZATION"]
    CANDIDATE --> RELATION_GATE["To-Be 엔터티 분리·정규화"]
    RELATION_GATE -->|통과| FINAL["Final Accepted<br/>표준 엔터티"]
    RELATION_GATE -->|실패| REJECT_REL["REJECTED_RELATIONSHIP"]
    FINAL --> RDB["RDB"]
    FINAL --> GOLD_BUILD["Gold 피처 계산<br/>조인·집계·검증"]
    GOLD_BUILD --> GOLD["gold_manager_assignment_features<br/>(run_id, manager_id)"]
    GOLD --> GOLD_VIEW["dashboard_gold_manager_assignment_view<br/>최신 SUCCESS"]
    REJECT_STD --> MONGO["MongoDB"]
    REJECT_REL --> MONGO
    RDB --> DJANGO["Django 조회"]
    GOLD_VIEW --> DJANGO
    MONGO --> DJANGO
    BRONZE -. "run_id·체크섬" .-> LINEAGE["실행·검증·계보 로그"]
    STANDARDIZE -. "규칙 버전·1차 판정" .-> LINEAGE
    RDB -.-> LINEAGE
    GOLD -. "Final Accepted 기반·feature_version" .-> LINEAGE
    MONGO -.-> LINEAGE
```

### 3.1 처리 상태 정의

| 상태 | 의미 | 다음 처리 |
| --- | --- | --- |
| `STANDARDIZING` | Bronze 원천에 컬럼·값 표준화 규칙 적용 중 | 1차 품질 검증 |
| `ACCEPTED_CANDIDATE` | 표준화 및 1차 품질 검증을 통과한 원천 행 | 엔터티 분리·정규화 |
| `REJECTED_STANDARDIZATION` | 스키마·필수값·타입·날짜·도메인 등 기본 품질 검증 실패 | MongoDB 적재 |
| `NORMALIZING` | Accepted Candidate에서 To-Be 엔터티와 관계 추출 중 | 모델·관계 검증 |
| `FINAL_ACCEPTED` | PK·FK·중복·관계 검증까지 통과한 최종 엔터티 | RDB 적재 |
| `REJECTED_RELATIONSHIP` | 엔터티 추출, PK·FK 또는 관계 무결성 검증 실패 | MongoDB 적재 |
| `GOLD_FEATURE_GENERATING` | Final Accepted `manager`·`area`·`top_area`를 담당자 단위로 조인·집계하는 중 | Gold 품질 검증 |
| `GOLD_READY` | Gold 피처 계산·검증·적재가 완료된 상태 | 최신 성공 View·분석 조회 |
| `GOLD_FAILED` | 입력 범위·속성 일관성·날짜 계산·적재 검증에 실패한 상태 | 실패 원인 기록 및 재처리 |

`Accepted Candidate`는 최종 RDB 적재 승인을 의미하지 않는다. 정규화와 관계 무결성 검증까지 통과한 `Final Accepted`만 RDB 적재 대상이 된다.

### 3.2 레이어와 저장소의 책임

| 구분 | 저장 대상 | 목적 |
| --- | --- | --- |
| Bronze | Raw CSV, `manifest.json` | 수집한 원본과 수집 정보를 변경 없이 저장 |
| Silver | Accepted Candidate, 정규화 엔터티 후보, 단계별 Rejected 및 검증 결과 | 표준화·정규화·검증된 중간 및 최종 처리 결과 저장 |
| RDB | Final Accepted 엔터티 | Django에서 조회할 표준 데이터를 관계형 구조로 저장 |
| Gold RDB | `gold_manager_assignment_features`, `dashboard_gold_manager_assignment_view` | Final Accepted를 담당자 단위 분석 피처로 재구성하고 최신 성공 결과를 조회 |
| MongoDB | Rejected 레코드와 품질 이슈 | 실패 단계·필드·관계·사유를 조회할 수 있도록 저장 |


> Bronze·Silver·Gold 결과는 `run_id`로 실행 회차와 연결한다. Gold는 Silver `Final Accepted`만을 원천으로 사용하며, `feature_version`과 `as_of_datetime`을 함께 보존해야 한다. RDB와 MongoDB의 결과에서도 해당 `run_id`를 통해 원천 데이터와 처리 결과를 역추적할 수 있어야 한다.


## 4. 사용자 흐름 및 기능 요구사항

### 4.1 수집 및 Bronze 저장

1. crontab 스케줄러가 3분마다 수집 작업을 호출한다.
2. 실행기는 수집 대상·범위와 고유 `run_id`를 등록한다.
3. 크롤러가 원본을 수집한다. 웹 수집은 API 키를 환경 변수로 주입하고 타임아웃과 원천별 호출 제한을 준수한다.
4. 이전 실행이 끝나지 않은 경우 다음 실행은 병렬로 시작하지 않고 건너뜀 상태와 사유를 기록한다.
5. 원본을 변형하지 않은 채 신규 `run_id` 경로에 저장하고 SHA-256 체크섬을 계산한다.
6. 매니페스트와 크롤링 상태를 기록한다. 일부 대상 실패는 `PARTIAL_FAILURE`, 필수 대상 전체 누락은 `FAILED`로 기록한다.
7. Bronze 유효성 검사 후 Silver 실행 후보로 전달한다.

권장 경로는 다음과 같다.

```text
data/bronze/{source_name}/ingest_date=YYYY-MM-DD/run_id={run_id}/
├── raw/{original_file}
└── manifest.json
```

Bronze 매니페스트는 최소 다음 정보를 포함한다.

| 필드 | 설명 |
| --- | --- |
| `run_id` | 실행 회차 식별자 |
| `source_name`, `source_uri` | 원천 식별자와 위치 |
| `collected_at`, `ingest_date` | 실제 수집 시각과 수집 일자 |
| `raw_path`, `content_type`, `file_size_bytes` | 저장 원본 정보 |
| `checksum_sha256` | 원본 무결성 체크섬 |
| `retry_count`, `http_status` | HTTP 수집 결과 |
| `crawler_version` | 수집 코드 버전 |
| `crawl_status`, `failure_reason` | 크롤링 성공·부분 실패·실패 상태와 사유 |

### 4.2 AS-IS 분석 및 표준 사전 구축

AS-IS 분석은 표준화 이전의 발견 사실을 남기며 이후 Silver 규칙과 TO-BE 모델의 근거가 된다.

| 산출물 | 목적 | 최소 내용 |
| --- | --- | --- |
| `as_is_profile.json` | 기계 판독 가능한 프로파일링 결과 | 파일·컬럼별 행 수, 타입, Null, 고유값, 패턴, 중복 |
| `legacy_columns_research.csv` | 컬럼 분석 | 원천 시스템, Legacy 컬럼, 예시값, 설명, 이슈 |
| `standard_words.csv` | 표준 단어 사전 | 안정 ID, 한글·영문 단어, 허용 약어, 정의, Legacy 표현 |
| `domain_rules.yaml` | 도메인 규칙 | 도메인 ID, 타입, 길이·형식, 허용값, 변환 규칙 |
| `naming_rules.yaml` | 명명 규칙 | 언어, `snake_case`, 물리명 패턴, 구분자, 약어 기준 |
| `standard_terms.csv` | 표준 용어·매핑 | 논리·물리명, 단어 ID, 정의, 도메인, Null 여부, Legacy 컬럼 |
| `source_to_standard_mapping.csv` | 원천별 컬럼 매핑 | 원천 컬럼, 표준 컬럼, 매핑 상태와 근거 |

Silver 표준화는 승인된 위 규칙 파일만을 기준으로 수행한다. 세부 컬럼 매핑과 변환값은 산출물에서 관리하며 PRD에 중복 정의하지 않는다.

모든 실행 회차에는 하나의 `rule_version`을 적용한다. 승인된 규칙에 없는 값은 임의로 변환하거나 보정하지 않으며, 미매핑 또는 판단 불가 사유를 기록한다.

### 4.3 Silver 표준화 및 품질 검증

각 Bronze 입력 행은 승인된 규칙으로 표준화한 후 기본 품질 검증을 거친다. 이 단계의 통과 결과는 최종 Accepted가 아니라 `Accepted Candidate`다. 기본 품질 검증을 통과하지 못한 행은 `REJECTED_STANDARDIZATION`으로 분류한다.

| 순서 | 처리 | 산출물 |
| ---: | --- | --- |
| 1 | Bronze 원본 파싱과 파일·스키마 검증 | 입력 행, 파싱·스키마 이슈 |
| 2 | 컬럼명 매핑과 문자열·식별자·날짜·논리값 표준화 | 표준화 후보 행 |
| 3 | 필수값·타입·날짜·도메인·식별자 매핑 검증 | 규칙별 1차 검증 결과 |
| 4 | 1차 통과 행 분류 | `accepted_candidate_rows.csv` |
| 5 | 1차 실패 행과 필드 이슈 분류 | `rejected_standardization_rows.csv`, 품질 이슈 |
| 6 | 원천 행 기준 1차 판정 완결성 검증 | `standardization_validation_check.json`(1차 실행 요약·검증 로그) |

#### 품질 게이트

| 검증 항목 | Accepted Candidate 수용 기준 | 실패 상태·코드 |
| --- | --- | --- |
| 행 수 | Bronze 입력 행과 1차 판정 결과를 대사할 수 있음 | 대사 불가 시 실행 실패 |
| 필수값 | 기본 필수 필드 결측 0건 | `REJECTED_STANDARDIZATION`·`MISSING_REQUIRED` |
| 타입·날짜 | 표준 타입과 날짜 변환 실패 0건 | `REJECTED_STANDARDIZATION`·`INVALID_TYPE`, `INVALID_DATE_FORMAT` |
| 도메인 | 승인된 허용값 밖의 값 0건 | `REJECTED_STANDARDIZATION`·`DOMAIN_VIOLATION` |
| 식별자 | 표준 식별자 매핑 실패·충돌 0건 | `REJECTED_STANDARDIZATION`·`IDENTIFIER_MAPPING_FAILED`, `IDENTIFIER_COLLISION` |

1차 건수 정합성은 다음 식으로 검증한다.

```text
Silver 입력 행 수
= Accepted Candidate 행 수 + REJECTED_STANDARDIZATION 행 수
```

### 4.4 To-Be 엔터티 분리·정규화·최종 판정 및 RDB 적재

AS-IS의 Grain, 표준 용어와 관계 검증 결과를 근거로 To-Be 모델을 확정하고, Accepted Candidate를 엔터티별로 분리·정규화한다.

1. `brd.md`에서 데이터 활용 목적과 엔터티 분리 원칙을 확정한다.
2. `entity_candidates.csv`에서 관리 대상 엔터티와 단순 속성을 구분한다.
3. `identifier_decisions.csv`에서 후보 키의 유일성·최소성·안정성·Not Null 근거를 검토한다.
4. 개념→논리→물리 모델을 작성하고 1NF·2NF·3NF 검토 결과를 기록한다.
5. Accepted Candidate 한 행에서 Employee, Area 및 필요한 관계 후보를 추출한다.
6. 엔터티 후보별 PK·업무키 중복, FK orphan, 자기참조 계층과 조인 대조 결과를 검증한다.
7. 기준 원천·시점이 승인되지 않은 `REG_DT`는 임의 선택하지 않는다.
8. 모델·관계 검증을 통과한 엔터티만 `FINAL_ACCEPTED`로 확정한다.
9. 엔터티 추출·PK·FK·관계 검증에 실패한 후보는 `REJECTED_RELATIONSHIP`으로 분류한다.
10. DDL을 생성하고 Final Accepted 엔터티를 트랜잭션 단위로 대상 RDB에 적재한다.
11. 확정된 PK·업무키를 기준으로 신규 엔터티는 삽입하고 반복 관측된 기존 엔터티는 승인된 최신 상태 반영 규칙에 따라 갱신한다.
12. 입력·삽입·갱신·건너뜀·실패 건수를 엔터티 유형별로 기록한다.


초기 논리 모델은 다음 엔터티를 기준으로 하며 실제 속성과 키는 표준 사전과 프로파일링 결과로 확정한다.

- Employee Grain: 직원 한 명. `employee_id`는 안정적 PK 후보이다.
- Area Grain: 업무 영역 한 건. `area_id`는 PK 후보이며, `parent_area_id`는 Area 자기참조 FK, `manager_employee_id`는 Employee FK이다.
- `join_ready`와 `parent_lookup`은 기준·대조 입력으로 사용한다. 별도 마스터 엔터티 적재 여부는 중복·변경 이력·업무 독립성 분석 후 결정한다.

공식 CSV 4종은 입력 역할과 검증 기준을 정의하며 To-Be 물리 테이블 수를 고정하지 않는다. 원천 파일 4종을 그대로 네 개의 기준 테이블로 복제하는 것만으로는 정규화로 보지 않는다. To-Be 테이블은 Grain, 함수적 종속성, 중복과 관계 분석으로 확정하고, `join_ready` 및 `parent_lookup`은 분석 결과에 따라 검증 입력, 조회 View 또는 독립 엔터티 중 하나로 결정한다.

#### 모델·관계 품질 게이트

| 검증 항목 | Final Accepted 수용 기준 | 실패 상태·코드 |
| --- | --- | --- |
| 엔터티 추출 | 필수 엔터티 키와 속성을 생성할 수 있음 | `REJECTED_RELATIONSHIP`·`ENTITY_EXTRACTION_FAILED` |
| PK | 엔터티별 PK 누락·비정상 중복 0건 | `REJECTED_RELATIONSHIP`·`DUPLICATE_BUSINESS_KEY` |
| FK | 관리자·상위 영역 참조 orphan 0건 | `REJECTED_RELATIONSHIP`·`FOREIGN_KEY_ORPHAN` |
| 계층 관계 | 자기참조 순환·계층 모순 0건 | `REJECTED_RELATIONSHIP`·`HIERARCHY_CONFLICT` |
| 조인 대조 | `join_ready` 기준 불일치 0건 또는 승인 예외 존재 | `REJECTED_RELATIONSHIP`·`JOIN_REFERENCE_MISMATCH` |
| 기준 불명확 | 기준 원천·시점 미승인 값 없음 | `REJECTED_RELATIONSHIP`·`AMBIGUOUS_REFERENCE_DATE` |

한 개의 원천 행에서 여러 엔터티 후보가 생성될 수 있으므로 Raw 행 수와 RDB 행 수를 직접 비교하지 않는다. 모델 단계의 건수 정합성은 엔터티 유형별로 다음 식을 검증한다.

```text
엔터티 후보 발생 건수
= Final Accepted 판정 건수 + REJECTED_RELATIONSHIP 판정 건수
```

서로 다른 `run_id`에서 동일 개체가 반복 관측되는 것은 중복 오류가 아니다. 중복 검사는 실행 회차와 엔터티의 확정된 비즈니스 키 범위에서 수행하며, RDB에서는 동일 개체를 중복 생성하지 않는다. 여러 Final Accepted 판정이 동일 엔터티로 upsert될 수 있으므로 Final Accepted 판정 건수와 최종 RDB 행 수는 별도로 기록한다.

RDB 연결·트랜잭션·제약 적용 중 발생한 기술 오류는 데이터 품질 Rejected로 변경하지 않고 파이프라인 적재 오류로 기록한다.

### 4.5 Rejected 및 품질 이슈 관리

Rejected는 단순 실패 파일이 아니라 DX 전환의 개선 대상을 설명하는 제품 결과다. 표준화·1차 품질 오류와 엔터티·관계 오류를 구분하고, 하나의 원천 행 또는 엔터티 후보가 여러 이슈를 가질 수 있도록 Rejected 레코드와 이슈를 논리적으로 분리하여 저장한다.

| 컬렉션·논리 객체 | 필수 속성 |
| --- | --- |
| `rejected_records` | `rejection_id`, `run_id`, `rejection_stage`, 원천명, 원천 레코드 키·행 번호, 엔터티 유형·키, Raw payload, 표준화 후보, 상태, 판정 시각 |
| `quality_issues` | `issue_id`, `rejection_id`, 필드·관계명, 원본값, 표준 필드, 규칙 ID·버전, 실패 유형, 사유, 치명도 |
| `processing_runs` | `run_id`, 원천 행·Accepted Candidate·Final Accepted·단계별 Rejected 건수, 규칙·코드 버전, 시작·종료 시각, 상태, 로그 위치 |

`rejection_stage`는 `STANDARDIZATION` 또는 `RELATIONSHIP` 값을 가진다. MongoDB 조회는 실행 회차, 판정 단계, 원천, 엔터티, 레코드 키, 실패 필드·관계와 실패 유형으로 필터링할 수 있어야 한다.

MongoDB 연결·쓰기 오류는 원천 데이터 품질 이슈로 기록하지 않고 파이프라인 적재 오류로 구분한다.

### 4.6 Django 단계별 품질 진단 대시보드

Django 조회 서비스는 데이터 처리 결과를 다음 세 개의 대시보드로 구분하여 제공한다.

1. 1차 대시보드: 표준화 및 기본 품질 검증 결과
2. 2차 대시보드: 정규화 및 관계 무결성 검증 결과
3. 3차 대시보드: 전체 데이터 파이프라인 통합 현황

1차와 2차 Accepted 데이터는 동일한 RDB 안에서 서로 다른 스키마 또는 테이블로 분리하여 저장한다. 단계별 Rejected 데이터와 거절 사유는 MongoDB의 `rejection_stage`로 구분한다.

```mermaid
flowchart LR
    RAW["Bronze<br/>Legacy Raw"] --> STD["표준화·1차 검증"]
    STD -->|통과| STAGE1_RDB["1차 Accepted<br/>RDB"]
    STD -->|실패| STAGE1_MONGO["1차 Rejected·사유<br/>MongoDB"]

    STAGE1_RDB --> NORMALIZE["엔터티 분리·정규화<br/>관계 검증"]
    NORMALIZE -->|통과| STAGE2_RDB["2차 Accepted<br/>RDB"]
    NORMALIZE -->|실패| STAGE2_MONGO["2차 Rejected·사유<br/>MongoDB"]

    PIPELINE["3차 통합 대시보드"] --> DASH1["1차 대시보드"]
    PIPELINE --> DASH2["2차 대시보드"]
```

#### 화면 구성 및 완료 기준

| 화면 | 주요 기능 | 완료 기준 |
| --- | --- | --- |
| 3차 통합 파이프라인 대시보드 | Bronze 수집부터 표준화, 정규화, RDB·MongoDB 적재까지 전체 흐름을 시각적으로 표현한다. 실행 단계별 상태와 처리 방향을 표시하고 1차·2차 대시보드 이동 버튼을 제공한다. | 선택한 `run_id`의 단계별 상태가 파이프라인 노드에 표시되고, 실행 중인 단계만 동적으로 강조된다. 1차·2차 대시보드 버튼이 정상적으로 이동한다. |
| 1차 표준화 결과 대시보드 | 표준화 입력, 1차 Accepted, `REJECTED_STANDARDIZATION` 결과와 주요 오류 유형을 요약한다. | 동일 `run_id`에서 표준화 입력이 Accepted와 Rejected로 빠짐없이 구분되어 표시된다. |
| 1차 Accepted 조회 | 표준화된 원천 레코드를 RDB에서 조회하고 원천명, 표준 식별자, 상태, 실행 회차로 검색·필터링한다. | RDB에 저장된 1차 Accepted 레코드가 목록과 상세 화면에 표시되고 Raw 레코드까지 역추적할 수 있다. |
| 1차 Rejected·사유 조회 | MongoDB의 `REJECTED_STANDARDIZATION` 레코드와 필드별 실패 규칙, 원본값, 사유를 조회한다. | 실행 회차, 원천, 필드, 오류 코드, 치명도로 필터링할 수 있고 하나의 레코드에 포함된 복수 이슈를 확인할 수 있다. |
| 2차 정규화 결과 대시보드 | 엔터티 후보, Final Accepted, `REJECTED_RELATIONSHIP` 결과와 엔터티별 처리 상태를 요약한다. | Employee·Area·관계 등 엔터티 유형별 최종 판정 결과가 구분되어 표시된다. |
| 2차 Accepted 조회 | 정규화된 Employee·Area 등 Final Accepted 엔터티를 RDB에서 조회한다. PK, 업무키, 상위 영역, 관리자 관계를 확인한다. | 정규화 RDB의 엔터티 목록·상세·관계 정보가 표시되고 원천 행과 1차 Accepted 결과까지 역추적할 수 있다. |
| 2차 Rejected·사유 조회 | MongoDB의 `REJECTED_RELATIONSHIP` 레코드와 PK·FK·계층·조인 오류 사유를 조회한다. | 엔터티 유형, 관계명, 오류 코드, 원천 레코드 기준으로 필터링하고 관계 검증 실패 원인을 확인할 수 있다. |
| 실행 회차 선택 및 계보 상세 | 모든 대시보드에서 `run_id`를 선택하고 원천 파일, 매니페스트, 규칙 버전, 처리 결과를 조회한다. | 화면에 표시된 집계와 상세 데이터가 동일한 `run_id`에 속하며 원천부터 최종 결과까지 이동할 수 있다. |

### 4.7 Gold 담당자 분석 피처 생성

Gold 생성은 Silver의 `Final Accepted` 엔터티를 분석 목적에 맞게 재구성하는 후속 처리다. Silver의 원장 상세도와 Gold의 반복 집계 결과를 분리하여, 검증·계보가 필요한 화면과 담당자별 비교·요약 화면이 서로의 목적을 침범하지 않도록 한다.

#### 입력과 출력

1. 입력은 동일 `run_id`의 Final Accepted `manager`, `area`, `top_area`다. `REJECTED_STANDARDIZATION`, `REJECTED_RELATIONSHIP` 및 아직 최종 판정되지 않은 후보는 입력에서 제외한다.
2. `manager`와 `area`를 담당자 식별자로 연결하고, `area`와 `top_area`의 계층 관계를 이용하여 담당자별 관리 영역 집합을 만든다.
3. 담당자 속성·영역 등록일의 회차 내 일관성, FK 관계 및 기준 시점 대비 날짜 계산 가능 여부를 검증한다.
4. 검증을 통과한 결과를 `gold_manager_assignment_features`에 저장한다. 물리 Grain은 담당자 한 명당 실행 회차별 한 행이며 PK는 `(run_id, manager_id)`다.
5. 동일 `run_id` 재실행 시 해당 회차 Gold 행을 교체하여 중복 없이 같은 결과를 만들고, 다른 회차의 이력은 보존한다.
6. `dashboard_gold_manager_assignment_view`는 `pipeline_run_summary.batch_status = 'SUCCESS'`인 회차 중 가장 최근 회차만 반환한다. 테이블에는 계보용 `run_id`, `as_of_datetime`, `feature_version`을 보존하고 View는 대시보드에 필요한 피처 중심으로 제공한다.

#### Gold 피처 계약

| 컬럼 | 타입·규칙 | 수용 기준 |
| --- | --- | --- |
| `run_id` | 실행 회차 전체 문자열, `VARCHAR(100)` | 원천 실행과 동일하고 Null이 아님 |
| `as_of_datetime` | 실행 회차 기준 시각, `DATETIME` | 모든 행에서 동일 회차 기준 시각 |
| `manager_id` | 담당자 업무키, `VARCHAR(9)` | `(run_id, manager_id)` 유일 |
| `manager_department_name` | 담당자 부서명 | 같은 회차 담당자 값이 하나로 일관됨 |
| `manager_position_name` | 담당자 직급 | 같은 회차 담당자 값이 하나로 일관됨 |
| `manager_active_flag` | 활성 여부 `Y/N` → `1/0` | `0` 또는 `1` |
| `manager_tenure_days` | 기준 시각 - 입사일의 일수 | 음수 없음, 계산 불가 행 없음 |
| `managed_area_count` | `DISTINCT area_id` 수 | 담당자별 관리 영역 집합과 일치 |
| `managed_top_area_count` | 연결된 `DISTINCT top_area_id` 수 | 하위 영역을 통한 연결까지 포함 |
| `managed_parent_area_count` | 연결된 `DISTINCT parent_area_id` 수 | Null 부모는 집계하지 않음 |
| `top_level_area_count` | 직접 최상위 영역 수 | `parent_area_id` Null 및 `area_id=top_area_id` 조건 |
| `average_area_age_days` | 영역 연령 평균 | 소수 둘째 자리까지 재계산 일치 |
| `max_area_age_days` | 영역 연령 최대값 | 평균·최대 계산 대상과 동일한 영역 집합 |
| `cross_top_area_flag` | 둘 이상의 최상위 영역 관리 여부 | `managed_top_area_count > 1`이면 `1`, 아니면 `0` |
| `feature_version` | Gold 계산 규칙 버전 | 모든 행에 기록, 규칙 변경 시 증가 |

`managed_top_area_count`와 `top_level_area_count`는 서로 대체할 수 없다. 전자는 하위 영역을 통해 연결된 최상위 영역까지 포함하고, 후자는 담당자가 직접 최상위 영역으로 지정된 경우만 센다. 동일 영역이 여러 행에 나타나도 모든 영역 수는 `DISTINCT`로 계산한다.

관리 영역이 0개인 담당자를 Gold 모집단에 포함할지는 업무 정책으로 확정한다. 포함이 요구되면 `manager`를 기준으로 `LEFT JOIN`하고 영역 관련 카운트·연령값을 0으로 저장해야 하며, 포함하지 않기로 하면 그 범위를 수용 기준과 대시보드 설명에 명시한다.

## 5. 상세 요구사항 및 수용 기준

| ID | 요구사항 | 수용 기준 |
| --- | --- | --- |
| PRD-01 | 공식 CSV 4종을 입력 기준 데이터로 관리한다. | 파일·행 수 합계 104,000과 16개 고유 필드 기준이 인벤토리에 기록된다. |
| PRD-02 | 웹 수집은 crontab으로 3분마다 실행하고 회차별 원본을 보존한다. | 각 실행에 고유 `run_id`, 실제 수집 시각과 크롤링 상태가 기록된다. |
| PRD-03 | Bronze는 원본을 변경하지 않는다. | 원본·체크섬·매니페스트가 동일 `run_id`로 연결되고 덮어쓰기가 없다. |
| PRD-04 | 모든 Legacy 컬럼에 표준화 적용 여부를 판정한다. | Coverage 검증에서 매핑·단어·도메인·명명 규칙 상태가 확인된다. |
| PRD-05 | Silver는 모든 원천 행을 Accepted Candidate 또는 `REJECTED_STANDARDIZATION`으로 1차 판정한다. | Silver 입력 행 수와 두 1차 판정 결과의 합이 일치하고 미판정 행이 0건이다. |
| PRD-06 | 판단 불가 값은 임의 보정하지 않는다. | Rejected에 판정 단계, 원본값, 규칙, 실패 유형과 사유가 보존된다. |
| PRD-07 | Accepted Candidate를 To-Be 업무 엔터티와 관계로 분리한다. | 각 후보에서 생성된 엔터티 유형·키와 원천 행의 연결 정보가 기록된다. |
| PRD-08 | 분리된 엔터티를 정규화하고 PK·FK·관계 무결성을 검증한다. | 엔터티 후보가 `FINAL_ACCEPTED` 또는 `REJECTED_RELATIONSHIP`으로 판정되고 미판정 후보가 0건이다. |
| PRD-09 | 조인 결과를 기준 데이터와 대조한다. | `join_ready` 불일치가 0건이거나 승인된 예외와 근거가 검증 로그에 남는다. |
| PRD-10 | 단계별 Rejected와 품질 이슈를 조회할 수 있다. | MongoDB에 `rejection_stage`와 레코드·이슈가 저장되고 화면 필터가 동작한다. |
| PRD-11 | Final Accepted만 정규화 RDB에 적재한다. | 적재 전후 PK 중복·FK orphan·필수값·도메인 위반이 0건이며 Accepted Candidate는 직접 적재되지 않는다. |
| PRD-12 | 결과는 원천까지 역추적할 수 있다. | Final Accepted·Rejected 상세에서 원천, `run_id`, Raw 경로, 규칙 버전과 파생 엔터티를 확인할 수 있다. |
| PRD-13 | Django에서 처리 단계별 결과를 구분해 조회한다. | Accepted Candidate 건수, Final Accepted 엔터티와 두 Rejected 단계의 이슈를 각각 확인할 수 있다. |
| PRD-14 | Gold는 Silver `Final Accepted` `manager`·`area`·`top_area`를 담당자 단위로 집계한다. | Gold 입력 원천과 `run_id`가 Silver Final Accepted와 일치하고 Rejected·미판정 데이터가 포함되지 않는다. |
| PRD-15 | Gold의 물리 Grain은 실행 회차별 담당자 한 명당 한 행이다. | 모든 회차에서 `(run_id, manager_id)` 중복이 0건이다. |
| PRD-16 | Gold는 합의된 담당자·관리 영역·최상위 영역·영역 연령 피처를 정의된 계산식으로 생성한다. | 독립 재계산 결과와 Gold 컬럼별 값이 일치하고 `managed_top_area_count`와 `top_level_area_count`가 구분된다. |
| PRD-17 | Gold 행은 전체 `run_id`, `as_of_datetime`, `feature_version`과 함께 저장되어야 한다. | 모든 Gold 행에서 실행 회차·기준 시각·규칙 버전을 확인할 수 있다. |
| PRD-18 | 동일 실행 회차의 Gold 적재는 멱등적으로 처리해야 한다. | 같은 `run_id`를 재실행해도 Gold 중복이 발생하지 않고 동일한 입력에서 같은 결과가 유지된다. |
| PRD-19 | Gold는 최신 `SUCCESS` 실행 회차를 조회하는 대시보드용 View를 제공해야 한다. | `dashboard_gold_manager_assignment_view`가 최신 성공 회차만 노출하고 실패·실행 중 회차를 노출하지 않는다. |
| PRD-20 | 관리 영역이 0개인 담당자의 Gold 포함 정책을 구현·검증해야 한다. | 포함 정책이면 `manager` 기준 `LEFT JOIN`으로 담당자와 0값 피처가 보존되고, 제외 정책이면 제외 근거가 문서화된다. |

### 5.1 실행 검증 결과 계약

`run_validation.json`은 각 처리 단계의 입력·판정·적재 건수를 별도로 기록해야 한다.

| 필드 | 의미 |
| --- | --- |
| `silver_input_rows` | Silver 1차 판정 대상 원천 행 수 |
| `accepted_candidate_rows` | 1차 품질 검증 통과 행 수 |
| `rejected_standardization_rows` | 1차 품질 검증 실패 행 수 |
| `entity_candidate_counts` | Employee·Area·관계 등 엔터티 유형별 후보 발생 건수 |
| `final_accepted_counts` | 엔터티 유형별 Final Accepted 판정 건수 |
| `rejected_relationship_counts` | 엔터티 유형·관계별 모델·관계 Rejected 건수 |
| `rdb_inserted_counts` | 엔터티별 신규 삽입 행 수 |
| `rdb_updated_counts` | 엔터티별 기존 행 갱신 수 |
| `mongodb_rejected_counts` | 판정 단계·오류 코드별 MongoDB 저장 건수 |
| `gold_input_final_accepted_rows` | Gold 계산에 사용한 Final Accepted 원천 엔터티 행 수 |
| `gold_manager_feature_rows` | 실행 회차별 Gold 담당자 피처 행 수 |
| `gold_run_id` | Gold 결과가 속한 실행 회차 전체 문자열 |
| `gold_feature_version` | Gold 피처 계산 규칙 버전 |
| `gold_duplicate_key_count` | `(run_id, manager_id)` 중복 키 건수 |
| `gold_source_reconciliation_status` | Silver Final Accepted와 Gold 입력 범위 대사 상태 |
| `gold_loaded_count` | Gold 테이블에 실제 반영된 행 수 |

다음 두 검증식이 모두 성립해야 하며, RDB 행 수는 upsert 결과로 별도 대사한다.

```text
silver_input_rows
= accepted_candidate_rows + rejected_standardization_rows
```

```text
entity_candidate_counts[entity_type]
= final_accepted_counts[entity_type] + rejected_relationship_counts[entity_type]
```

Gold 검증은 다음 식과 조건을 추가로 만족해야 한다.

```text
gold_manager_feature_rows[run_id]
= COUNT(DISTINCT manager_id in the approved Gold input scope)
```

```text
gold_duplicate_key_count = 0
gold_loaded_count = gold_manager_feature_rows[run_id]
```

관리 영역이 0개인 담당자를 포함하는 정책이 승인되면 `approved Gold input scope`는 `manager` 전체 모집단이며, 제외 정책이면 해당 회차 Final Accepted에서 실제 관리 영역이 존재하는 담당자 모집단으로 정의한다. 이 정책을 실행 로그에 기록한다.

### 5.2 핵심 수용 시나리오

| 시나리오 | 입력·조건 | 기대 결과 |
| --- | --- | --- |
| 1차 통과 | 표준 매핑·필수값·타입·도메인을 충족한 원천 행 | `ACCEPTED_CANDIDATE` 생성, RDB 직접 적재 없음 |
| 1차 실패 | 필수값 누락 또는 타입·도메인 오류 | `REJECTED_STANDARDIZATION`과 필드 이슈 생성 |
| 엔터티 분리 | 한 Accepted Candidate에 직원·영역·관리자 관계 정보 존재 | Employee·Area·관계 후보가 원천 행과 연결되어 생성 |
| 관계 실패 | 관리자 FK 또는 상위 영역 FK 참조 대상 없음 | 해당 후보가 `REJECTED_RELATIONSHIP`으로 분류 |
| 최종 통과 | 엔터티 키·참조·조인 대조를 모두 충족 | `FINAL_ACCEPTED` 판정 후 RDB 삽입 또는 갱신 |
| 반복 관측 | 다른 `run_id`에서 동일 업무키 재수집 | 오류 중복으로 분류하지 않고 기존 RDB 엔터티 갱신 |
| 단계별 조회 | 두 종류의 Rejected와 Final Accepted가 존재 | Django에서 판정 단계·엔터티·오류 유형별 구분 조회 |
| Gold 기본 집계 | 한 담당자가 3개 영역과 2개 최상위 영역을 관리 | 담당자당 Gold 1행, `managed_area_count=3`, `managed_top_area_count=2`, `cross_top_area_flag=1` |
| Gold 속성 충돌 | 같은 회차 같은 담당자에 서로 다른 부서·직급이 존재 | Gold 생성 실패, 충돌 원인과 `run_id` 기록 |
| Gold 영역 기준일 충돌 | 같은 `area_id`에 서로 다른 등록일이 존재 | Gold 생성 실패, 영역 식별자와 충돌 값 기록 |
| Gold 영역 없는 담당자 | 관리 영역이 없는 담당자가 존재 | 승인된 포함 정책이면 0값 Gold 행 생성, 제외 정책이면 제외 근거와 모집단 기록 |
| Gold 재실행 | 같은 `run_id`와 동일 입력으로 Gold 재실행 | 기존 회차 Gold를 중복 없이 교체하고 결과가 동일함 |
| 최신 Gold View | 성공·실패·실행 중 회차가 함께 존재 | 최신 `SUCCESS` 회차만 `dashboard_gold_manager_assignment_view`에 표시 |

## 6. 실행 산출물 및 일정

### 6.1 제출 산출물

```text
project/
├── README.md
├── .env
├── docs/
│   ├── as_is_profiling.md
│   ├── data_inventory.csv
│   ├── relationship_profile.csv
│   ├── legacy_columns.csv
│   ├── legacy_column_research.csv
│   ├── standard_words.csv
│   ├── standard_terms.csv
│   ├── source_to_standard_mapping.csv
│   ├── domain_rules.yaml
│   ├── naming_rules.yaml
│   ├── quality_rules.yaml
│   ├── standard_coverage_validation.json
│   ├── business_rules.md
│   ├── entity_candidates.csv
│   ├── identifier_decisions.csv
│   ├── conceptual_model.md
│   ├── logical_model.md
│   └── lineage.md
├── data/
│   ├── bronze/
│   ├── silver/
│   │   ├── candidates/
│   │   │   └── accepted_candidate_rows.csv
│   │   ├── accepted/
│   │   │   └── {entity_name}.csv
│   │   └── rejected/
│   │       ├── rejected_standardization_rows.csv
│   │       ├── rejected_relationship_entities.csv
│   │       └── quality_issues.json
│   └── gold/
│       └── manager_assignment_features.csv
├── logs/
│   ├── run_validation.json
│   └── gold_validation.json
├── src/
│   └── gold/
│       └── manager_assignment_features.py
├── django_app/
└── ddl/
    └── schema.sql
```

Gold를 RDB에 물리화하는 경우 DDL에는 `gold_manager_assignment_features` 테이블과 `dashboard_gold_manager_assignment_view`를 포함한다. Gold 파일 경로는 재처리·검증용 산출물이며, 대시보드의 운영 조회 기준은 RDB 테이블과 View다.

### 6.2 2일 실행 계획

| 시점 | 수행 작업 | 완료 증빙 |
| --- | --- | --- |
| 1일차 오전 | 데이터 인벤토리, Grain 분석, 프로파일링, 관계 후보 및 품질 기준선 확인 | `data_inventory.csv`, `as_is_profiling.md`, `legacy_column_research.csv`, `relationship_profile.csv` |
| 1일차 오후 | 표준 단어·용어·도메인·명명·매핑 규칙과 TO-BE 모델 확정 | `standard_words.csv`, `standard_terms.csv`, `domain_rules.yaml`, `naming_rules.yaml`, `source_to_standard_mapping.csv`, `entity_candidates.csv`, `identifier_decisions.csv`, `conceptual_model.md`, `logical_model.md` |
| 2일차 오전 | 크롤링, Bronze 저장, Silver 표준화·1차 검증 및 To-Be 엔터티 분리·정규화 | 회차별 `raw.csv`, `manifest.json`, `accepted_candidate_rows.csv`, `{entity_name}.csv`, `rejected_standardization_rows.csv`, `rejected_relationship_entities.csv`, `quality_issues.json`, `run_validation.json` |
| 2일차 오후 | Final Accepted RDB 적재, Gold 담당자 피처 생성·검증·적재, 단계별 Rejected MongoDB 적재, Django 조회, 계보 및 통합 검증 | `schema.sql`, Gold 검증 로그, Django migration 파일, `README.md` |

## 7. 비기능 요구사항·운영 원칙

- 재현성: 입력 체크섬, 코드·규칙 버전, 파티션 경로와 실행 로그로 결과를 재현한다.
- 멱등성: 동일 `run_id`의 성공 원본을 덮어쓰지 않으며 재처리는 별도 실행 또는 명시된 재처리 상태로 기록한다.
- 보안: API 키·세션·인증정보를 코드·매니페스트·로그에 저장하지 않는다.
- 복구: 파싱·스키마 오류가 발생해도 원본은 Bronze에 남기고 Silver 처리만 차단한다. 실패 대상은 전체 재수집 없이 선택 재처리할 수 있어야 한다.
- 관측성: 실행 성공·부분 실패율, 수집 파일·행 수, 체크섬 중복, Accepted Candidate·Final Accepted 건수, 판정 단계별 Rejected 분포와 엔터티별 처리율을 기록한다.
- Gold 재현성: 동일 `run_id`·Silver Final Accepted·피처 버전이면 동일한 담당자 집계 결과를 생성한다.
- Gold 계보: Gold 행은 전체 `run_id`, 기준 시각, 피처 버전과 입력 범위를 확인할 수 있어야 하며, Rejected 입력은 계산에서 제외한다.
- Gold 멱등성: 같은 실행 회차를 재처리해도 Gold 스냅샷 중복이 발생하지 않고 최신 성공 View의 선택 기준이 흔들리지 않는다.

## 8. 완료 정의 및 확정 과제

### 8.1 Definition of Done

- 공식 CSV 4종·104,000행 기준선과 Bronze 저장 결과를 대사할 수 있다.
- 16개 고유 필드의 표준 사전, Legacy→표준명 매핑, 도메인 및 명명 규칙이 존재하고 적용 범위를 검증한다.
- Bronze와 Silver의 책임이 분리되고 모든 실행에 매니페스트와 계보 정보가 존재한다.
- 모든 Silver 입력 행이 Accepted Candidate 또는 `REJECTED_STANDARDIZATION`으로 1차 판정된다.
- Accepted Candidate가 To-Be 엔터티로 분리·정규화되고 모든 엔터티 후보가 `FINAL_ACCEPTED` 또는 `REJECTED_RELATIONSHIP`으로 최종 판정된다.
- Final Accepted 데이터만 정규화된 RDB에 적재되고 단계별 Rejected와 이슈는 MongoDB에 적재된다.
- Silver Final Accepted를 입력으로 Gold 담당자 피처가 `(run_id, manager_id)` 단위로 생성되고 중복·미판정 행이 없다.
- Gold의 `managed_area_count`, `managed_top_area_count`, `managed_parent_area_count`, `top_level_area_count`, 영역 연령, 담당자 근속 및 `cross_top_area_flag`가 독립 계산과 일치한다.
- Gold 행에서 전체 `run_id`, `as_of_datetime`, `feature_version`을 확인할 수 있고 동일 회차 재실행이 멱등적이다.
- `dashboard_gold_manager_assignment_view`가 최신 `SUCCESS` 회차만 반환하며 Silver 상세 원장과 Gold 집계 결과의 책임이 문서·DDL에서 구분된다.
- Django에서 Accepted Candidate 건수, Final Accepted 엔터티, 표준화 Rejected와 모델·관계 Rejected를 구분하여 조회할 수 있다.
- PK·FK, 필수값, 도메인, 타입·날짜, 엔터티 추출 및 조인 대조 검증 결과가 저장되고 수용 기준을 충족한다.
- 원천 행에서 파생된 Employee·Area·관계 엔터티와 최종 판정 결과를 역추적할 수 있다.
- `README.md`의 절차와 저장소에 포함된 소스 코드, 의존성 파일, 환경 변수 예시, 규칙 파일 및을 이용하여 신규 환경에서 수집·적재·변환·검증·조회 절차를 재현할 수 있다.
- 실제 API 키와 DB 인증정보를 제외한 필수 환경 변수의 이름과 설정 방법이 제공된다.
- Django 실행 절차가 제공된다.

### 8.2 프로젝트 수행 중 확정할 사항

다음 항목은 사전 입력값이 아니라 분석·설계 또는 팀 합의를 통해 프로젝트 수행 중 확정한다.

1. 웹 수집의 정확한 엔드포인트, API 키 전달 헤더, 페이지별 수집 범위 및 호출 제한
2. 16개 필드의 표준명, 타입, 허용값, 필수 여부와 식별자 정규화 규칙
3. `REG_DT` 불일치의 기준 원천, 기준 시점과 승인 근거
4. RDB 제품과 착수 시점 최신 안정 버전, Django 실행 환경 및 MongoDB 연결 방식
5. `join_ready`를 대조 전용으로 둘지 별도 조회 모델로 제공할지에 대한 결정
6. 품질 규칙별 `ERROR`, `WARNING`, `INFO` 최종 치명도
7. 동일 실행 회차 중복 행의 대표 행 선정 및 병합 정책
8. 관리 영역이 0개인 담당자를 Gold 모집단에 포함할지 여부와 포함 시 0값 피처 처리 기준
9. Gold 영역 연령·담당자 근속의 기준 시각, 시간대 및 소수점 반올림 규칙
10. Gold 피처 버전 증가 기준과 최신 `SUCCESS` 회차 View의 동률 처리 규칙

정책이 승인되기 전에는 중복 대표 행을 자동 선정하거나 병합하지 않으며, 판단 근거가 없는 값을 임의로 보정하지 않는다.
