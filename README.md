# Data Pipeline Dashboard

Legacy 데이터 수집 → 표준화 → 정규화 → MySQL/MongoDB 적재 흐름을 관제하는 Django 대시보드입니다.

통합 화면의 중앙 파이프라인은 Three.js 3D 장면으로, 주변 및 상세 분석 패널은 Apache ECharts로 렌더링합니다. 라이브러리는 CDN이 아니라 `datapipeline/static/datapipeline/vendor/`에 고정되어 있습니다.

## 화면 URL

- 통합 관제: `http://127.0.0.1:8000/dashboard/`
- MySQL accepted: `http://127.0.0.1:8000/dashboard/mysql/`
- MongoDB rejected/reason: `http://127.0.0.1:8000/dashboard/mongodb/`

## 로컬 실행

```powershell
cd "Django dashboard"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python manage.py runserver
```

DB 환경 변수가 없는 동안에는 SQLite 설정과 repository의 샘플 지표를 사용하므로 세 화면을 바로 확인할 수 있습니다. 실제 접속 정보는 `.env.example`을 복사한 `.env`에 작성합니다. `.env`는 Git에서 제외됩니다.

## 레이어 책임

- `presentation`: URL, request/response, template 선택
- `service`: 지표 계산 및 화면 context 조립
- `repository`: MySQL/MongoDB/Legacy 데이터 조회 경계
- `templates`: 통합·MySQL·MongoDB 대시보드 화면

실제 DB 스키마가 확정되면 `repository`의 샘플 반환부를 조회 로직으로 교체하고, `service`와 템플릿의 데이터 계약은 유지합니다.
