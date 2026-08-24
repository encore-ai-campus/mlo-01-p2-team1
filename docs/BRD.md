# BRD v1.0 — 업무 요구사항 정의서

> **BRD (Business Requirements Document, 업무 요구사항 정의서)**  
> 프로젝트의 목적, 범위, 핵심 요구사항과 팀 공통 의사결정 사항을 정리한다.  
> 상세 데이터 정의와 처리 규칙은 별도 문서를 참조한다.

## 1. 프로젝트 개요

- 프로젝트명: 데이터 표준화 및 AI Ready Data 구축 프로젝트
- 기간: 2026-08-27 ~ 2026-08-28
- 팀 구성: 4명(조장, 팀원1, 팀원2, 신성민)
- 목적: 레거시 원천 데이터를 Bronze → Silver → Gold 구조로 변환하여 AI 활용 가능한 데이터셋을 구축한다.

## 2. 프로젝트 범위

### In Scope — 포함 범위
- 공식 CSV 4종 분석 및 기준선 확인
- 내부 API 원천 수집
- Bronze 원본 보존
- Silver 표준화 및 품질 정제
- Gold 직원/영역 차원 및 `area_manager_features` 생성
- 품질 검증 자동화
- 표준 사전, AS-IS 리포트, TO-BE 명세, README, 발표자료, 회고 작성

### Out of Scope — 제외 범위
> 이번 2일 프로젝트에서 하지 않을 일을 적는다.

예시:
- 실제 운영 배포
- 장기 모니터링 시스템 구축
- 머신러닝 모델 학습 자체

팀 결정:
- 
- 
- 

## 3. AS-IS 요약

> 상세 내용은 `as_is_profiling.md` 참조

- 공식 데이터: CSV 4종, 총 104,000행
- 고유 필드: 16개
- 예상 문제 유형: 공백, 대소문자, 날짜 형식, 코드값 불일치, PK/FK, 결측, 조인 정합성

## 4. TO-BE 요약

```text
원천 CSV / 내부 API
        ↓
Bronze — 원본 보존
        ↓
Silver — 표준화·정제
        ↓
Gold — AI Ready Data
```

> 상세 구조는 `to_be_medallion_model.md` 참조

## 5. 핵심 업무 요구사항

`BR`은 **Business Requirement(업무 요구사항)** 의 약자이며, 아래 ID는 팀 내부 관리용이다.

| ID | 요구사항 | 설명 |
|---|---|---|
| BR-001 | 원본 보존 | Bronze에서는 원천값을 변경하지 않는다. |
| BR-002 | 표준화 | Silver에서는 팀이 확정한 표준 컬럼명·타입·도메인을 적용한다. |
| BR-003 | 품질 검증 | PK/FK/결측/도메인/조인/타입 검증을 수행한다. |
| BR-004 | AI Ready Data | Gold에서 직원·영역 차원 및 `area_manager_features`를 생성한다. |
| BR-005 | 재현성 | 동일 입력과 동일 코드에서 동일 결과를 재현할 수 있어야 한다. |
| BR-006 | 계보 추적 | Source → Bronze → Silver → Gold 흐름을 추적할 수 있어야 한다. |

### 팀 추가 요구사항 예시
- 예: 동일 체크섬 원본 재수집 시 중복 여부를 로그에 기록한다.
- 예: 모든 격리 데이터는 오류 코드와 원본값을 함께 저장한다.

### 팀 추가 요구사항
- 
- 
- 

## 6. 핵심 데이터 관계

| From | To | 의미 |
|---|---|---|
| `MANAGER_EMP_NO` | `EMP_NO` | 영역 관리자 → 직원 마스터 |
| `PARENT_AREA_ID` | `AREA_ID` | 하위 영역 → 상위 영역 |

추가 관계:
- 

## 7. 팀이 반드시 합의할 사항

> 상세 작성은 관련 문서에서 진행한다.

- 16개 컬럼의 업무 의미
- Legacy → 표준 컬럼명
- 타입
- PK(Primary Key, 기본키) / FK(Foreign Key, 외래키)
- NULL 허용 여부
- 도메인/코드값
- 날짜/Boolean 변환 기준
- `REG_DT` 기준 소스와 기준 시점
- Silver 출력 스키마
- Gold Feature 정의
- 예외 및 격리 정책

## 8. 미결사항

`TBD`는 **To Be Determined(추후 결정)** 의 약자다.

| ID | 미결사항 | 확인할 내용 | 상태 |
|---|---|---|---|
| TBD-001 | `REG_DT` 기준 | 기준 소스와 기준 시점 확인 | Open |
| TBD-002 |  |  |  |

## 9. 관련 문서

- `as_is_profiling.md`
- `data_standard_dictionary.md`
- `data_processing_rules.md`
- `to_be_medallion_model.md`
- `gold_feature_spec.md`
- `retrospective.md`
