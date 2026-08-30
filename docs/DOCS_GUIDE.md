# 문서 구성 안내 v1.0

> 이 문서는 `docs/` 폴더 안의 각 문서가 어떤 목적을 가지는지 빠르게 확인하기 위한 안내 문서입니다.

## 문서 목록

| 파일명 | 문서명 | 목적 | 주로 작성하는 시점 |
|---|---|---|---|
| `BRD.md` | BRD (Business Requirements Document, 업무 요구사항 정의서) | 프로젝트의 목적, 범위, 핵심 업무 요구사항과 팀 공통 의사결정 기준을 정리 | 프로젝트 초반 |
| `as_is_profiling.md` | AS-IS 데이터 프로파일링 리포트 | 원천 데이터의 현재 상태, 건수, 결측, 중복, 이상 패턴, PK/FK 및 조인 정합성 등을 분석 | 1일차 초반 |
| `data_standard_dictionary.md` | AI 데이터 표준 사전 | 16개 고유 필드의 업무 의미, 표준 컬럼명, 타입, 키, 도메인, 필수 여부 등을 확정 | 1일차 |
| `data_processing_rules.md` | 데이터 처리 및 예외 규칙 | 공백, 대소문자, ID, 날짜, Boolean, 도메인, 결측, `REG_DT`, Quarantine(격리) 처리 규칙을 정의 | 1일차 |
| `to_be_medallion_model.md` | TO-BE Medallion Model 명세 | Bronze → Silver → Gold 구조, 각 레이어의 책임, 저장 방식, 입출력 계약과 데이터 계보를 정의 | 1일차 후반 |
| `gold_feature_spec.md` | Gold Feature 명세 | AI Ready Data의 Grain(한 행의 기준), Feature의 업무 의미, Source, 계산식, 타입, 기준 시점을 정의 | 1일차 후반~2일차 |
| `retrospective.md` | 프로젝트 회고 | 잘된 점, 어려웠던 점, 해결 방법, AI/Codex 활용, 다시 한다면 바꿀 점을 기록 | 프로젝트 종료 시 |
| `PROJECT_REQUIREMENTS.md` | 프로젝트 요구조건 정리 | 강사 가이드에서 제시한 전체 요구조건, 일정, 평가 기준, 산출물, 완료 조건을 요약 | 프로젝트 시작 전 |
| `README.md` | 프로젝트 실행 안내 | 프로젝트 소개, 환경 구성, 실행 순서, 검증 방법, 디렉터리 구조를 안내 | 개발 중 보완, 종료 전 확정 |

---

## 문서 간 관계

```text
PROJECT_REQUIREMENTS.md
        ↓
      BRD.md
        ↓
 ┌───────────────┬───────────────────────┐
 ↓               ↓                       ↓
AS-IS         데이터 표준 사전       데이터 처리 규칙
프로파일링          ↓                       ↓
 └──────────────→ TO-BE Medallion Model ←─┘
                         ↓
                  Gold Feature 명세
                         ↓
                       구현
                         ↓
                    README / 회고
```

---

## 각 문서에서 결정하는 핵심 질문

### `BRD.md`
- 왜 이 프로젝트를 하는가?
- 어디까지 하는가?
- 무엇을 반드시 만족해야 하는가?
- 아직 결정되지 않은 핵심 사항은 무엇인가?

### `as_is_profiling.md`
- 원천 데이터는 실제로 어떤 상태인가?
- 결측, 중복, 공백, 날짜 형식, 코드값 문제는 몇 건인가?
- PK(Primary Key, 기본키)와 FK(Foreign Key, 외래키) 관계는 정상인가?
- 어떤 데이터 품질 문제를 Silver에서 해결해야 하는가?

### `data_standard_dictionary.md`
- 각 Legacy 컬럼은 업무적으로 무슨 뜻인가?
- 표준 컬럼명을 무엇으로 정할 것인가?
- 타입은 무엇인가?
- PK/FK인가?
- NULL을 허용하는가?
- 어떤 값만 허용할 것인가?

### `data_processing_rules.md`
- 비정상 표현을 어떤 규칙으로 고칠 것인가?
- 공백과 대소문자는 어떻게 처리할 것인가?
- 날짜와 Boolean 값은 어떤 형식으로 통일할 것인가?
- 잘못된 데이터는 언제 Quarantine(격리)할 것인가?
- `REG_DT` 불일치는 어떤 기준으로 처리할 것인가?

### `to_be_medallion_model.md`
- Bronze, Silver, Gold가 각각 무엇을 담당하는가?
- 각 레이어가 다음 레이어에 어떤 형태로 데이터를 넘기는가?
- 데이터가 어디서 와서 어디로 갔는지 어떻게 추적할 것인가?

### `gold_feature_spec.md`
- Gold 데이터 한 행은 무엇을 의미하는가?
- 어떤 AI Feature를 만들 것인가?
- Feature는 어느 Silver 컬럼에서 오는가?
- 계산식과 기준 시점은 무엇인가?
- 데이터 누수 가능성은 없는가?

### `retrospective.md`
- 무엇이 잘됐는가?
- 무엇이 어려웠는가?
- 어떻게 해결했는가?
- AI/Codex는 어디에 활용했고 사람이 무엇을 검토했는가?
- 다음 프로젝트에서는 무엇을 바꿀 것인가?

---

## 추천 작성 순서

1. `PROJECT_REQUIREMENTS.md` 확인
2. `BRD.md`에서 범위와 핵심 요구사항 합의
3. `as_is_profiling.md` 작성
4. `data_standard_dictionary.md` 작성
5. `data_processing_rules.md` 작성
6. `to_be_medallion_model.md` 확정
7. `gold_feature_spec.md` 작성
8. 구현 및 품질 검증
9. `README.md` 최종화
10. `retrospective.md` 작성

---

## 폴더 예시

```text
docs/
├── DOCS_GUIDE.md
├── PROJECT_REQUIREMENTS.md
├── BRD.md
├── as_is_profiling.md
├── data_standard_dictionary.md
├── data_processing_rules.md
├── to_be_medallion_model.md
├── gold_feature_spec.md
└── retrospective.md
```
