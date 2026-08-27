# Bronze Relay crawler

`biz_legacy_integrated` 원천을 API(Application Programming Interface, 애플리케이션 프로그래밍 인터페이스)에서 완전 수집하여 불변 파일 Bronze와 최신 READY MongoDB dataset을 만드는 프로젝트다. Bronze crawler는 원천값을 표준화하지 않고 수집·계보·검증·안전한 production 공개까지만 담당한다.

## 현재 운영 흐름

```text
systemd legacy-crawler.service
→ python -m legacy_crawler.service
→ full collection 및 파일 Bronze publish
→ run별 MongoDB staging 검증
→ READY → READY production 승격
→ production 사후 검증
→ crawler_runs.state = ready
→ next_refresh_at + 5초 기반 대기
→ 다음 cycle 반복
```

JSON(JavaScript Object Notation, 자바스크립트 객체 표기법) Raw 파일은 HTTP(Hypertext Transfer Protocol, 하이퍼텍스트 전송 프로토콜) response body bytes를 재직렬화하지 않고 보존한다. CSV(Comma-Separated Values, 쉼표 구분 값)는 UTF-8(Unicode Transformation Format 8-bit, 8비트 유니코드 변환 형식) BOM(Byte Order Mark, 바이트 순서 표식) 형식이다.

## 실행 환경

- Windows 호스트와 WSL(Windows Subsystem for Linux, Windows용 Linux 하위 시스템)
- Python 3.14 가상환경: `.venv`
- PyMongo 4.17.0
- MongoDB database: `legacy_bronze`
- 설정 계약: [.env.example](.env.example)

`.env.example`은 예시일 뿐 자동 로드되지 않는다. 실행 프로세스에 필요한 환경변수를 명시적으로 전달해야 한다. MongoDB 인증과 방화벽 설정은 이 프로젝트에서 변경하지 않았다.

## 주요 디렉터리

| 경로 | 역할 |
| --- | --- |
| `src/legacy_crawler/` | 수집, 직렬화, 검증, MongoDB staging, 승격 보호 로직 |
| `src/legacy_crawler/service.py` | 자동 수집·승격·READY 확인·다음 실행 대기 runner |
| `tests/` | unit, contract, opt-in integration 테스트 |
| `data/bronze/` | 모든 성공 run의 Raw JSON, exchange CSV, 불변 manifest |
| `backup/bronze/` | 모든 성공 run의 20컬럼 full snapshot CSV |
| `logs/` | run_id 기반 구조화 JSON 로그 |
| `state/` | 동시 실행 및 승격 lock 파일 |
| `docs/` | 아키텍처, 운영, 데이터 계약, 조회, 장애 대응 문서 |

## 운영 방법

WSL의 `legacy-crawler.service`가 상시 runner를 foreground process로 실행한다. 현재 unit은 enabled 상태이며 서비스는 `active (running)`으로 운영된다.

```bash
systemctl is-enabled legacy-crawler.service
systemctl is-active legacy-crawler.service
systemctl status legacy-crawler.service --no-pager -l
```

`service.py`는 매 cycle마다 새 metadata를 조회하고 `run_once()`로 full snapshot을 만든 뒤 `promote_ready_to_ready()`로 검증된 staging을 production에 승격한다. CLI(Command-Line Interface, 명령줄 인터페이스) `--promote-ready`와 자동 runner의 실제 READY→READY 승격이 검증되었다. `--promote-first-mixed`는 완료된 최초 migration 전용이므로 반복 운영에 사용하지 않는다.

수동 1회 end-to-end 확인은 다음 명령을 사용한다.

```bash
cd /mnt/c/MLOps/project/2nd
PYTHONPATH=src .venv/bin/python -m legacy_crawler.service --once
```

## 테스트 방법

```bash
cd /mnt/c/MLOps/project/2nd
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
```

실제 MongoDB를 변경하는 integration 테스트는 기본적으로 skip된다. 관련 환경변수를 켜기 전에 [운영 매뉴얼](docs/bronze_operation_manual.md)의 대상 collection과 보호 조건을 확인한다.

## 현재 production 계약

상시 서비스가 production을 계속 갱신하므로 문서에 특정 run_id나 row count를 고정하지 않는다. 최신 READY run은 `crawler_runs`에서 동적으로 조회하며 다음 조건을 항상 만족해야 한다.

- `legacy_records`의 distinct `_ingest.run_id`는 정확히 1개
- production `_ingest.run_id`와 최신 `crawler_runs.state=ready` run_id가 일치
- `_ingest.source_name`은 `biz_legacy_integrated`
- unique index는 `{record_id: 1}`, 이름 `uq_record_id`
- MongoDB manifest는 `status=success`, `mongodb_validation_status=pass`

## 상세 문서

- [최종 아키텍처](docs/bronze_architecture.md)
- [운영 매뉴얼](docs/bronze_operation_manual.md)
- [MongoDB 데이터 계약](docs/mongodb_data_contract.md)
- [팀 조회 가이드](docs/team_query_guide.md)
- [장애 대응 및 rollback](docs/troubleshooting_and_rollback.md)
