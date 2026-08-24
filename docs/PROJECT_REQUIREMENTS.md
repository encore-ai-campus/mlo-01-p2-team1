# 2nd Project Requirements

## 1. 프로젝트 개요

- 프로젝트명: 데이터 표준화 및 AI Ready Data 구축 프로젝트
- 수행 기간: 2026-08-27 ~ 2026-08-28
- 수행 인원: 4명
- 핵심 목표: 레거시 원천 데이터를 수집·보존하고, 표준화·정제 후 AI 활용 가능한 Gold 데이터셋으로 변환
- 핵심 아키텍처: Bronze → Silver → Gold
- 최종 결과물: AI Ready Data 및 이를 재현·검증할 수 있는 코드/문서/로그

---

## 2. 공식 데이터 범위

공식 평가 기준 데이터는 CSV 4종, 총 104,000행이다.

| 파일 | 행 수 | 컬럼 수 | 역할 |
|---|---:|---:|---|
| `biz_employee_master.csv` | 3,000 | 6 | 직원 마스터 |
| `biz_meta_area_50000.csv` | 50,000 | 5 | 업무 영역 마스터 |
| `biz_meta_area_join_ready.csv` | 50,000 | 9 | 직원·상위 영역 정보가 결합된 대조용 데이터 |
| `biz_meta_area_parent_lookup.csv` | 1,000 | 4 | 최상위 영역 조회 데이터 |
| 합계 | 104,000 | 24 | 파일별 컬럼 수 합계 |

- 파일 전체 컬럼 수 합계: 24개
- 중복 제거 기준 고유 필드: 16개
- `biz_legacy_integrated.csv`는 공식 평가 기준선에 포함되지 않으며 별도 레거시/확장 검증 데이터로 취급

### 주요 관계 후보

- `MANAGER_EMP_NO → EMP_NO`
- `PARENT_AREA_ID → AREA_ID`
- `biz_meta_area_join_ready.csv`는 표준 변환 및 조인 결과 대조용 기준 데이터

---

## 3. 내부 API / Bronze Relay

내부망 기반 증분 데이터 피드가 제공된다.

- API 주소 예시: `http://192.168.0.51:8000`
- 내부망 전용
- API 키 기반 인증
- 키 변경 주기
  - 23:00: 다음 키 공지
  - 00:00: 신규 키 적용
  - +24시간: 만료
- 데이터 갱신 주기: 4분
- 증분 피드 방식
- 100건 단위 조회
- Signed Cursor 사용

### 수집 원칙

수집 단계에서는 원천 데이터를 정제하지 않는다.

- 원본 값 유지
- 공백 유지
- 대소문자 유지
- 비정상 표현 유지
- 인코딩/오류 형태 유지
- 원본과 수집 사실을 함께 보존

---

## 4. Medallion Architecture

### 4.1 Bronze

#### 목적

원천 데이터를 변형하지 않고 재현 가능한 상태로 보존한다.

#### 저장 대상

- CSV / JSON / HTML 등 원본
- 내부 API 응답 원문
- 수집 메타데이터
- 실행 정보
- 체크섬
- 실패 또는 파싱 불가 원본

#### 필수 메타데이터

- `run_id`
- `source_name`
- `source_uri`
- `collected_at`
- `ingest_date`
- `raw_path`
- `content_type`
- `file_size_bytes`
- `checksum_sha256`
- `http_status`
- `retry_count`
- `crawler_version`
- `status`

#### 권장 구조

```text
data/
└── bronze/
    └── {source_name}/
        └── ingest_date=YYYY-MM-DD/
            └── run_id={run_id}/
                ├── raw/
                │   └── {original_file}
                └── manifest.json
```

#### 완료 조건

- 공식 CSV 4종의 원본 기준선 재현
- 총 104,000행 확인
- 원본과 manifest가 `run_id`로 연결
- 체크섬 / 수집 시각 / 원천 식별자 / 코드 버전 기록
- 누락 또는 실패 데이터가 있으면 성공 처리하지 않음

---

### 4.2 Silver

#### 목적

Bronze 데이터를 표준 사전 기준으로 정규화하고 품질 검증을 통과시킨다.

#### 주요 처리

