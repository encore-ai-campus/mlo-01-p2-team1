# Data Pipeline Dashboard 가이드

## 1. 목적과 범위

이 대시보드는 Legacy 데이터 수집부터 표준화, 정규화, MySQL accepted 적재, MongoDB rejected 적재까지의 상태를 한 화면에서 관제하기 위한 로컬 Django 애플리케이션입니다.

화면은 다음 세 가지로 나뉩니다.

- Main Dashboard: 파이프라인 전체 흐름과 통합 상태
- MySQL Dashboard: accepted 데이터와 엔터티별 적재 상태
- MongoDB Dashboard: rejected 행, 오류 발생 건수와 반려 사유

상단 메뉴 또는 중앙 3D 데이터베이스 노드를 통해 세 화면 사이를 이동할 수 있습니다.

## 2. Live 데이터 확인 결과

확인 시점: **2026-08-28 09:26 KST**  
확인 URL: `http://127.0.0.1:8000/dashboard/`

실행 중인 Django 서버가 세 페이지 요청마다 아래의 동일한 배치를 반환하는 것을 확인했습니다.

| 항목 | 확인값 |
| --- | ---: |
| 데이터 모드 | `LIVE DATA` |
| 최신 `run_id` | `20260827T213314+0900-3be3f1c6` |
| 배치 상태 | `SUCCESS` |
| Legacy 원천 행 | 23,612 |
| 표준화 accepted | 14,998 |
| 표준화 rejected | 8,614 |
| Final accepted | 11,045 |
| 정규화 rejected | 3,953 |
| MongoDB rejected 문서 합계 | 12,567 |
| 행 기준 전체 대사율 | 100.0% |

단계별 대사도 일치합니다.

```text
23,612 raw
= 14,998 standardization accepted + 8,614 standardization rejected

14,998 standardization accepted
= 11,045 final accepted + 3,953 normalization rejected

23,612 raw
= 11,045 final accepted + 12,567 MongoDB rejected rows
```

MySQL에서 제공한 예상 rejected와 MongoDB의 실제 문서 수도 일치합니다.

| 단계 | MySQL 예상 | MongoDB 실제 | 결과 |
| --- | ---: | ---: | --- |
| 표준화 rejected | 8,614 | 8,614 | 일치 |
| 정규화 rejected | 3,953 | 3,953 | 일치 |

브라우저 콘솔에서 Three.js 및 ECharts 관련 오류도 발견되지 않았습니다. 따라서 **현재 실행 중인 Django 서버 기준으로 MySQL과 MongoDB 데이터를 모두 받아 화면에 정상 반영하고 있습니다.**

단, 별도의 새 CLI 프로세스에서 MySQL에 독립적으로 재접속하는 검증은 로컬 실행 환경의 네트워크 접근 정책에 의해 차단되었습니다. 위 판단은 실제 Django 서버가 페이지 요청마다 반환한 live 값과 두 DB의 동일 `run_id` 대사 결과를 근거로 합니다.

## 3. 현재 Warning 상태

확인 시점의 Main/MongoDB 화면은 `CRITICAL · 5 SIGNALS`, MySQL 화면은 `CRITICAL · 3 SIGNALS`입니다. 이는 DB 연결 실패가 아니라 현재 배치의 시간과 rejected 비율이 설정된 기준을 초과했기 때문입니다.

화면에서 확인되는 주요 신호는 다음과 같습니다.

- 최신 배치 시작 후 9분 이상 새 실행이 없어 `PIPELINE_STALE`
- 표준화 rejected가 8건 또는 50% 기준을 넘어 `STANDARD_REJECT_SURGE`
- 정규화 rejected가 경고 기준을 넘어 `FINAL_REJECT_HIGH`
- 동일 오류 코드가 한 배치에서 3회 이상 발생하면 MongoDB `ERROR_CODE_SPIKE`

Warning tray는 전체 alert 중 앞의 3개 메시지만 보여주고, 헤더의 `N SIGNALS`가 전체 개수를 표시합니다. 전체 우선순위는 `CRITICAL > WARNING > NORMAL`입니다.

## 4. Main Dashboard 지표

Main Dashboard는 전체 파이프라인을 지휘통제실 형태로 요약합니다.

