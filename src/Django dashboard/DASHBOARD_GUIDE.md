# Data Pipeline Dashboard 가이드

## 1. 목적과 화면

이 로컬 Django 애플리케이션은 Legacy 수집 → 표준화 → 정규화 → MySQL accepted/MongoDB rejected 적재 → Gold manager feature 흐름을 관제합니다.

| 화면 | URL | 역할 |
| --- | --- | --- |
| Main | `/dashboard/` | 전체 파이프라인, DB 간 대사와 경고 통합 |
| MySQL | `/dashboard/mysql/` | accepted 행과 엔터티별 적재 완전성 |
| MongoDB | `/dashboard/mongodb/` | rejected 행, 오류 발생과 반려 사유 |
| Gold | `/dashboard/gold/` | manager assignment feature와 조직·업무영역 분석 |

상단 메뉴로 네 화면을 이동하며, Main의 Three.js 파이프라인과 Gold의 manager constellation은 동일한 미래형 지휘통제실 콘셉트를 사용합니다.

## 2. 데이터 소스와 집계 기준

### Pipeline과 rejected

- MySQL `dashboard_pipeline_run_view`의 **전체 run 행**을 기본 KPI에 합산합니다.
- 그 전체 `run_id` 집합과 정확히 일치하는 MongoDB 문서만 `standardization_rejected`, `normalization_rejected`에서 조회합니다.
- MongoDB 조회는 run_id를 최대 1,000개씩 나누어 `$in` 조건으로 수행합니다.
- MySQL에 없는 MongoDB run_id는 집계에서 제외합니다.
- 최신 run_id는 Main의 `CURRENT BATCH`, freshness와 최신 배치 경고를 위한 메타데이터일 뿐 전체 KPI의 필터가 아닙니다.
- MySQL과 MongoDB 상세 service에 `run_id`를 명시하면 해당 단일 배치 계약도 유지됩니다.

### Gold

- Gold는 MySQL `dashboard_gold_manager_assignment_view`의 현재 manager snapshot을 읽습니다.
- Gold View에는 run_id가 없으므로 pipeline run 대사 대상이 아니라 독립된 `(View snapshot, manager_id)` grain입니다.
- View 이름은 `GOLD_DASHBOARD_VIEW` 환경변수로 재정의할 수 있습니다.

## 3. Live 검증 스냅샷

2026-08-28 구현 검증 시점의 읽기 전용 조회 결과입니다. 배치가 계속 적재되므로 숫자는 실행 시점마다 증가할 수 있습니다.

| 항목 | 검증값 |
| --- | ---: |
| MySQL pipeline run | 105개 |
| 전체 Legacy raw | 28,707행 |
| Final accepted / MySQL stored | 25,456행 |
| MongoDB rejected | 3,251행 |
| 전체 행 대사 | `25,456 + 3,251 = 28,707` |
| MongoDB run별 대사 불일치 | 없음 |
| Gold View | `dashboard_gold_manager_assignment_view` |
| Gold manager | 14명 |
| Gold source status | `SYNCHRONIZED` |

Gold View의 실제 컬럼 12개가 repository 계약과 일치하고 브라우저 context까지 반환되는 것을 확인했습니다.

## 4. Main Dashboard

| 영역 | 지표와 계산 |
| --- | --- |
| Ingestion Matrix | 전체 run의 `Σ raw_row_count` |
| Hourly Ingestion | 최근 60개 run을 KST 시간 단위로 합산한 raw 수집량 |
| Process Throughput | 최근 run의 raw와 Final accepted 추이 |
| Current Batch | 표시용 최신 MySQL run_id |
| Global Load Rate | `(Σ Final accepted + 실제 MongoDB rejected 행) / Σ raw` |
| MySQL Gateway | `Σ Final accepted / Σ raw` |
| MongoDB Gateway | `실제 rejected 문서 / Σ raw` |
| Gold Gateway | manager loaded/target 및 Gold 화면 이동 |
| Load Distribution | Final accepted, MongoDB rejected, 미대사 행 |
| Rejection Signals | MongoDB `errors[]` 오류 코드별 발생 건수 Top 5 |
| 3D Pipeline | Legacy → Standardization → Normalization → Gold/MySQL/MongoDB 흐름 |

manager/top area/area 엔터티 건수는 원천 행과 단위가 다르므로 Global Load Rate에 더하지 않습니다.

