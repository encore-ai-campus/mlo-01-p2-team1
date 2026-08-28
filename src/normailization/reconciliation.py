"""표준화와 최종 품질검증 과정에서 행이 빠지지 않았는지 확인한다."""


STANDARDIZATION_RESULT_KEYS = (
    "run_id",
    "accepted_candidate_row_count",
    "rejected_row_count",
    "accepted_candidate_row_list",
    "rejected_row_list",
)

FINAL_RESULT_KEYS = (
    "run_id",
    "final_accepted_row_count",
    "final_rejected_row_count",
    "final_accepted_row_list",
    "final_rejected_row_list",
)


def validate_result_shape(result, result_name, result_keys):
    """팀에서 합의한 결과 딕셔너리의 키와 건수를 검사한다."""
    missing = [key for key in result_keys if key not in result]
    if missing:
        raise ValueError(f"{result_name}에 키가 없습니다: {', '.join(missing)}")

    if result_name == "standardization_result":
        accepted_count_key = "accepted_candidate_row_count"
        rejected_count_key = "rejected_row_count"
        accepted_list_key = "accepted_candidate_row_list"
        rejected_list_key = "rejected_row_list"
    else:
        accepted_count_key = "final_accepted_row_count"
        rejected_count_key = "final_rejected_row_count"
        accepted_list_key = "final_accepted_row_list"
        rejected_list_key = "final_rejected_row_list"

    accepted_rows = result[accepted_list_key]
    rejected_rows = result[rejected_list_key]

    if result["run_id"] is None or str(result["run_id"]).strip() == "":
        raise ValueError(f"{result_name}의 run_id가 비어 있습니다.")

    for count_key in (accepted_count_key, rejected_count_key):
        if not isinstance(result[count_key], int) or result[count_key] < 0:
            raise ValueError(f"{result_name}의 {count_key}는 0 이상의 정수여야 합니다.")

    if not isinstance(accepted_rows, list) or not isinstance(rejected_rows, list):
        raise TypeError(f"{result_name}의 row_list는 list여야 합니다.")

    if any(not isinstance(row, dict) for row in accepted_rows + rejected_rows):
        raise TypeError(f"{result_name}의 각 row는 dict여야 합니다.")

    if result[accepted_count_key] != len(accepted_rows):
        raise ValueError(f"{result_name}의 Accepted 건수와 실제 리스트 길이가 다릅니다.")

    if result[rejected_count_key] != len(rejected_rows):
        raise ValueError(f"{result_name}의 Rejected 건수와 실제 리스트 길이가 다릅니다.")


def reconcile_counts(raw_row_count, standardization_result, final_result):
    """원본→표준화→최종검증의 세 가지 행 수 보존식을 검사한다."""
    validate_result_shape(
        standardization_result,
        "standardization_result",
        STANDARDIZATION_RESULT_KEYS,
    )
    validate_result_shape(final_result, "final_result", FINAL_RESULT_KEYS)

    if standardization_result["run_id"] != final_result["run_id"]:
        raise ValueError("standardization_result와 final_result의 run_id가 다릅니다.")

    standard_accepted = standardization_result["accepted_candidate_row_count"]
    standard_rejected = standardization_result["rejected_row_count"]
    final_accepted = final_result["final_accepted_row_count"]
    final_rejected = final_result["final_rejected_row_count"]

    standardization_pass = raw_row_count == standard_accepted + standard_rejected
    final_partition_pass = standard_accepted == final_accepted + final_rejected
    total_pass = raw_row_count == standard_rejected + final_accepted + final_rejected

    return {
        "raw_row_count": raw_row_count,
        "standardization_accepted_row_count": standard_accepted,
        "standardization_rejected_row_count": standard_rejected,
        "final_accepted_row_count": final_accepted,
        "final_rejected_row_count": final_rejected,
        "standardization_partition_pass": standardization_pass,
        "final_partition_pass": final_partition_pass,
        "total_reconciliation_pass": total_pass,
    }