- 16개 고유 필드 표준화
- Legacy → 표준 컬럼명 매핑
- 문자열 공백 정리
- 전각 공백 정리
- 대소문자 통일
- 날짜 표현 통일
- Boolean 표현 통일
- 타입 변환
- PK 중복 검사
- 필수값 결측 검사
- FK orphan 검사
- 도메인 위반 검사
- Join 정합성 검사
- 정상 데이터 / 격리 데이터 분리

#### 표준화 예시

- `EMP_NO → employee_id`
- `ACTIVE_YN → is_active`

#### 권장 모델

- `silver_employee`
- `silver_area`
- `silver_area_join_reference`
- `silver_parent_area`

#### 품질 게이트

- PK 중복: 0건
- FK orphan: 0건
- 도메인 위반: 0건
- join_ready 대조 불일치: 0건
- 날짜·타입 변환 실패: 0건
- 필수 컬럼 결측: 0건 또는 승인된 예외만 존재

#### 주의사항

`biz_meta_area_parent_lookup.csv`의 `REG_DT` 1,000건 값 차이는 임의로 한쪽 값을 선택하지 않는다.

반드시 다음을 먼저 결정한다.

- 기준 소스
- 기준 시점
- 처리 규칙
- 변경 전/후 건수
- 회귀 검증 결과

---

### 4.3 Gold

#### 목적

Silver 데이터를 기반으로 분석/서비스/AI 활용 목적의 2차 데이터셋을 생성한다.

#### 필수 산출 모델

- 직원 차원 데이터
- 영역 차원 데이터
- `area_manager_features`

#### 2차 컬럼 후보

- 직원 재직 기간
- 관리자별 담당 영역 수
- 영역 계층 깊이
- 최상위 영역 식별자
- 상위 영역 보유 여부
- 관리자 재직 여부 + 영역 속성 결합 피처

#### 필수 원칙

- Gold는 Silver 데이터만 입력으로 사용
- 원천 CSV를 직접 참조하지 않음
- 모든 파생 컬럼에 출처 컬럼과 계산식 명시
- `as_of_date` 저장
- 데이터 누수 여부 검증
- 타입 / 허용 범위 / 결측 처리 정의
- 동일 입력 재실행 시 동일 결과 보장

---

## 5. 1일차 작업

### 목표

분석 · 표준화 · TO-BE 설계 완료

### 작업

1. 데이터 이해
2. 품질 진단
3. 표준화 설계
4. TO-BE 설계

### 완료 증빙

- 데이터 인벤토리
- AS-IS 프로파일링 리포트
- AI 데이터 표준 사전
- Medallion TO-BE 명세서

### 1일차 종료 전 필수 확인

- CSV 4종 행 수 / 컬럼 수 기준선 문서화
- PK/FK 후보 확정
- join_ready 대조 방식 정의
- Legacy → 표준 컬럼 매핑 확정
- 타입 / 도메인 / 코드 규칙 확정
- `REG_DT` 기준 소스·시점 결정 방법 정의
- Bronze 전달 계약 / 저장 경로 정의

---

## 6. 2일차 작업

### 목표

변환 · 검증 · 패키징 완료

### 작업

1. Bronze 적재
2. Silver 표준화
3. Gold 생성
4. 검증 자동화
5. `REG_DT` 이슈 반영
6. 회귀 검증
7. README 및 발표자료 정리
8. 최종 패키징

### 2일차 종료 전 필수 확인

- PK 중복 0건
- FK orphan 0건
- join_ready 대조 불일치 0건
- 예외 발생 시 사유 / 건수 / 처리 방식 기록
- Gold 계산식과 Silver 계보 추적 가능
- README만으로 재실행 가능
- 코드 / 문서 / 데이터 / 로그 / 발표자료 / 회고 제출 가능 상태

---

## 7. 필수 산출물

### 문서

- 데이터 인벤토리
- AS-IS 데이터 프로파일링 리포트
- AI 데이터 표준 사전
- Medallion TO-BE 명세서
- README
- 회고 문서
- 발표자료

### 코드

- 수집 / 크롤링 코드
- Bronze 적재 코드
- Silver 표준화 코드
- Gold 생성 코드
- 검증 스크립트

