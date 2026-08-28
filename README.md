# Data Pipeline Dashboard

Legacy 데이터 수집 → 표준화 → 정규화 → MySQL accepted/MongoDB rejected 적재 → Gold manager feature 흐름을 관제하는 Django 대시보드입니다.

통합 화면의 중앙 파이프라인은 Three.js 3D 장면으로, 주변 및 상세 분석 패널은 Apache ECharts로 렌더링합니다. 라이브러리는 CDN이 아니라 `datapipeline/static/datapipeline/vendor/`에 고정되어 있습니다.

화면별 지표, 계산식, Live 확인 결과와 디자인 설명은 [DASHBOARD_GUIDE.md](DASHBOARD_GUIDE.md)를 참고하세요.

## 화면 URL

- 통합 관제: `http://127.0.0.1:8000/dashboard/`
- MySQL accepted: `http://127.0.0.1:8000/dashboard/mysql/`
- MongoDB rejected/reason: `http://127.0.0.1:8000/dashboard/mongodb/`
- Gold manager intelligence: `http://127.0.0.1:8000/dashboard/gold/`

## 로컬 실행

```powershell
cd "Django dashboard"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python manage.py runserver
```

`DASHBOARD_DATA_MODE=sample`에서는 repository 샘플 지표로 네 화면을 바로 확인할 수 있습니다. 실제 접속 정보는 `Django dashboard/.env`에 작성합니다. MySQL은 단일 `MYSQL_*` 연결을 Django ORM에서 사용하고, MongoDB는 `MONGO_*` 설정을 repository의 PyMongo 연결에서 사용합니다. Gold는 같은 MySQL 연결로 `dashboard_gold_manager_assignment_view`를 읽으며, 필요한 경우 `GOLD_DASHBOARD_VIEW`로 View 이름을 재정의할 수 있습니다. `.env`는 Git에서 제외됩니다.

## 레이어 책임

- `presentation`: URL, request/response, template 선택
- `service`: 지표 계산 및 화면 context 조립
- `repository`: MySQL pipeline View, MongoDB rejected 컬렉션, MySQL Gold View의 읽기 전용 조회 경계
- `templates`: 통합·MySQL·MongoDB·Gold 대시보드 화면

`DASHBOARD_DATA_MODE=sample`에서는 샘플 지표를 사용하고, `live`에서는 repository가 실제 DB를 조회합니다. 모드가 바뀌어도 `service`와 템플릿의 데이터 계약은 유지합니다.

## Warning Sign 기준

전체 상태는 `CRITICAL > WARNING > NORMAL` 우선순위로 결정합니다. 약 3분 배치 주기를 기준으로 하며, 종료된 배치에서만 단계별 건수 대사를 수행하여 `RUNNING` 중간 상태의 오경보를 방지합니다.

| 분류 | `WARNING` | `CRITICAL` |
| --- | --- | --- |
| 배치 상태·시간 | `PARTIAL_FAILURE`, 알 수 없는 상태, 실행 또는 새 배치 지연 6분 이상, 실행시간 3분 이상 | `FAILED`, `RUNNING` 또는 새 배치 지연 9분 이상, 완료 시각 누락·역전, 부분 실패 2회 연속 |
| 표준화 rejected | 4건 이상 또는 원천 대비 25% 이상 | 8건 이상 또는 원천 대비 50% 이상 |
| 정규화 rejected | 3건 이상 또는 표준화 accepted 대비 20% 이상 | 표준화 accepted 대비 40% 이상 |
| MySQL 건수·적재 | 비성공 배치의 엔터티 적재율 95% 미만 | 단계별 accepted/rejected 대사 불일치, 적재 건수가 target 초과, `SUCCESS`인데 target과 loaded 불일치 |
| MongoDB 품질 | `errors`가 없는 반려 문서, 오류 코드 형식 불량, 동일 오류 코드 3회 이상 | 동일 배치·단계·원천 행의 rejected 문서 중복 |
| DB 간 대사 | `PARTIAL_FAILURE`·`FAILED` 배치의 MySQL 예상 rejected와 MongoDB 실제 문서 수 불일치 | `SUCCESS` 배치의 MySQL 예상 rejected와 MongoDB 실제 문서 수 불일치 |
| Gold 품질 | Gold View가 비어 있거나 평균 Area 연령이 최대 연령보다 큰 행 | manager_id 중복, feature 범위·계층 모순, cross-top flag 불일치 |
| 조회 장애 | 현재 KPI는 유지되지만 MySQL 이력 또는 MongoDB 추이 조회 실패 | MySQL 전체 배치, MongoDB rejected 또는 Gold View 조회 실패 |

한 MongoDB 문서에 `errors`가 여러 개일 수 있으므로 **반려 행 수**와 **오류 발생 건수**는 별도로 집계합니다. 오류 사유 차트는 오류 발생 건수 기준의 막대 차트이며 합계 비율이 반려 행 기준 100%를 초과하는 상황을 비율 차트로 표현하지 않습니다.
