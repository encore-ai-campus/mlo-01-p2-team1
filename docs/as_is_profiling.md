# AS-IS 데이터 프로파일링 리포트 v1.1


## 1. 공식 기준선

| 파일명 | 기준 행 수 | 컬럼 수 | 역할 |
|---|---:|---:|---|
| `biz_employee_master.csv` | 3,000 | 6 | 직원 마스터 |
| `biz_meta_area_50000.csv` | 50,000 | 5 | 업무 영역 마스터 |
| `biz_meta_area_join_ready.csv` | 50,000 | 9 | 조인 대조용 |
| `biz_meta_area_parent_lookup.csv` | 1,000 | 4 | 최상위 영역 조회 |
| 합계 | 104,000 | 24 | 파일별 컬럼 합계 |

고유 필드 수: 16개

## 2. 샘플 원시 데이터 스냅샷 프로파일

| 항목 | 진단 결과 |
|---|---|
| 분석 대상 | `biz_legacy_integrated_raw_20260825.csv` 공개 원시 스냅샷 |
| 기술적 grain | `record_id` 하나가 원천 `source_row_no` 하나와 대응하는 스냅샷 행 |
| 업무적 grain | 하나의 업무영역에 상위·최상위 영역 및 담당자 속성이 함께 적재된 원시 레코드 |
| 수집 순서 | `release_slot`과 `scheduled_release_at`이 일관되게 대응하며 공개 순서를 추적할 수 있음 |
| 원시 보존 원칙 | CSV 값은 수정하지 않고 보존하며, 정규화 결과와 예외 사유는 별도 표준화 계층에서 관리 |

## 3. Grain 및 키 구조

| 키 후보 | 관측 결과 | 판단 |
|---|---|---|
| `record_id` | 누락이나 중복 없이 행을 구분하는 기술 식별자 | 스냅샷 행의 기술 PK로 사용 가능 |
| `source_row_no` | 원천 수집 순서를 추적하는 값 | 원천 행 추적용 보조 기술키 |
| `source_record_sha256` | 원천 레코드 변경 여부를 확인할 수 있는 해시 | 무결성·변경 감지용 보조키 |
| 원시 전체 행 | 완전히 동일한 행은 관측되지 않음 | 자동 중복 삭제 대상 없음 |
| `business_area_id` | 표준화 뒤에도 같은 업무영역 ID가 여러 행에서 관측됨 | 스냅샷 행 PK로 사용하지 않음 |
| `(business_area_id, manager_id)` | 복합해도 반복되는 조합이 존재함 | 스냅샷 행 PK로 사용하지 않음 |

동일 `business_area_id`의 반복은 완전 중복이 아니라 이름·등록일시·담당자 등 속성 차이를 포함할 수 있다. 따라서 삭제 규칙을 적용하기보다 기준정보 확인 후 이력(SCD) 관리 여부를 결정해야 한다.

## 4. 컬럼별 기초 프로파일

`domain-rules.yaml`의 NULL 토큰(`''`, `-`, `NULL`, `N/A`, `NA`, `UNKNOWN`)을 기준으로 해석한다. `없음`은 현재 NULL 토큰에 없으므로 업무 승인 전에는 자동 NULL 변환 대상이 아니다.

| 컬럼군 | 주요 AS-IS 관측 | 표준화 방향 |
|---|---|---|
| 기술 식별자 | `record_id`, `source_row_no`, 해시는 안정적으로 행과 원천을 추적할 수 있음 | 원시값 보존 및 기술키로 관리 |
| 공개 메타데이터 | 공개 슬롯과 예정 시각은 수집 순서와 시점을 설명함 | 수집·적재 이력으로 보존 |
| 업무영역·담당자 ID | 공백, 하이픈, 밑줄, 대소문자가 혼재함 | 공백·구분자 정리 후 표준 ID 재구성 |
| 영역·담당자 명칭 | 외부 공백, 탭, 전각 공백, NULL 계열 표기가 섞여 있음 | Unicode 정규화, trim, NULL 정책 적용 |
| 최상위 수준 코드 | 같은 의미를 영문·한글·숫자 등 여러 방식으로 표현함 | 정의된 매핑으로 `TOP` 통일, 미상은 NULL 처리 |
| 담당자 활성 상태 | `Y/N`, 숫자, 한글 상태 표현 및 미상 값이 혼재함 | `Y/N`으로 매핑하고 미상은 NULL 및 사유 기록 |
| 담당자 직위 | 공백 변형과 미상 표현이 존재함 | 허용 직위 사전 매칭, 임의 문자열 삭제 금지 |
| 날짜·시간 | 여러 허용 형식과 비정상 sentinel 값이 함께 존재함 | 허용 형식 파싱, sentinel 격리 및 NULL 전환 |

## 5. 도메인·날짜·분포 진단

### 5.1 식별자 도메인

