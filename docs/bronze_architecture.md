# Bronze 아키텍처

## 데이터 흐름

```text
/public/v1/key → X-API-Key
→ /api/v1/meta에서 dataset_id와 다음 실행시각 확인
→ /api/v1/records?dataset_id=...&limit=1000&cursor=...
→ signed next_cursor 연쇄
→ 페이지별 Raw/CSV 및 별도 run_id
→ legacy_records append
→ page validation / crawler_runs / crawl_manifests
→ continuation cursor 원자적 저장
→ has_more=false에서 누적 production 검증
```

첫 페이지의 `checkpoint`, `dataset_id`, `released_rows`는 한 cursor chain의 불변 기준이다. 후속 페이지에서 하나라도 변하면 실패한다. 마지막 `next_cursor`와 `checkpoint`는 `state/records_continuation.json`에 저장한다. 다음 3분 cycle은 이 cursor를 첫 요청에 전달하며 첫 페이지로 자동 재수집하지 않는다.

## 페이지 run lineage

응답 페이지마다 새 `run_id`를 생성한다. 해당 페이지의 Raw JSON(JavaScript Object Notation, 자바스크립트 객체 표기법), CSV(Comma-Separated Values, 쉼표 구분 값), 파일 manifest, MongoDB 문서, `crawler_runs`, `crawl_manifests`가 같은 run_id로 연결된다. `crawl_id`나 `snapshot_id` 같은 상위 식별자는 사용하지 않는다.

파일 Bronze는 다음 구조로 페이지 run을 불변 보존한다.

```text
data/bronze/biz_legacy_integrated/ingest_date=YYYY-MM-DD/run_id={page_run_id}/
├── raw/page_0001.json
├── exchange/legacy_full_15cols.csv
└── manifest.json

backup/bronze/biz_legacy_integrated/ingest_date=YYYY-MM-DD/run_id={page_run_id}/
└── raw_full_20cols.csv
```

Raw 파일은 HTTP(Hypertext Transfer Protocol, 하이퍼텍스트 전송 프로토콜) response body bytes를 재직렬화하지 않고 저장한다.

## MongoDB

`legacy_records`는 페이지 단위 run을 append하므로 여러 `_ingest.run_id`가 동시에 존재한다. `record_id` unique index가 페이지 내부와 페이지 사이 중복을 차단한다. `source_row_no` 중복은 누적 검증으로 검사한다.

최초 전환에서는 기존 production을 `legacy_records_backup_pre_page_append_{timestamp}`로 rename하고 새 `legacy_records`를 만든다. backup은 새 구조 전체 검증이 끝난 뒤에도 수동 승인 전까지 유지한다. 정상 3분 cycle은 collection rename이나 staging promotion을 사용하지 않는다.
