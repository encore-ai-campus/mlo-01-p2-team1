# How to process

## Silver rule

### 실행 코드 및 산출물

#### Rules

1. 검증 시 모든 산출물에는 `run_id`, 처리 시각, 코드 버전이 명시되어 있어야해.
	- 맨 윗줄에 3줄에 걸쳐 각각 기록해줘.
	- `run_id`는 mongodb의 manifest collection에 기록되어있어.
	- 코드 버전은 지금은 do_standardization(v0.1)을 적어줘
2. 재실행해도 같은 입력과 같은 코드 버전이면 같은 결과가 나오도록 멱등성을 보장한다.
3. 실패한 데이터는 정상 데이터와 섞지 않고 격리하며, 실패 원인과 재처리 여부를 기록한다.

#### Implementation
- 오류 코드

| 검증 항목 | Accepted Candidate 수용 기준 | 실패 상태·코드 |
|---|---|---|
| 행 수 | Bronze 입력 행과 1차 판정 결과를 대사할 수 있음 | 대사 불가 시 실행 실패 | 
| 스키마 | 필수 컬럼이 존재하고 파싱 가능 | `REJECTED_STANDARDIZATION : SCHEMA_MISMATCH` |
| 필수값 | 기본 필수 필드 결측 0건 | `REJECTED_STANDARDIZATION : MISSING_REQUIRED` |
| 타입·날짜 | 표준 타입과 날짜 변환 실패 0건 | `REJECTED_STANDARDIZATION : INVALID_TYPE`, `REJECTED_STANDARDIZATION : INVALID_DATE_FORMAT` |
| 도메인 | 승인된 허용값 밖의 값 0건 | `REJECTED_STANDARDIZATION : DOMAIN_VIOLATION` |
data/bronze/standardization/ingest_data=YYYY-MM-DD/run_id={run_id}

파사드 패턴 적용 : 

	- `do_standardization()` : 메인으로 표준화 작업을 수행할 mongodb에서 데이터를 꺼내와. 이후, 데이터 컬럼의 이름을 `source-to-standard-mapping.csv` 해당 규칙을 보고 변경해, 이후 데이터를 json포맷으로 만들고 처리를 시작할거야. 사전 처리가 다 끝나면, 이제 총 3개의 `check_xxx()`함수를 호출할건데, 각 함수에서는 `standard-terms.csv`, `domain-rules.yaml`에 대한 체크를 수행해. 체크 함수를 수행하면서, 얻은 결과물은 다음과 같아야해.
		- 너가 참조할 두 파일(standard-terms.csv, domain-rules.yaml)들에 대한 경로는 ./docs/standardization/디렉토리에 존재할거야.
		1. `accepted_candidate_rows.csv` : 모든 체크에서 살아남은 row들이 .csv로 컬럼명과 함께 저장된 파일.
		2. `rejected_standardization_rows.csv` : 하나의 체크에서라도 살아남지 못한 row들이 .csv로 컬럼명과 함께 저장된 파일.
		3. `standardization_validation_check.json` : 특정 검사에서 check 통과에 실패한 row들에 대한 정보와 추가로, 어떤 이유 때문에 검사에 실패했는지에 대한 이유가 기술된 파일. 해당 파일은 반드시 오류 코드가 기입되어 있어야 한다.
	추가로, 이 함수는 마지막에 `accepted_candidate_rows.csv`와 `rejected_standardization_rows.csv`파일을 읽어서 총 행의 개수도 카운트해서 입력으로 들어온 원천 데이터의 row와 맞는지 판단해서 `standardization_validation_check.json`의 마지막 줄에 전체 데이터 중에 검증이 완료된 데이터의 비율을 적어줘.
	
	이제, `do_standardization()`함수가 사용할 내부 `check_xxx()`함수들을 기술할게
		- `get_data_from_db(ip, port, user)` : 'mongodb://<ip>:<port>/<user>'를 통해 db와 연결을 수행하고, 연결된 디비의 <collection>로부터 데이터를 읽고, 필요한 부분을 꺼내서 반환하는 함수야. -> 이건 일단 빼고 구현해줘
			- 이 때, 반환값은 반드시 run_id를 가져야하고, 특정 run_id를 where절을 걸었을 때 나오는 bulk rows를 싹 가져올거야.
		- `do_column_mapping(data)` : 이 함수는 `source-to-standard-mapping.csv` 파일을 읽어서  받은 rows를 읽은 데이터 파일의 컬럼명을 표준 컬럼명으로 변경해주는 함수야. 반환값은 변환 완료된 데이터야.
		- `check_validations()` : 이 함수는 
			1) standard-terms.csv, domain-rules.yaml을 읽고, 어떤 row의 특정 컬럼에 적용된 domain 규칙을 파악하고, 해당 도메인 규칙에 맞는 속성값 범위를 파악해.
			2) 만약, 도메인 규칙을 벗어난 값들에 대해서 적절하게 올바른 도메인 규칙으로 변경할 수 있다면 변경하고, 변경할 수 없다면 그 이유를 적어줘.
			3) 데이터의 전체 데이터에 대해서 2번을 적용하고 나면 반드시, `accepted_candidate_rows.csv`와 `rejected_standardization_rows.csv`, `standardization_validation_check.json`라는 산출물이 나와야해.
		- 최종적으로 이 함수의 반환값은 다음과 같아
			{
				'run_id' : run_id,
				'accepted_candidate_row_count' : n,
				'rejected_row_count' : m,
				'accepted_candidate_row_list' : 
					[row1, row2, ..., row n],
				'rejected_row_list' : 
					[row1, row2, ..., row m],
			}
		- 이 과정에서 필요한 함수가 있다면 너가 직접 만들어줘.

