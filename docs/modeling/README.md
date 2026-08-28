# 데이터 모델링·적재 흐름

## 목적

MongoDB 원본을 표준화·정규화한 뒤, Final Accepted만 MySQL 적재 대상으로 만든다.

## 실행 흐름

```text
main.run_all()
→ get_raw_data_from_mongoDB()로 원본 문서 목록 조회
→ payload를 표준화 행으로 만들고 _ingest.run_id를 보존
→ do_standardization(...)
→ 표준화 결과 5개 키만 전달
→ run_normalization(...)과 행 수 대사
→ PASS면 결과 파일 생성
→ Final Accepted MySQL UPSERT
→ 표준화·정규화 Rejected를 MongoDB의 두 컬렉션에 저장
→ pipeline_status=pass
→ pipeline_run_summary에 RUNNING/SUCCESS/실패 사실값 기록
```

## 소스 구조

| 파일 | 역할 |
|---|---|
| `src/main.py` | MongoDB 조회부터 표준화·최종검증·MySQL 적재·Manifest 상태 변경까지 연결 |
| `src/standardization/` | MongoDB 원본 조회와 Accepted Candidate·Rejected 생성 |
| `src/normailization/normalization.py` | Final Accepted·Rejected 판정과 결과 파일 저장 |
| `src/normailization/reconciliation.py` | 표준화 인계 건수와 Final 분할 건수 검사 |
| `src/standardization/get_raw_data_from_mongodb.py` | `payload` 행과 `_ingest.run_id` 조회, Manifest `pipeline_status` 변경 |
| `src/loader/mysql_loader.py` | Final Accepted와 배치 사실값을 MySQL에 트랜잭션 적재 |
| `src/loader/write_rejected_rows_to_mongodb.py` | 표준화·정규화 Rejected를 단계별 MongoDB 컬렉션에 저장 |
| `src/schema/schema.sql` | manager·top_area·area·pipeline_run_summary DDL과 View |
| `docs/modeling/dashboard_data_contract.md` | 대시보드 조회 컬럼과 KPI 계산 계약 |
| `docs/modeling/run_id_compensation.md` | MySQL rollback과 Manifest 상태 처리 |
| `docs/notes/modeling_questions_and_answers.md` | 설계 과정에서 발생한 이슈·결정·해결 상태 기록 |

## 표준화 결과

```python
{
    "run_id": run_id,
    "accepted_candidate_row_count": n,
    "rejected_row_count": m,
    "accepted_candidate_row_list": [...],
    "rejected_row_list": [...],
}
```

## 최종 품질검증 결과

```python
{
    "run_id": run_id,
    "final_accepted_row_count": x,
    "final_rejected_row_count": y,
    "final_accepted_row_list": [...],
    "final_rejected_row_list": [...],
}
```

## 구현 완료

- 표준화 담당자의 5개 키 결과를 받는 인계 경계 작성
- 표준화 Accepted+Rejected를 인계 기준 건수로 계산
- 최종 결과의 `final_*` 반환 계약 적용
- 행 수 보존식 구현
- MySQL 연결·DDL·트랜잭션 적재 함수 작성
- MySQL 세 테이블에 `run_id`를 저장하고 팀의 반복 관측 규칙에 따라 UPSERT
- `run_id`를 숨긴 업무 View와 배치 사실값 View 작성
- `pipeline_run_summary`에 단계별 판정 건수와 엔터티별 목표/적재 건수 저장
- MySQL 적재 실패 rollback 테스트 작성
- 두 Rejected 결과 형식의 MongoDB 저장과 같은 run 재실행 시 교체 처리

`run_all()`의 최종 연결은 구현되어 있다. MongoDB와 MySQL은 하나의 ACID 트랜잭션이 아니므로 MySQL 업무 테이블은 자체 트랜잭션으로 rollback하고, 이후 단계가 실패하면 `pipeline_run_summary`에 실패 상태를 남긴다. Manifest의 `pipeline_status=pass`는 MySQL 적재와 MongoDB Rejected 저장이 모두 끝난 뒤에만 기록한다. Django 화면 구현만 이 저장소의 담당 범위가 아니다.

MySQL 적재기는 `.env`의 `DB1_*` 값을 사용한다. Raw MongoDB는 `RAW_MONGO_*`와 `MONGO_RAW_*`를 사용한다. 대시보드 담당자는 별도 Django repository에서 MySQL 서버에 직접 접속해 `dashboard_area_view`와 `dashboard_pipeline_run_view`를 SELECT한다. 이 저장소에서 JSON을 대시보드에 전달하거나 Django context를 생성하지 않는다.

테스트는 프로젝트 루트에서 `python -m unittest discover -s tests -v`로 실행한다.
