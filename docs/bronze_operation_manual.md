# Bronze 운영 매뉴얼

## systemd 운영

```bash
systemctl is-enabled legacy-crawler.service
systemctl is-active legacy-crawler.service
systemctl status legacy-crawler.service --no-pager -l
journalctl -u legacy-crawler.service -n 100 --no-pager
```

unit은 `.venv/bin/python -m legacy_crawler.service`를 실행하고 `Restart=on-failure`로 실패를 복구한다. 정상 cycle 뒤 metadata의 `next_refresh_at + 5초`까지 기다린다.

## 일회성 초기화

초기화는 기존 production을 삭제하지 않고 timestamp backup으로 rename한다. 반드시 서비스를 먼저 중지한다.

```bash
sudo systemctl stop legacy-crawler.service
systemctl is-active legacy-crawler.service  # inactive 확인

cd /mnt/c/MLOps/project/2nd
PYTHONPATH=src .venv/bin/python -m legacy_crawler.service --initialize --once
PYTHONPATH=src .venv/bin/python -m legacy_crawler.audit_page_append
```

`--initialize`는 continuation state가 이미 있으면 거부된다. 실패하면 새 partial production을 failed collection으로 보존하고 원래 backup을 `legacy_records`로 복구한다.

## 정상 cycle

```bash
PYTHONPATH=src .venv/bin/python -m legacy_crawler.service --once
```

정상 cycle은 저장 cursor부터 신규 데이터만 가져온다. 페이지마다 새 run_id를 생성하고 최대 1,000건을 append한 뒤 page manifest와 continuation cursor를 기록한다. cursor 만료·거부, checkpoint 변경, 중복 또는 누락이 발생하면 non-zero로 종료하며 cursor 없는 요청으로 fallback하지 않는다.

## 검증과 재가동

```bash
PYTHONPATH=src .venv/bin/python -m legacy_crawler.audit_page_append
sudo systemctl start legacy-crawler.service
systemctl status legacy-crawler.service --no-pager -l
```

audit의 모든 check가 `true`여야 한다. API Key는 `/public/v1/key`에서 받아 memory에서만 사용하며 로그·파일·MongoDB·continuation state에 저장하지 않는다.
