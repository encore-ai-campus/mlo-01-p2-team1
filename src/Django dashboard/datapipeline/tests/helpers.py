from copy import deepcopy
from datetime import timedelta

from django.utils import timezone

from datapipeline.service.mongodb_services import empty_mongo_facts


def make_run(now=None, **overrides):
    """Return a reconciled, recent SUCCESS run suitable for unit tests."""
    now = now or timezone.now()
    started_at = now - timedelta(minutes=2)
    completed_at = started_at + timedelta(seconds=30)
    run = {
        "run_id": started_at.strftime("run-unit-%Y%m%dT%H%M%SZ-0001"),
        "raw_row_count": 16,
        "standardization_accepted_count": 14,
        "standardization_rejected_count": 2,
        "final_accepted_count": 13,
        "final_rejected_count": 1,
        "manager_target_count": 5,
        "manager_loaded_count": 5,
        "top_area_target_count": 2,
        "top_area_loaded_count": 2,
        "area_target_count": 13,
        "area_loaded_count": 13,
        "started_at": started_at,
        "completed_at": completed_at,
        "batch_status": "SUCCESS",
        "error_message": None,
        "created_at": started_at,
        "updated_at": completed_at,
    }
    run.update(overrides)
    return run


def make_mongo_facts(
    run_id,
    *,
    standard_rows=2,
    normalization_rows=1,
    standard_errors=None,
    normalization_errors=None,
    error_codes=None,
    recent_rejections=None,
    rows_without_errors=0,
    malformed_error_count=0,
    duplicate_document_count=0,
):
    facts = empty_mongo_facts(run_id)
    standard_errors = standard_rows if standard_errors is None else standard_errors
    normalization_errors = (
        normalization_rows if normalization_errors is None else normalization_errors
    )
    facts["stages"]["standardization"]["rejected_rows"] = standard_rows
    facts["stages"]["standardization"]["error_occurrences"] = standard_errors
    facts["stages"]["standardization"]["run_counts"] = {
        run_id: {
            "rejected_rows": standard_rows,
            "error_occurrences": standard_errors,
        }
    }
    facts["stages"]["normalization"]["rejected_rows"] = normalization_rows
    facts["stages"]["normalization"]["error_occurrences"] = normalization_errors
    facts["stages"]["normalization"]["run_counts"] = {
        run_id: {
            "rejected_rows": normalization_rows,
            "error_occurrences": normalization_errors,
        }
    }
    facts["total_rejected_rows"] = standard_rows + normalization_rows
    facts["total_error_occurrences"] = standard_errors + normalization_errors
    facts["error_codes"] = deepcopy(error_codes or [])
    facts["recent_rejections"] = deepcopy(recent_rejections or [])
    facts["rows_without_errors"] = rows_without_errors
    facts["malformed_error_count"] = malformed_error_count
    facts["duplicate_document_count"] = duplicate_document_count
    return facts


class FakeMySQLRepository:
    def __init__(self, run=None, history=None, *, current_error=None, history_error=None, all_error=None):
        self.run = deepcopy(run)
        self.history = deepcopy(history if history is not None else ([run] if run else []))
        self.current_error = current_error
        self.history_error = history_error
        self.all_error = all_error
        self.latest_calls = 0
        self.all_calls = 0
        self.summary_calls = []
        self.history_calls = []

    def _current(self):
        if self.current_error:
            raise self.current_error
        return deepcopy(self.run)

    def get_latest_run_summary(self):
        self.latest_calls += 1
        return self._current()

    def get_run_summary(self, run_id):
        self.summary_calls.append(run_id)
        return self._current()

    def get_run_history(self, limit=12):
        self.history_calls.append(limit)
        if self.history_error:
            raise self.history_error
        return deepcopy(self.history)

    def get_all_run_summaries(self):
        self.all_calls += 1
        if self.all_error:
            raise self.all_error
        return deepcopy(self.history)


class FakeMongoRepository:
    def __init__(self, facts=None, trend=None, *, summary_error=None, trend_error=None):
        self.facts = deepcopy(facts)
        self.trend = deepcopy(trend or {})
        self.summary_error = summary_error
        self.trend_error = trend_error
        self.summary_calls = []
        self.multi_summary_calls = []
        self.trend_calls = []

    def get_rejection_summary(self, run_id):
        self.summary_calls.append(run_id)
        if self.summary_error:
            raise self.summary_error
        return deepcopy(self.facts)

    def get_run_counts(self, run_ids):
        self.trend_calls.append(list(run_ids))
        if self.trend_error:
            raise self.trend_error
        return deepcopy(self.trend)

    def get_rejection_summary_for_runs(self, run_ids):
        self.multi_summary_calls.append(list(run_ids))
        if self.summary_error:
            raise self.summary_error
        return deepcopy(self.facts)