| 영역/배너 | 표시 지표 | 의미 |
| --- | --- | --- |
| 상단 Command Bar | 데이터 모드, 전체 상태, signal 수, KST 시계 | `LIVE DATA` 여부와 가장 높은 경고 등급을 즉시 확인 |
| Warning Signal Tray | 우선순위가 높은 경고 3개 | 배치 실패, 지연, 건수 불일치, DB 조회 장애 등의 원인 |
| Ingestion Matrix | `raw_row_count`, 최신 배치 | Legacy에서 들어온 전체 원천 행 수 |
| Hourly Ingestion | 시간당 원천 수집량 막대 | 최근 60개 배치를 KST 시간 단위로 합산한 raw 수집량 |
| Process Throughput | 원천 수집과 Final accepted 추이 | 최근 MySQL 배치 이력의 처리량 비교 |
| Live Event Stream | 배치 상태, accepted/rejected 저장 이벤트 | 최신 배치의 핵심 사건과 첫 번째 경고를 시간순 형태로 표시 |
| Current Batch | 최신 `run_id` | MySQL과 MongoDB를 묶는 배치 식별자 |
| Global Load Rate | `(Final accepted + 실제 MongoDB rejected 행) / raw` | 서로 같은 원천 행 단위로 계산한 전체 대사율 |
| 중앙 3D Pipeline | Legacy → 표준화 → 정규화 → MySQL/MongoDB | 단계별 건수, accepted/rejected 분기와 흐르는 데이터 표현 |
| Stage Status Ribbon | 수집, 표준화 accepted, Final accepted, 전체 대사 건수 | 파이프라인 단계별 통과량과 비율 |
| MySQL Gateway | `Final accepted / raw`, 전체 Legacy 대비 비율 | MySQL 상세 화면 진입 버튼 |
| MongoDB Gateway | `실제 rejected 문서 / raw`, 전체 Legacy 대비 비율 | MongoDB 상세 화면 진입 버튼 |
| Load Distribution | Final accepted, MongoDB rejected, 미대사 | 원천 행의 최종 분류를 표시하고 중앙에는 `Final accepted / raw` 비율 표시 |
| Rejection Signals | 오류 코드별 발생 건수 Top 5 | MongoDB `errors[]`의 오류 발생 횟수 기준 막대 차트 |

`Global Load Rate`에는 MySQL의 manager/top area/area 엔터티 적재 건수를 더하지 않습니다. 엔터티 건수와 원천 행은 단위가 다르기 때문입니다.

## 5. MySQL Dashboard 지표

MySQL Dashboard는 `dashboard_pipeline_run_view`에서 읽은 배치 사실값을 이용해 accepted와 엔터티 적재 상태를 보여줍니다.

| 영역/배너 | 계산 또는 데이터 | 의미 |
| --- | --- | --- |
| Standard Accepted | `standardization_accepted_count / raw_row_count` | 표준화 통과 행 수와 통과율 |
| Normalized Accepted | `final_accepted_count / standardization_accepted_count` | 정규화·관계·중복 검증까지 통과한 행 수와 비율 |
| MySQL Load Rate | `Σ loaded_count / Σ target_count` | manager, top business area, business area 엔터티 적재율 |
| Data Freshness | `updated_at`, `completed_at`, `started_at` 순서로 최신 시각 사용 | 마지막 배치 기록이 현재로부터 얼마나 오래됐는지 표시 |
| Load Rate Telemetry | 최근 배치별 엔터티 적재율 | 배치 단위 적재율 변화 |
| Acceptance Orbit | Final accepted, rejected, 미대사 | 원천 데이터의 처리 결과 분포 |
| Accepted Data Channel | raw → 표준화 accepted → Final accepted → 엔터티 적재 | 단계별 건수 흐름 |
| Table Load Matrix | 테이블별 `loaded / target` | manager, top_business_area, business_area 적재율 |
| Stage Volume | raw, 표준화 accepted, Final accepted, 엔터티 loaded | 처리 단계별 볼륨 비교 |
| Table Integrity Status | 테이블별 loaded/expected/rate/status | `loaded == target` 여부를 표로 확인 |
| Database Link | repository, 데이터 분류, 환경변수 채널 | 현재 데이터가 `PipelineRepository`, accepted, `MYSQL_*`에서 왔음을 표시 |
| Recent Load Batches | run_id, Final accepted 행, 실행시간, 상태 | 최근 배치 이력과 `SUCCESS/PARTIAL_FAILURE/FAILED` 결과 |

