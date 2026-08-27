# Bronze 최종 아키텍처

## 목적과 경계

Bronze crawler는 `biz_legacy_integrated` 원천을 변경 없이 수집하고, 각 수집 회차의 파일 snapshot과 최신 검증 완료 dataset을 제공한다. 공백 제거, 날짜 변환, 대소문자 변경, 빈 문자열의 NULL 치환, 코드값 치환과 같은 정규화·표준화는 Bronze 범위가 아니다.

## 데이터 흐름

```text
systemd legacy-crawler.service
  ↓ foreground runner: python -m legacy_crawler.service
API(Application Programming Interface, 애플리케이션 프로그래밍 인터페이스)
  ↓ metadata에서 dataset_id 확인, signed cursor 전체 pagination
Raw JSON(JavaScript Object Notation, 자바스크립트 객체 표기법)
  ↓ HTTP(Hypertext Transfer Protocol, 하이퍼텍스트 전송 프로토콜) response body bytes를 페이지별 불변 저장
exchange / backup CSV(Comma-Separated Values, 쉼표 구분 값)
  ↓ payload 15컬럼 / wrapper 5개 + payload 15컬럼
MongoDB run별 staging
  ↓ full snapshot 적재
파일 및 MongoDB validation
  ↓ 모든 필수 검사 PASS
production legacy_records
  ↓ 단일 READY run 공개
후속 정규화·표준화 및 next_refresh_at + 5초까지 대기
  ↓
다음 자동 cycle
```

`service.py`는 `run_once()`, `validate_promotion_candidate()`, `promote_ready_to_ready()`, `calculate_next_run()`을 조합한다. 검증 로직을 복제하지 않고 기존 보호 조건과 rollback을 재사용한다. 수집과 staging 검증이 성공해도 production 승격 전 `crawler_runs.state`는 `validating`이며, production rename과 사후 검증까지 성공한 뒤에만 `ready`가 된다.

systemd unit은 enabled 상태이며 `python -m legacy_crawler.service`를 `active (running)`으로 유지한다. `Restart=on-failure`로 비정상 종료를 복구하고, 정상 cycle은 metadata의 `server_time`, `next_refresh_at`을 기준으로 다음 시각을 매번 다시 계산한다.

## 저장 계층 원칙

### 파일 Bronze

파일 Bronze는 모든 성공 run의 full snapshot 불변 이력이다. 각 run은 다른 run과 독립적으로 보존한다.

```text
data/bronze/biz_legacy_integrated/
└── ingest_date=YYYY-MM-DD/
    └── run_id={run_id}/
        ├── raw/page_0001.json ...
        ├── exchange/legacy_full_15cols.csv
        └── manifest.json

backup/bronze/biz_legacy_integrated/
└── ingest_date=YYYY-MM-DD/
    └── run_id={run_id}/
        └── raw_full_20cols.csv
```

Raw 파일별 실제 bytes의 SHA-256(Secure Hash Algorithm 256-bit, 256비트 보안 해시 알고리즘), 크기, 페이지 번호와 경로를 `raw_artifacts`에 기록한다. 여러 파일의 hash를 조합한 aggregate checksum은 사용하지 않는다.

### MongoDB production

`legacy_records`는 최신 READY dataset 한 회차만 유지한다. 모든 run의 full snapshot을 이 collection에 누적하지 않는다. collection 안의 distinct `_ingest.run_id`와 `_ingest.source_name`은 각각 반드시 1이어야 한다.

과거 run은 다음을 연결해 추적한다.

```text
run_id → crawler_runs → crawl_manifests
      → 파일 manifest → Raw JSON / exchange CSV / backup CSV
```

## run_id lineage

`run_id`는 crawler가 생성하는 기술 계보 키이며 원천 payload 컬럼이 아니다. 한 실행의 API 수집, Raw 파일, CSV, manifest, MongoDB staging, production 문서, `crawler_runs`, `crawl_manifests`는 동일한 원래 `run_id`를 사용한다.

`safe_run_id`는 collection 이름을 만들 때만 사용한다. 원래 run_id의 `+`, `-` 등 collection 이름에 부적합한 문자는 이름에서 `_`로 바꾸지만 문서 내부 `_ingest.run_id`는 원래 값을 그대로 보존한다.

## READY → READY 반복 승격

현재 production run A와 검증 완료 staging run B 사이의 일반 승격은 다음 계약을 따른다.

```text
production A 단일 run/source 및 최신 READY 일치 확인
→ promotion.lock
→ legacy_records → legacy_records_backup_{safe_run_A}
→ staging B → legacy_records
→ production B 사후 검증
→ crawler_runs(B).state = ready
→ next_refresh_at + 5초까지 대기
```

사후 검증 또는 READY 기록이 실패하면 B를 `legacy_records_failed_{safe_run_B}`로 보존하고 backup A를 `legacy_records`로 복원한다. `dropTarget=true`는 사용하지 않는다.

## manifest 역할 분리

- 파일 `manifest.json`: Bronze 수집 당시의 불변 증빙이다. 최초 `pipeline_status=pending`이며 후속 파이프라인 완료 뒤에도 수정하지 않는다.
- MongoDB `crawl_manifests`: 운영 추적용 확장 manifest다. 최초 내용은 파일 manifest를 기반으로 하며 실제 MongoDB 검증 결과를 추가한다. 후속 정규화·표준화 및 해당 단계 검증이 끝났을 때 이 collection의 `pipeline_status`만 `pending → pass`로 변경할 수 있다.

따라서 두 manifest는 최초에는 대응하지만 영구적으로 완전히 동일해야 하는 계약이 아니다.

## 현재 운영 상태

production은 systemd runner의 성공 cycle마다 새 READY snapshot으로 갱신된다. 특정 run_id나 row count를 아키텍처 문서에 고정하지 않는다. 최신 READY run은 `crawler_runs`를 동적으로 조회하고, 그 run_id가 `legacy_records._ingest.run_id`의 단일 distinct 값과 일치하는지 확인한다. 서로 다른 run_id의 자동 cycle 연속 성공과 `systemctl restart` 이후 자동 cycle 복구가 운영 증빙으로 확인되었다.
