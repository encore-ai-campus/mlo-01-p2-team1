# Bronze Relay crawler

`biz_legacy_integrated` 원천을 변경 없이 수집해 파일 Bronze와 MongoDB `legacy_records`에 제공한다. 현재 운영 단위는 API(Application Programming Interface, 애플리케이션 프로그래밍 인터페이스) 응답 페이지이며 페이지마다 별도 `run_id`를 사용한다.

## 현재 운영 흐름

```text
systemd legacy-crawler.service
→ 저장된 signed cursor로 /api/v1/records?limit=1000 호출
→ 응답 페이지별 run_id 생성
→ Raw JSON / 15컬럼 exchange CSV / 20컬럼 backup CSV 저장
→ 해당 페이지를 legacy_records에 append
→ page run 검증 및 crawl_manifests 기록
→ next_cursor 원문을 continuation state에 원자적으로 저장
→ has_more=false 후 production 전체 검증
→ next_refresh_at + 5초까지 대기
→ 반복
```

페이지 이동에는 서버의 `next_cursor`만 사용한다. `page`, `offset`, `release_slot`, `record_id`, `source_row_no`로 다음 위치를 계산하지 않는다. cursor가 만료되거나 거부되면 첫 페이지로 자동 fallback하지 않고 실패 종료한다.

## 실행 환경과 주요 경로

- WSL(Windows Subsystem for Linux, Windows용 Linux 하위 시스템), Python 3.14, PyMongo 4.17.0
- 코드: `src/legacy_crawler/`
- 테스트: `tests/`
- 파일 Bronze: `data/bronze/`, `backup/bronze/`
- cursor 상태: `state/records_continuation.json`
- 로그: `logs/`
- 설정 예시: [.env.example](.env.example)

## 운영 명령

```bash
systemctl status legacy-crawler.service --no-pager -l

cd /mnt/c/MLOps/project/2nd
PYTHONPATH=src .venv/bin/python -m legacy_crawler.service --once
PYTHONPATH=src .venv/bin/python -m legacy_crawler.audit_page_append
```

`--initialize --once`는 기존 `legacy_records`를 timestamp backup으로 rename하고 처음부터 full pagination을 수행하는 일회성 명령이다. 서비스가 `inactive`인 통제된 상황에서만 사용한다.

## 테스트

```bash
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests/unit -v
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests/contract -v
RUN_MONGODB_INTEGRATION=1 PYTHONPATH=src .venv/bin/python \
  -m unittest tests.integration.test_mongodb_page_append -v
```

## MongoDB production 계약

- `legacy_records`에는 여러 page `run_id`가 동시에 존재한다.
- 한 page의 최대 1,000건은 동일한 `_ingest.run_id`를 가진다.
- `record_id` unique index `uq_record_id`를 유지한다.
- production document count는 continuation state의 `released_rows`와 같아야 한다.
- 전체 `record_id`와 `source_row_no` 중복은 0이어야 한다.
- 각 production page run은 READY `crawler_runs`와 `status=success`, `mongodb_validation_status=pass`, `pipeline_status=pending`인 `crawl_manifests`에 대응한다.

상세 내용은 [아키텍처](docs/bronze_architecture.md), [운영 매뉴얼](docs/bronze_operation_manual.md), [MongoDB 계약](docs/mongodb_data_contract.md), [팀 조회 가이드](docs/team_query_guide.md), [장애 대응](docs/troubleshooting_and_rollback.md)을 참고한다.

## 이슈 #41 전환 검증 이력

전환 검증 당시 최초 full pagination은 27,532건을 28개 page run으로 수집했고, 이후 3분 continuation cycle에서 저장된 signed cursor부터 신규 데이터만 append하는 것을 확인했다. 누적 검증 결과는 `record_id` 중복 0, `source_row_no` 중복 0, `_ingest.run_id` 누락 0이었다.

동기화된 제출 소스에서도 Unit 30건, Contract 3건, 격리 MongoDB Integration 2건이 모두 통과했다. 운영 서비스는 systemd에서 active 상태로 확인된 구조를 문서화한 것이다. 운영 document 수와 page run 수는 이후 cycle마다 증가하므로 위 수치는 현재 production의 고정값이 아니라 전환 시점 검증 증빙으로만 사용한다.
