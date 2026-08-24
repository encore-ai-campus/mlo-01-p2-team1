# TO-BE Medallion Model 명세 v1.0

> Bronze → Silver → Gold의 목표 구조와 레이어 간 계약을 정의한다.

## 1. 전체 구조

```text
원천 CSV / 내부 API
        ↓
Bronze
원본 + 수집 메타데이터
        ↓
Silver
표준화 + 품질 정제 + 격리
        ↓
Gold
직원 차원 + 영역 차원 + area_manager_features
```

## 2. Bronze

### 책임
- 원본 보존
- `run_id` 기록
- 수집 시각 기록
- SHA-256 체크섬
- 원천 정보 및 실행 상태 기록

### 금지
- 컬럼명 표준화
- 값 수정
- 조인/집계
- Feature 생성

### 팀 결정
- 원본 저장 포맷:
- 저장 경로:
- manifest 구조:
- cursor 저장 방식:
- API Key 관리 방식:

## 3. Silver

### 권장 모델
- `silver_employee`
- `silver_area`
- `silver_area_join_reference`
- `silver_parent_area`

### 책임
- 표준명 적용
- 타입 변환
- 공백/대소문자/날짜/Boolean 정규화
- PK/FK/도메인/결측 검증
- 정상 데이터와 격리 데이터 분리

### 팀 결정
- Silver 저장 포맷:
- 파티션:
- 출력 경로:

## 4. Gold

### 필수 모델
- 직원 차원
- 영역 차원
- `area_manager_features`

### 책임
- Silver만 입력으로 사용
- 조인/집계/파생 Feature 생성
- `as_of_date` 기준 시점 저장
- 데이터 누수 검토

## 5. Bronze → Silver 인터페이스

### 작성 예시
- 입력: Bronze raw + manifest
- 필수 추적값: `run_id`, `source_name`
- 원본 컬럼 유지
- Silver는 Bronze 원본을 기준으로 변환

### 팀 확정
- 입력 위치:
- 파일/테이블 포맷:
- 필수 메타데이터:
- 실행 단위:

## 6. Silver → Gold 인터페이스

### 작성 예시

```text
silver_employee
- employee_id: string
- hire_date: date
- is_active: boolean

silver_area
- area_id: string
- parent_area_id: string/null
- manager_employee_id: string/null
```

### 팀 확정

```text
silver_employee
-

silver_area
-

silver_area_join_reference
-

silver_parent_area
-
```

## 7. 데이터 계보

### 작성 예시
`EMP_NO → silver_employee.employee_id → Gold manager_employee_id → area_manager_features`

### 팀 작성
- 
- 
- 

## 8. 완료 조건
- Bronze/Silver/Gold 책임이 겹치지 않는다.
- Gold가 원천 CSV를 직접 참조하지 않는다.
- 각 출력 스키마가 문서와 일치한다.
- 동일 입력으로 재실행 시 동일 결과가 나온다.