## 5. MySQL Dashboard

MySQL 기본 화면의 KPI는 전체 run 합계입니다. 차트는 최근 60개 run을 사용해 약 3시간 범위를 보여줍니다.

| 영역 | 지표와 계산 |
| --- | --- |
| Standard Accepted | `Σ standardization_accepted / Σ raw` |
| Normalized Accepted | `Σ final_accepted / Σ standardization_accepted` |
| MySQL Load Rate | `Σ final_accepted / Σ raw` |
| Data Freshness | 최신 run의 updated/completed/started 시각 |
| Load Rate Telemetry | KST 정각 기준 30분 버킷의 `Σ final_accepted / Σ raw` |
| Acceptance Orbit | Final accepted, 단계별 rejected, 미대사 |
| Accepted Data Channel | raw → standard accepted → final accepted → MySQL loaded |
| Table Load Matrix | manager/top_business_area/business_area별 `loaded / target` |
| Stage Volume | raw, standard accepted, final accepted, MySQL stored 행 |
| Table Integrity | 엔터티별 loaded/target/rate/status |
| Recent Load Batches | 최근 run_id, Final accepted, 실행시간과 상태 |

30분 버킷은 `[HH:00, HH:30)`, `[HH:30, 다음 HH:00)`로 나누며 run별 퍼센트의 단순 평균이 아니라 버킷 내 건수를 먼저 합산한 가중 비율입니다.

`MYSQL LOADED`는 원천 행과 동일 단위인 `final_accepted_count`입니다. manager/top area/area의 합계는 한 원천 행에서 여러 엔터티가 만들어질 수 있어 raw보다 커질 수 있으므로 `entity_load`로 분리해 Table Load Matrix/Integrity에서만 사용합니다.

검증 스냅샷:

- MySQL stored: `25,456 / 28,707 = 88.7%`
- 엔터티 적재 완전성: `65,184 / 65,184 = 100.0%`
- 30분 telemetry 라벨 예: `12:00`, `12:30`, `13:00`, `13:30`, `14:00`

## 6. MongoDB Dashboard

MongoDB 기본 화면은 MySQL View의 전체 run_id 집합과 일치하는 두 rejected 컬렉션을 합산합니다. Rejected Velocity는 최근 12개 run을 표시합니다.

| 영역 | 지표와 계산 |
| --- | --- |
| Standard Rejected | 표준화 rejected 문서 / 전체 raw |
| Normalized Rejected | 정규화 rejected 문서 / 전체 standard accepted |
| MongoDB Load Rate | 실제 rejected 문서 / MySQL 예상 rejected |
| Top Error Signal | `errors[]` 오류 발생 건수 1위 |
| Rejection Analysis | 오류 코드별 발생 건수 막대 |
| Rejected Orbit | 표준화/정규화 rejected 행 분포 |
| Collection Load Matrix | 컬렉션별 실제/예상 적재율 |
| Reason Code Matrix | 오류 코드, 한글 라벨, 발생 건수와 오류 내 비율 |
| Recent Stream | 최신 오류 발생 내역 최대 20개 |

MongoDB 문서 1개는 반려 행 1건이고, 문서 안 `errors[]` 각 항목은 오류 발생 1건입니다. 한 행에 오류가 3개면 반려 행 1건, 오류 발생 3건으로 집계하므로 오류 사유는 합계 100%를 전제로 하지 않는 막대 차트로 표시합니다.

## 7. Gold Medallion Dashboard

### View 계약

`dashboard_gold_manager_assignment_view`가 다음 필드를 제공합니다.

```text
manager_id
manager_department_name
manager_position_name
manager_active_flag
manager_tenure_days
managed_area_count
managed_top_area_count
managed_parent_area_count
top_level_area_count
average_area_age_days
max_area_age_days
cross_top_area_flag
```

`GoldRepository`는 View를 읽고 문자열, 숫자, 0/1 flag를 정규화합니다. `GoldDashboardService`는 manager grain KPI, 조직별 집계, chart/3D payload와 warning을 계산합니다.

### 화면 지표와 기능

