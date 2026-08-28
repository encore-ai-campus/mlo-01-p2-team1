# 팀 MongoDB 조회 가이드

## 사용 전 gate

`legacy_records`에는 여러 page run_id가 존재하는 것이 정상이다. 후속 pipeline 전 다음을 확인한다.

```javascript
use legacy_bronze

const count = db.legacy_records.countDocuments({});
const recordIds = db.legacy_records.distinct("record_id");
const sourceRows = db.legacy_records.distinct("source_row_no");
const runIds = db.legacy_records.distinct("_ingest.run_id");
const sources = db.legacy_records.distinct("_ingest.source_name");

if (count !== recordIds.length) throw new Error("record_id 중복 가능성");
if (count !== sourceRows.length) throw new Error("source_row_no 중복 가능성");
if (sources.length !== 1 || sources[0] !== "biz_legacy_integrated") {
  throw new Error("source_name 계약 불일치");
}

const readyCount = db.crawler_runs.countDocuments({
  run_id: { $in: runIds }, state: "ready"
});
const manifestCount = db.crawl_manifests.countDocuments({
  run_id: { $in: runIds },
  status: "success",
  mongodb_validation_status: "pass",
  pipeline_status: { $in: ["pending", "pass"] }
});

if (readyCount !== runIds.length) throw new Error("READY page run 누락");
if (manifestCount !== runIds.length) throw new Error("page manifest 누락/실패");
```

운영자는 파일 상태의 `released_rows`까지 포함하는 다음 audit를 수행한다.

```bash
PYTHONPATH=src .venv/bin/python -m legacy_crawler.audit_page_append
```

audit가 실패하면 후속 정규화·표준화를 실행하지 않는다.

## 조회

```javascript
db.legacy_records.find(
  {},
  {
    _id: 0,
    record_id: 1,
    source_row_no: 1,
    source_record_sha256: 1,
    release_slot: 1,
    scheduled_release_at: 1,
    payload: 1,
    _ingest: 1
  }
).sort({ source_row_no: 1 }).limit(1000)
```

정렬과 조회에 `source_row_no`를 사용할 수 있지만 다음 API 페이지 위치를 계산하는 데 사용해서는 안 된다. API 이동 기준은 signed `next_cursor`뿐이다.