### 데이터

- Bronze 원본 데이터셋
- Silver 표준화 데이터셋
- Gold AI Ready 데이터셋
- Quarantine 데이터

### 로그 / 증빙

- 수집 로그
- 변환 로그
- 품질 검증 로그
- 이슈 처리 기록
- 회귀 검증 결과

---

## 8. 평가 기준

### AS-IS 분석 · 표준화: 50점

필수 산출물

- 데이터 프로파일링 리포트
- AI 데이터 표준 사전

핵심 평가 요소

- 현행 문제 진단
- 단어 / 용어 / 도메인 정의
- 표준 컬럼명 적용

### TO-BE 모델링 · 검증: 50점

필수 산출물

- Medallion TO-BE 명세서
- 변환 데이터셋
- 정합성 검증 결과

핵심 평가 요소

- AI 학습 적합성
- 오류 없는 변환
- 정합성 및 품질 검증

---

## 9. 권장 Repository 구조

```text
project/
├── README.md
├── docs/
│   ├── as_is_profiling.md
│   ├── data_standard_dictionary.md
│   ├── to_be_medallion_model.md
│   └── retrospective.md
├── src/
│   ├── ingest_or_crawler/
│   ├── bronze/
│   ├── silver/
│   └── gold/
├── tests/
├── logs/
├── data/
│   ├── bronze/
│   ├── silver/
│   ├── gold/
│   └── quarantine/
└── presentation/
```

---

## 10. 팀 공통 결정 사항

역할 분담 전에 아래 항목을 4명이 공통으로 확정한다.

- 16개 고유 필드의 업무 의미
- Legacy 컬럼명
- 표준 컬럼명
- 타입
- 도메인
- PK / FK
- Null 처리 규칙
- 코드값 변환 규칙
- 날짜 변환 규칙
- 격리 기준
- Silver 출력 스키마
- Gold 입력 스키마
- Gold feature 정의
- `as_of_date`
- `REG_DT` 기준 규칙
- 프로젝트 디렉터리 구조
- 로그 포맷
- 실행 명령

공통 규격이 확정된 이후 병렬 개발을 진행한다.

---

## 11. 4인 병렬 작업 예시

| 담당 | 주요 책임 |
|---|---|
| 1 | 내부 API / 수집 / Bronze |
| 2 | 표준화 / Silver |
| 3 | Gold / AI Ready Data |
| 4 | 품질검증 / 테스트 / 통합 |

문서는 각 담당 코드 영역과 연계해서 분담하되, 최종 표준 사전과 공통 규칙은 팀 전체가 공유한다.

---

## 12. AI / Codex 활용 원칙

AI는 반복 작업과 초안 생성에 활용하되 최종 판단은 사람이 수행한다.

### AI에 맡기기 적합한 작업

- 문서 초안
- 컬럼 매핑표 초안
- 정제 코드 초안
- 검증 코드 초안
- README 초안
- 로그 분석
- 테스트 케이스 초안

### 사람이 반드시 결정/검토할 항목

- 컬럼의 실제 업무 의미
- 표준명 승인
- 타입 / 도메인 승인
- PK / FK 관계
- 예외 처리 기준
- `REG_DT` 기준 소스와 시점
- Gold feature 의미
- 데이터 누수 여부
- AI 생성 코드 및 문서 최종 검토

### 공통 원칙

> AI generates; humans decide and validate.

---

## 13. Definition of Done

다음 조건을 모두 만족해야 프로젝트 완료로 본다.

- 공식 CSV 4종 / 104,000행 기준선 재현
- 16개 고유 필드 표준 사전 존재
- Legacy → 표준 컬럼 매핑 존재
- Bronze / Silver / Gold 책임 분리
- 데이터 계보 추적 가능
- PK 중복 기준 통과
- FK orphan 기준 통과
- 조인 불일치 기준 통과
- 주요 도메인 오류 기준 통과
- `REG_DT` 처리 규칙과 근거 기록
- Gold 차원 및 `area_manager_features` 명세 완료
- Bronze 원본 및 메타데이터 재현 가능
- README 명령만으로 재실행 가능
- 코드 / 문서 / 데이터 / 로그 / 발표자료 / 회고 제출 가능