| 원시 컬럼 | 표준 도메인 | 원시 표기 이슈 | 처리 방향 |
|---|---|---|---|
| `area_no` | `BIZ_#####` | 하이픈·공백·밑줄·대소문자 혼재 | 표기 정규화 후 표준 ID 재구성 |
| `p_area_no` | 선택형 `BIZ_#####` | NULL 계열 토큰 및 `없음` 혼재 | NULL 허용 정책을 적용하되 `없음`은 업무 확인 후 처리 |
| `top_area_no` | `BIZ_#####` | 하이픈·공백·밑줄·대소문자 혼재 | 표기 정규화 후 표준 ID 재구성 |
| `mgr_no` | `EMP######` | 공백·하이픈·대소문자 및 `UNKNOWN` 혼재 | 표기 정규화, `UNKNOWN`은 NULL 후보로 관리 |

원시 컬럼명 `area_no`, `mgr_nm`, `mgr_hire_dtm` 등의 레거시 약어는 AS-IS 품질 오류가 아니다. `naming-rules.yaml`은 raw 보존 후 Silver/curated 계층에서 `business_area_id`, `manager_name`, `manager_hire_datetime` 등으로 적용한다.

### 5.2 코드·상태 도메인

| 컬럼 | 원시 관측 | 표준화 방향 |
|---|---|---|
| `top_area_lvl` | `TOP_LEVEL`, `L1`, `top_level`, `최상위`, `TOP LEVEL`, `1`, `UNKNOWN` 등 의미가 겹치는 표현이 혼재 | 정의된 매핑으로 `TOP` 통일, `UNKNOWN`은 NULL 및 사유 기록 |
| `mgr_act_yn` | `Y/N`, `YES/NO`, 숫자, 한글 상태값, `UNKNOWN`이 혼재 | `YES`·`1`·`사용`·`재직`은 `Y`, `NO`·`0`·`미사용`·`퇴직`은 `N`으로 매핑 |
| `mgr_pos_nm` | 공백 변형과 `미상` 등 사전 확인이 필요한 표현이 존재 | 사전 매칭된 직위만 정규화하고, 그 외 값은 임의로 삭제하지 않음 |

### 5.3 날짜 진단

원시 날짜는 ISO T, `yyyy-mm-dd hh:mm:ss`, 소수초, slash, dot, 압축 표기 등 허용된 여러 형식으로 존재한다. `9999-99-99 99:99:99`, `0000-00-00 00:00:00`, `9999/99/99 99:99:99` 같은 sentinel은 실제 일시가 아니므로 NULL 전환 대상이며, 원본값과 reject 사유를 함께 보관해야 한다.

| 컬럼 | 관측 | 처리 방향 |
|---|---|---|
| `mgr_hire_dtm` | 허용 형식과 invalid sentinel이 혼재 | ISO 초 단위로 파싱, sentinel 격리 |
| `area_reg_dtm` | 허용 형식과 invalid sentinel이 혼재 | ISO 초 단위로 파싱, sentinel 격리 |
| `top_area_reg_dtm` | 허용 형식과 invalid sentinel이 혼재 | ISO 초 단위로 파싱, sentinel 격리 |

## 6. 주요 품질 이슈

| 품질 항목 | 발견 여부 | 실제 예시 | 처리 방향 |
|---|---|---|---|
| 완전 중복 행 | 없음 | - | 삭제 대상 없음 |
| 업무영역 자연키 반복 | 있음 | 동일 표준 업무영역 ID에 서로 다른 속성이 함께 존재 | 자동 삭제 금지, 기준정보/SCD 정책 확인 |
| 외부·내부 공백 | 있음 | ` BIZ_19140 `, ` 김수아 ` | NFKC 후 trim, 반복 공백 축소 |
| 탭·전각 공백 | 있음 | `기획\t`, `　팀장　` | 일반 공백으로 변환 후 정규화 |
| NULL 계열 토큰 | 있음 | `NULL`, `N/A`, `-`, `UNKNOWN` | 컬럼별 NULL 허용 정책 적용 |
| 미매핑 결측 후보 | 있음 | `p_area_no='없음'` | 업무 승인 전에는 자동 NULL 변환 금지 |
| 날짜 sentinel | 있음 | `9999-99-99 99:99:99` | NULL 전환 및 reject 사유 보관 |
| 계층 코드 불일치 | 있음 | `TOP_LEVEL`, `L1`, `최상위` | `TOP`으로 매핑 |
| 상태 코드 불일치 | 있음 | `사용`, `YES`, `1`, `N` | `Y/N`으로 매핑 |

## 7. PK/FK 및 조인 정합성 기준선

### 7.1 스냅샷 내부 영역 조인

현재 파일 안에서 `p_area_no`와 `top_area_no`를 `area_no`에 대조하면, 원시 문자열의 공백·구분자·대소문자 차이 때문에 정확 일치 조인이 제한된다. 표준 ID로 정규화하면 내부 조인 가능 범위가 늘어나므로 식별자 표기 혼재가 직접적인 조인 저해 요인으로 판단된다.

