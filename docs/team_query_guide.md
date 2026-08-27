# 팀 MongoDB 조회 가이드

## 사용 전 필수 gate

후속 정규화·표준화 pipeline은 다음 조건을 모두 만족할 때만 `legacy_records`를 읽는다.

systemd 상시 서비스가 `next_refresh_at + 5초` 일정으로 production을 계속 갱신하므로 특정 run_id나 row count를 설정값으로 사용하지 않는다. 매 작업 시작 시 `crawler_runs`에서 최신 READY run을 다시 조회한다.

1. 최신 run의 `crawler_runs.state == "ready"`
2. 최신 READY `run_id == legacy_records._ingest.run_id`
3. distinct `legacy_records._ingest.run_id == 1`
4. distinct `legacy_records._ingest.source_name == ["biz_legacy_integrated"]`

하나라도 불일치하면 dataset을 사용하거나 후속 pipeline을 실행하지 않는다. `pipeline_status=pending`은 Bronze READY와 모순되지 않는다. 이 값은 후속 정규화·표준화 완료 여부다.

## mongosh 확인 예시

`mongosh`는 MongoDB Shell(MongoDB 명령줄 shell)이다.

```javascript
use legacy_bronze

const latestReady = db.crawler_runs
  .find({ source_name: "biz_legacy_integrated", state: "ready" })
  .sort({ ready_at: -1 })
  .limit(1)
  .toArray()[0];

const productionRunIds = db.legacy_records.distinct("_ingest.run_id");
const productionSources = db.legacy_records.distinct("_ingest.source_name");

printjson({ latestReady, productionRunIds, productionSources });
```

소비 gate를 한 번에 검사한다.

```javascript
if (!latestReady) {
  throw new Error("READY run이 없습니다.");
}
if (productionRunIds.length !== 1) {
  throw new Error("production이 단일 run이 아닙니다.");
}
if (productionRunIds[0] !== latestReady.run_id) {
  throw new Error("READY run_id와 production run_id가 다릅니다.");
}
if (
  productionSources.length !== 1 ||
  productionSources[0] !== "biz_legacy_integrated"
) {
  throw new Error("production source_name 계약이 맞지 않습니다.");
}
```

## 건수와 index 확인

```javascript
const documentCount = db.legacy_records.countDocuments({});
const distinctRecordCount = db.legacy_records.distinct("record_id").length;
const indexes = db.legacy_records.getIndexes();

printjson({ documentCount, distinctRecordCount, indexes });

if (documentCount !== distinctRecordCount) {
  throw new Error("record_id 중복 또는 누락 가능성이 있습니다.");
}
```

`uq_record_id`가 `{record_id: 1}`, `unique: true`인지 확인한다.

## manifest 확인

```javascript
db.crawl_manifests.findOne(
  { run_id: latestReady.run_id },
  {
    _id: 0,
    run_id: 1,
    status: 1,
    mongodb_validation_status: 1,
    pipeline_status: 1,
    row_count: 1,
    page_count: 1
  }
)
```

Bronze 소비 시 기대값은 `status=success`, `mongodb_validation_status=pass`다. `pipeline_status`는 후속 작업 전 `pending`, 후속 정규화·표준화와 검증 완료 후 `pass`다.

## 데이터 조회 예시

```javascript
db.legacy_records.find(
  { "_ingest.run_id": latestReady.run_id },
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
).limit(10)
```

팀 pipeline은 payload 값을 Bronze에서 수정하거나 Bronze collection에 결과를 되쓰지 않는다. 후속 dataset에도 원본 `run_id`를 계보 키로 전달해 결과에서 Raw JSON까지 역추적 가능하게 한다.

## 동적 조회 원칙

최신 READY run은 `crawler_runs`에서 동적으로 조회한다. production `legacy_records._ingest.run_id`의 distinct 값은 하나여야 하며 그 값이 최신 READY run_id와 일치해야 한다. 상시 서비스의 다음 cycle 사이에도 이 gate를 통과한 snapshot만 후속 pipeline에 제공한다.
