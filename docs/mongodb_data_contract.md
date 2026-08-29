# MongoDB 데이터 계약

기본 database는 `legacy_bronze`, source는 `biz_legacy_integrated`다.

## collection

| collection | 역할 |
| --- | --- |
| `legacy_records` | 페이지 run들을 append한 현재 공개 누적 데이터 |
| `crawl_manifests` | page run별 파일·MongoDB 검증 및 pipeline 상태 |
| `crawler_runs` | page run별 `loading → validating → ready/failed` 상태 |
| `legacy_records_backup_pre_page_append_{timestamp}` | 새 구조 도입 직전 production의 보존본 |
| `legacy_records_failed_page_append_{timestamp}` | 초기 full pagination rollback 시 실패한 새 production |

과거 staging/promotion collection은 자동 삭제하지 않는다. 정상 page append 운영에서는 staging collection이나 READY→READY collection rename을 사용하지 않는다.

## legacy_records 문서

문서는 wrapper 5개, payload 15개와 `_ingest`만 가진다.

```javascript
{
  record_id: 154001,
  source_row_no: 251,
  source_record_sha256: "...",
  release_slot: 62,
  scheduled_release_at: "...",
  payload: { /* 원천 15개 필드 */ },
  _ingest: {
    run_id: "<page-run-id>",
    source_name: "biz_legacy_integrated",
    collected_at: "<timezone-aware timestamp>"
  }
}
```

원천 wrapper와 payload는 수정하지 않는다. `strip`, 날짜 변환, NULL 치환, 대소문자 변경, 코드 치환, payload flatten을 금지한다. `pipeline_status`는 record마다 저장하지 않는다.

## index와 누적 불변 조건

```javascript
db.legacy_records.createIndex(
  { record_id: 1 },
  { unique: true, name: "uq_record_id" }
)
```

- document count `==` continuation state의 `released_rows`
- distinct `record_id == document count`, duplicate 0
- distinct `source_row_no == document count`, duplicate 0
- `_ingest.source_name == biz_legacy_integrated`
- production의 모든 `_ingest.run_id`는 READY `crawler_runs`와 pass/pending `crawl_manifests`에 대응
- 한 page run의 문서는 모두 동일한 `_ingest.run_id`를 사용

## 상태

- `manifest.status`: `success | partial_failure | failed`
- `mongodb_validation_status`: `pass | fail`
- `pipeline_status`: `pending | pass`
- `crawler_runs.state`: `loading | validating | ready | failed`

파일 manifest의 `pipeline_status=pending`은 불변이다. 후속 정규화·표준화 완료 시 MongoDB `crawl_manifests.pipeline_status`만 `pending → pass`로 변경한다.
