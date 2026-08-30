# Gold Feature 명세 v1.0

> AI Ready Data에 포함할 Gold Feature의 의미, 출처, 계산식, 기준 시점을 정의한다.

## 1. Gold 데이터 Grain

**Grain(그레인)** 은 "한 행이 무엇을 의미하는가"를 뜻한다.

### 작성 예시
- 직원 차원: 직원 1명당 1행
- 영역 차원: 업무 영역 1개당 1행
- `area_manager_features`: 영역 1개 + 관리자 기준 1행

### 팀 확정
- 직원 차원 Grain:
- 영역 차원 Grain:
- `area_manager_features` Grain:

## 2. Feature 후보

가이드 예시:
- 직원 재직 기간
- 관리자별 담당 영역 수
- 영역 계층 깊이
- 최상위 영역 ID
- 상위 영역 보유 여부
- 관리자 재직 여부 + 영역 속성 결합 Feature

## 3. Feature 정의

### 작성 예시

| Feature | 업무 의미 | Source | 계산식 | 타입 | NULL 처리 | 기준 시점 |
|---|---|---|---|---|---|---|
| `manager_area_count` | 관리자 담당 영역 수 | `silver_area.manager_employee_id` | 관리자별 영역 수 집계 | integer | 0 | `as_of_date` |
| `has_parent_area` | 상위 영역 존재 여부 | `silver_area.parent_area_id` | NULL 아니면 true | boolean | false | `as_of_date` |
| `area_depth` | 계층 깊이 | `silver_area` | 최상위부터 깊이 계산 | integer | 팀 결정 | `as_of_date` |

### 팀 작성

| Feature | 업무 의미 | Source | 계산식 | 타입 | NULL 처리 | 기준 시점 |
|---|---|---|---|---|---|---|
|  |  |  |  |  |  |  |

## 4. AI Ready 검증

- Feature 의미가 명확한가?
- Source를 Silver까지 추적 가능한가?
- 계산식이 문서화되어 있는가?
- 타입과 허용 범위가 정의되어 있는가?
- NULL 처리 방식이 정의되어 있는가?
- `as_of_date`가 존재하는가?
- 미래 정보가 섞이지 않았는가?
- 데이터 누수가 없는가?

## 5. Feature 분포 검증

### 작성 예시

| Feature | 최소 | 최대 | 평균/중앙값 | 이상치 여부 |
|---|---:|---:|---:|---|
| `manager_area_count` | 1 | 30 | 4.2 | 검토 |

### 팀 작성

| Feature | 최소 | 최대 | 평균/중앙값 | 이상치 여부 |
|---|---:|---:|---:|---|
|  |  |  |  |  |