현재 live 배치의 엔터티 적재 결과는 다음과 같습니다.

| 엔터티 | Loaded / Target | 적재율 |
| --- | ---: | ---: |
| manager | 2,483 / 2,483 | 100.0% |
| top_business_area | 916 / 916 | 100.0% |
| business_area | 11,045 / 11,045 | 100.0% |
| 합계 | 14,444 / 14,444 | 100.0% |

엔터티 합계 14,444는 여러 테이블의 적재 건수를 합한 값이므로 `Final accepted` 11,045와 직접 같은 행 단위로 비교하지 않습니다.

## 6. MongoDB Dashboard 지표

MongoDB Dashboard는 `standardization_rejected`와 `normalization_rejected` 두 컬렉션을 동일 `run_id`로 조회합니다.

| 영역/배너 | 계산 또는 데이터 | 의미 |
| --- | --- | --- |
| Standard Rejected | 표준화 컬렉션 문서 수 / raw | 표준화 단계에서 반려된 원천 행과 비율 |
| Normalized Rejected | 정규화 컬렉션 문서 수 / 표준화 accepted | 정규화 단계에서 반려된 원천 행과 비율 |
| MongoDB Load Rate | 실제 rejected 문서 / MySQL 예상 rejected | rejected 저장 누락 여부 확인 |
| Top Error Signal | 오류 코드별 `errors[]` 발생 건수 1위 | 가장 많이 발생한 품질 문제 |
| Rejection Signal Analysis | 오류 코드별 발생 건수 | 한 행의 복수 오류를 각각 집계한 막대 차트 |
| Rejected Orbit | 표준화 rejected 행과 정규화 rejected 행 | 반려 행의 단계별 분포 |
| Rejected Data Routing | raw → 두 rejected 단계 → MongoDB stored | 반려 데이터 라우팅 흐름 |
| Rejected Velocity | 최근 배치별 두 컬렉션 문서 수 | 단계별 rejected 추이 |
| Collection Load Matrix | 컬렉션별 실제/예상 적재율 | 두 컬렉션의 저장 완전성 |
| Reason Code Matrix | 오류 코드, 한글 라벨, 건수, 오류 내 비율 | 활성 오류 규칙과 발생 빈도 |
| Collection Channels | 컬렉션명, loaded/expected, 적재율 | 실제 조회 대상과 단계 |
| Recent Rejection Stream | 배치 시각, record ID, 단계, 오류 코드, 저장 상태 | 최근 오류 발생 내역 최대 20개 |

현재 오류 발생 건수는 다음과 같습니다.

| 오류 코드 | 발생 건수 | 전체 오류 중 비율 |
| --- | ---: | ---: |
| `DOMAIN_VIOLATION` | 7,743 | 76.1% |
| `MISSING_REQUIRED` | 1,873 | 18.4% |
| `INVALID_DATE_FORMAT` | 558 | 5.5% |

MongoDB 문서 1개는 **반려 행 1건**이며, 그 문서의 `errors[]` 항목은 **오류 발생 건수**입니다. 한 행에 오류가 3개라면 반려 행은 1건, 오류 발생은 3건으로 집계합니다. 따라서 오류 사유는 합계 100%를 전제로 하는 행 비율 차트가 아니라 발생 건수 막대 차트로 표현합니다.

## 7. 데이터 흐름과 레이어 책임

```text
.env
  ├─ MYSQL_* ──> PipelineRepository ──┐
  └─ MONGO_* ──> MongoRepository ─────┤
                                      v
                         MySQL/MongoDB Services
                                      │
                         KPI 계산 · 대사 · Warning
                                      v
                            MainDashboardService
                                      │
                         Django View / Template Context
                                      v
                         Three.js + ECharts + HTML/CSS
```

- `presentation`: URL과 request/response, 사용할 template 결정
- `repository`: DB 연결과 사실값 조회, DB 예외를 repository 예외로 변환
- `service`: 비율, 건수 대사, warning 판정, 화면용 context 조립
- `templates`: 서버 context를 HTML 구조와 JSON payload로 출력
- Browser JavaScript: JSON payload를 3D 장면과 차트로 렌더링