- 이 때, 산출물을 만들 때, `./data/silver/standardization/ingest_date=YYYY-MM-DD/run_id={run_id}/` 밑에 각 파일을 생성할거야.

## 구현 사용법

MongoDB 연결과 조회는 이 모듈 밖에서 수행한다. 조회 결과는 다음과 같이
`manifest`와 `rows`를 포함한 JSON 객체로 전달한다.

```python
from src.standardization import do_standardization

result = do_standardization(
    {
        "manifest": {
            "run_id": "20260827-001",
            "ingest_date": "2026-08-27",
        },
        "rows": mongo_rows,
    }
)
```

운영 환경에서는 `src/standardization/requirements.txt`의 PyYAML 의존성을
설치한다. 동일한 입력, 규칙 파일, 코드 버전으로 같은 `run_id`를 재실행하면
기존 산출물을 변경하지 않고 반환한다. 같은 `run_id`에 다른 입력이 들어오면
기존 결과의 덮어쓰기를 막기 위해 실행을 실패시킨다.

## functions

### get_raw_data_from_mongodb()
- 해당 함수는 mongodb server에 연결해서 raw data를 가져오는 역할을 수행한다.

1. Document를 단순 `find()`로 읽어오지 않고, `find_one_and_update()`를 사용한다. 따라서, `processing_status의` `pending` -> `in_progress`변경을 원자적으로 처리한다.
2. mongodb의 manifest 콜렉션에 `crawl_status`를 도입하고, `crawl_status==running`인 데이터는 가져오지 않는다.
3. 즉, 데이터를 가져오는 조건식은 manifest 컬렉션의 `crawl_status==completed` and `processing_status==pending`인 경우다.
4. mongodb에서 일반 컬렉션에서 격리 컬렉션으로 옮기는 작업은 하나의 transaction으로 묶어야 한다.
5. audit module또한 `crawl_status==completed` and `processing_status==pending`인 데이터에 대해서만 처리한다.


1. mongodb에는 총 4개의 collection이 존재한다.
	1) manifest collection
	2) raw_datas collection
	3) 격리_manifest collection
	4) 격리 raw_datas collection

2. manifest collection에서 `crawl_status==completed` and `processing_status==pending`인 documents를 찾고 가장 첫번째 document의 `run_id`, `total_bytes`를 꺼낸다.
3. `run_id`를 이용해서 `raw_datas collection에서 데이터를 꺼낸다.
4. `total_bytes`와 `raw_datas`의 전체 크기를 비교해 데이터 변조 여부를 체크하고, 변조가 없다면 해당 데이터를 반환한다. 단, 변조가 있다면 audit module을 호출해서 격리시킨다.
5. 만약, 전체 과정에서 한 부분에서라도 에러가 발생하면, 로그를 만들고 종료한다.(?) -> 종료를 해야할까? 아니면 다시 try하는게 좋을까?

6. audit module은 crontab과 같은 스케쥴링 프로그램을 이용해서 manifest collection에서 `crawl_status==completed` and `processing_status==pending`인 랜덤한 `run_id`를 가져오고, 얘네들에 대해 Sha-256검사를 수행한다.

만약, 이상이 있으면 모두 격리 manifest, 격리 raw_datas 콜렉션으로 넘긴다.