| 영역 | 내용 |
| --- | --- |
| Manager Universe | 전체 manager 수 |
| Active Rate | active manager 수와 비율 |
| Average Area Load | manager당 평균 담당 Area |
| Cross-Top | 복수 Top Area 담당 manager |
| Unassigned | 담당 Area가 0인 manager |
| Average Tenure | 평균 근속일 |
| 3D Constellation | manager node 크기를 담당 Area 수로 표현, 자동 orbit/drag/zoom/선택 |
| Active Orbit | Active/Inactive 도넛 |
| Workload Matrix | 근속연수 × 담당 Area scatter |
| Feature Radar | 전체 평균과 고부하 manager 비교 |
| Department Load | 부서별 평균 담당 Area |
| Assignment Frequency | 담당 Area 수 분포 |
| Signal Queue | 미배정, 고부하, Cross-Top manager |
| Feature Grid | 검색·부서·직급·상태 필터, CSV export, 상세 drawer |

Gold 경고는 manager_id 중복, 음수/범위 오류, 계층 건수 모순, cross-top flag 불일치, 평균 Area 연령이 최대 연령보다 큰 경우와 View 조회/빈 데이터 상태를 다룹니다.

## 8. 레이어와 데이터 흐름

```text
.env
  ├─ MYSQL_* ──> PipelineRepository ──────────────┐
  │                                               ├─> Main/MySQL Services
  ├─ MONGO_* ──> MongoRepository ────────────────┘
  │
  └─ GOLD_DASHBOARD_VIEW ─> GoldRepository ─> GoldDashboardService

Service ─> Django presentation/view ─> Template context/JSON
        ─> Three.js + ECharts + HTML/CSS/Vanilla JS
```

- `presentation`: URL, request/response, template 선택
- `repository`: DB 조회와 타입 정규화, DB 예외를 repository 예외로 변환
- `service`: KPI, 전체-run 대사, warning, 화면 context 조립
- `templates`: 서버 context와 JSON payload 출력
- Browser JavaScript: Three.js 장면, ECharts와 화면 인터랙션 렌더링

Main 전용 repository는 없습니다. `MainDashboardService`가 PipelineRepository의 전체 run과 MongoRepository의 일치 run_id 문서를 조합합니다. Gold는 독립 repository/service 경계를 유지합니다.

## 9. Warning Sign

전체 상태 우선순위는 `CRITICAL > WARNING > NORMAL`입니다. 종료된 pipeline 배치만 MySQL–MongoDB 단계별 건수 대사를 수행해 RUNNING 중간 상태의 오경보를 막습니다.

| 분류 | 주요 조건 |
| --- | --- |
| 배치 | FAILED, PARTIAL_FAILURE, 6/9분 이상 지연, 완료시각 누락·역전 |
| MySQL | accepted/rejected 대사 불일치, 엔터티 target/loaded 불일치, rejected 급증 |
| MongoDB | errors 없는 문서, 오류 코드 형식, 중복 문서, 오류 코드 급증 |
| run 대사 | 각 MySQL run의 예상 rejected와 MongoDB 실제 문서 수 불일치 |
| Gold | View empty/조회 실패, manager 중복, feature·계층·flag 모순 |

Warning tray는 앞의 3개 메시지를 표시하고 헤더의 `N SIGNALS`가 전체 경고 개수를 표시합니다.

## 10. 기술과 로컬 운영

- Backend: Django 5.2, mysqlclient, PyMongo, python-dotenv
- Visualization: Three.js/WebGL 2, Apache ECharts 6.1
- UI: Django Template, HTML, CSS, Vanilla JavaScript
- 라이브러리는 `datapipeline/static/datapipeline/vendor/`에 로컬 고정되어 오프라인에서도 렌더링됩니다.

`.env` 핵심 항목:

```dotenv
DASHBOARD_DATA_MODE=live
MYSQL_*=...
MONGO_*=...
GOLD_DASHBOARD_VIEW=dashboard_gold_manager_assignment_view
```

환경변수 변경 후 Django 서버를 재시작해야 전역 service/repository 인스턴스가 새 설정을 사용합니다. live 모드의 조회 실패는 sample 값으로 숨기지 않고 `MYSQL_UNAVAILABLE`, `MONGODB_UNAVAILABLE`, `GOLD_VIEW_UNAVAILABLE`로 표시합니다.

Footer의 LATENCY/UPTIME/SECURE CHANNEL 문구는 현재 실측 모니터링 값이 아니라 HUD 표현입니다.