Main 전용 repository는 없습니다. `MainDashboardService`가 MySQL과 MongoDB repository 결과를 동일 `run_id` 기준으로 조합합니다.

## 8. 사용 기술

| 구분 | 기술 | 역할 |
| --- | --- | --- |
| Backend | Django 5.2 | URL, view, template 렌더링, 설정과 서비스 실행 |
| 환경변수 | python-dotenv | `.env`의 `DASHBOARD_DATA_MODE`, `MYSQL_*`, `MONGO_*` 로딩 |
| MySQL 연결 | Django DB backend + mysqlclient | `dashboard_pipeline_run_view` 조회 |
| MongoDB 연결 | PyMongo | 두 rejected 컬렉션 조회와 집계 |
| 중앙 3D | Three.js + WebGL 2 | 입체 노드, 광원, glow, particle flow, 자동 카메라 orbit |
| 분석 차트 | Apache ECharts 6.1 | line, bar, doughnut 차트와 반응형 애니메이션 |
| UI | Django Template, HTML, CSS, Vanilla JavaScript | HUD 패널, 네비게이션, 실시간 시계, 새로고침 |

Three.js와 ECharts는 CDN이 아니라 `datapipeline/static/datapipeline/vendor/`에 로컬 고정되어 있어 인터넷 연결 없이도 렌더링됩니다.

## 9. 화면 콘셉트와 인터랙션

전체 테마는 미래형 데이터 관제실과 네트워크 지휘통제 HUD를 결합한 분위기입니다.

- 짙은 navy/black 배경과 원근 grid로 깊이감 구성
- cyan/teal은 accepted 및 정상 흐름, purple은 rejected, amber/red는 경고에 사용
- 반투명 panel, 얇은 scan line, glow와 gradient로 고급 관제 화면 표현
- 중앙 파이프라인은 fog, point light, emissive material, particle flow로 입체화
- 카메라는 천천히 자동 orbit하며 텍스트를 읽기 어려울 정도로 회전하지 않도록 이동 범위를 제한
- 마우스 drag로 3D 방향을 조절하고 MySQL/MongoDB 노드를 선택해 상세 화면으로 이동
- ECharts는 smooth line, gradient bar, doughnut animation으로 정적 표보다 동적인 분석 느낌 제공
- 전체 UI와 차트·3D 라벨의 글자 크기를 초기안보다 약 10% 높여 관제 화면의 가독성 강화
- Warning/CRITICAL tray는 border, background, glow가 반복 점멸해 즉시 식별 가능
- 브라우저의 `prefers-reduced-motion` 설정을 감지해 애니메이션 강도를 낮춤
- WebGL 2를 사용할 수 없으면 3D fallback 안내를 표시

## 10. 운영 시 주의사항

- `.env`에서 `DASHBOARD_DATA_MODE=live`로 변경한 뒤 Django 서버를 재시작해야 합니다.
- live 모드에서는 DB 조회 실패를 sample 값으로 대체하지 않고 `MYSQL_UNAVAILABLE` 또는 `MONGODB_UNAVAILABLE`로 표시합니다.
- MySQL View와 MongoDB 두 컬렉션은 동일한 `run_id`를 사용해야 DB 간 대사가 가능합니다.
- Main은 시간당 수집량과 처리 추이를 위해 최근 60개 배치를 조회하고, MySQL/MongoDB 상세 화면은 최근 12개 배치를 조회합니다. 실제 시간 범위는 배치 주기와 저장된 이력 수에 따라 달라집니다.
- 현재 실측 `run_id`는 `...+0900...` 형식이지만 MongoDB의 단독 시각 parser는 `YYYYMMDDTHHMMSSZ` 형식을 기준으로 합니다. 현재 화면은 MySQL의 `started_at`을 우선 사용해 정상 동작하지만, 향후 데이터 계약에서 한 가지 형식으로 통일하거나 parser가 두 형식을 모두 지원하도록 정리하는 것이 안전합니다.
- Footer의 `LATENCY`, `UPTIME`, `SECURE CHANNEL` 값은 현재 실측 모니터링 값이 아니라 시각적 HUD 문구입니다.
