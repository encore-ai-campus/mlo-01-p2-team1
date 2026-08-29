# 장애 대응과 rollback

## 추적 순서

```text
page run_id
→ crawler_runs
→ crawl_manifests
→ legacy_records._ingest.run_id
→ 파일 manifest
→ Raw JSON
```

## cursor 오류

cursor 거부·만료, checkpoint/dataset_id/released_rows 변경, cursor 반복은 모두 실패다. 첫 페이지부터 자동 재수집하거나 offset/page/record_id/source_row_no/release_slot으로 위치를 재구성하지 않는다. 오류 원인을 확인하고 수동 대응할 때까지 서비스를 중지한다.

```bash
sudo systemctl stop legacy-crawler.service
systemctl is-active legacy-crawler.service
journalctl -u legacy-crawler.service -n 100 --no-pager
```

## 최초 초기화 rollback

초기 full pagination 실패 시 구현은 다음 순서로 원상복구한다.

```text
새 partial legacy_records
→ legacy_records_failed_page_append_{timestamp}

legacy_records_backup_pre_page_append_{timestamp}
→ legacy_records
```

`dropTarget=true`와 production 직접 삭제는 사용하지 않는다. 실패 collection과 backup은 자동 삭제하지 않으며 수동 승인 후 정리한다.

## 검증

```bash
PYTHONPATH=src .venv/bin/python -m legacy_crawler.audit_page_append
```

document/released row count, record/source row 중복, page run READY, manifest pass/pending, source name, terminal cursor/checkpoint, unique index와 backup 보존을 모두 검사한다. 하나라도 실패하면 후속 pipeline을 실행하지 않는다.