다만 이 파일은 전체 업무영역 마스터가 아닌 공개 스냅샷이므로, 표준화 뒤에도 연결되지 않는 참조는 **스냅샷 내부 미해결 참조**로 기록한다. 전체 영역 마스터 제공 전에는 FK orphan으로 확정하지 않는다.

### 7.2 관계 및 기준정보 일관성

| 관계 | 관측 | 해석 |
|---|---|---|
| `business_area_id → parent_business_area_id` | 동일 업무영역의 상위 영역 ID는 표준화 후 일관되게 관측됨 | 계층 ID 관계는 표준화 후 검증 가능 |
| `business_area_id → top_business_area_id` | 동일 업무영역의 최상위 영역 ID는 표준화 후 일관되게 관측됨 | 계층 ID 관계는 표준화 후 검증 가능 |
| `business_area_id → business_area_name` | 같은 ID에 결측 또는 상이한 명칭이 관측됨 | 기준정보 확인 필요 |
| `top_business_area_id → top_business_area_name` | 공백 변형 및 일부 상이 명칭이 관측됨 | 표준 명칭 사전 필요 |
| `manager_id → manager_name` | 공백 변형·결측 및 상이 값 가능성이 관측됨 | 직원 마스터 대조 필요 |
| `manager_id → manager_department_name` | 공백 변형 외 실제 소속 변경 가능성이 있음 | 이력 관리 여부 확인 필요 |

`manager_id → employee master` FK는 직원 마스터가 제공되지 않아 orphan 여부를 산출하지 않는다.

## 8. AS-IS → 표준화 대상

`standard-terms.csv`는 원시 컬럼을 표준 용어에 대응시킨다. 아래 표는 업무·기술 컬럼을 함께 표시한다.

| AS-IS 컬럼 | 표준 컬럼 | 도메인/처리 기준 |
|---|---|---|
| `record_id` | `record_id` | `RECORD_ID`, 기술 PK |
| `source_row_no` | `source_row_number` | `SOURCE_ROW_NUMBER`, 원천 순번 |
| `source_record_sha256` | `source_record_sha256_hash` | `SHA256_HASH`, 원천 무결성 |
| `release_slot` | `release_slot` | `RELEASE_SLOT`, 공개 슬롯 |
| `scheduled_release_at` | `scheduled_release_datetime` | `DATETIME_KST_ISO_SECOND` |
| `area_no` | `business_area_id` | `BUSINESS_AREA_ID`, `BIZ_#####` 재구성 |
| `area_nm` | `business_area_name` | `BUSINESS_AREA_NAME`, NULL 토큰 처리 |
| `p_area_no` | `parent_business_area_id` | `OPTIONAL_BUSINESS_AREA_ID`, `없음` 승인 필요 |
| `p_area_nm` | `parent_business_area_name` | `BUSINESS_AREA_NAME`, 선택형 NULL |
| `top_area_no` | `top_business_area_id` | `BUSINESS_AREA_ID`, `BIZ_#####` 재구성 |
| `top_area_nm` | `top_business_area_name` | `BUSINESS_AREA_NAME` |
| `top_area_lvl` | `top_business_area_level_code` | `TOP_AREA_LEVEL_CODE`, `TOP` 매핑 |
| `mgr_no` | `manager_id` | `MANAGER_ID`, `EMP######` 재구성 |
| `mgr_nm` | `manager_name` | `PERSON_NAME` |
| `mgr_dept_nm` | `manager_department_name` | `DEPARTMENT_NAME` |
| `mgr_pos_nm` | `manager_position_name` | `MANAGER_POSITION_NAME`, 허용 직위 사전 |
| `mgr_hire_dtm` | `manager_hire_datetime` | `DATETIME_ISO_SECOND`, sentinel NULL |
| `mgr_act_yn` | `manager_active_yn` | `YES_NO`, `Y/N` 매핑 |
| `area_reg_dtm` | `business_area_registration_datetime` | `DATETIME_ISO_SECOND`, sentinel NULL |
| `top_area_reg_dtm` | `top_business_area_registration_datetime` | `DATETIME_ISO_SECOND`, sentinel NULL |

## 9. 요약

- 원시 샘플의 주요 이슈는 식별자·명칭·직위에 섞인 공백과 표기 변형, 코드·상태값의 다중 표현, 날짜 sentinel이다.
- 스냅샷 행의 PK는 `record_id`로 관리한다. `business_area_id` 및 `(business_area_id, manager_id)`는 반복 가능성이 있어 행 PK로 사용하지 않는다.
- Silver 계층에서는 Unicode/공백 정규화, 식별자 재구성, `top_area_lvl`·`mgr_act_yn` 도메인 매핑, 날짜 파싱 및 sentinel 격리를 우선 처리한다.
- `p_area_no='없음'`의 NULL 인정 여부, 반복 업무영역 ID의 우선 레코드 또는 SCD 처리, 동일 ID의 명칭·부서·직위 차이 허용 여부는 업무 확인이 필요하다.
- 조인 검증은 표준 ID 기준으로 수행하고, 전체 업무영역·직원 마스터가 제공된 뒤 확정 FK 정합성 검증으로 전환한다.
