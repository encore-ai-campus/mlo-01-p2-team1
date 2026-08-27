from django.conf import settings
from django.test import SimpleTestCase

from datapipeline.repository.mongodb_repository import (
    MongoRepository,
    MongoRepositoryError,
)


class FakeCollection:
    def __init__(self, *, documents=None, aggregate_rows=None, failure=None):
        self.documents = documents or []
        self.aggregate_rows = aggregate_rows or []
        self.failure = failure
        self.find_calls = []
        self.aggregate_calls = []

    def find(self, query, projection):
        self.find_calls.append((query, projection))
        if self.failure:
            raise self.failure
        return list(self.documents)

    def aggregate(self, pipeline):
        self.aggregate_calls.append(pipeline)
        if self.failure:
            raise self.failure
        return list(self.aggregate_rows)


class MongoRepositoryTests(SimpleTestCase):
    def _repository(self, standard, normalization):
        database = {
            settings.MONGODB["STANDARDIZATION_REJECTED_COLLECTION"]: standard,
            settings.MONGODB["NORMALIZATION_REJECTED_COLLECTION"]: normalization,
        }
        return MongoRepository(database=database, data_mode="live")

    def test_one_rejected_document_with_three_errors_counts_one_row_and_three_occurrences(self):
        run_id = "run-unit-20260827T104049Z-0001"
        standard = FakeCollection(
            documents=[
                {
                    "run_id": run_id,
                    "business_area_id": "BIZ_11608",
                    "_source_row_number": 2,
                    "errors": [
                        {
                            "error_code": "REJECTED_STANDARDIZATION : MISSING_REQUIRED",
                            "column": "business_area_name",
                            "reason": "필수값 누락",
                        },
                        {
                            "error_code": "REJECTED_STANDARDIZATION : INVALID_DATE_FORMAT",
                            "column": "manager_hire_datetime",
                            "reason": "날짜 오류",
                        },
                        {
                            "error_code": "REJECTED_STANDARDIZATION : DOMAIN_VIOLATION",
                            "column": "manager_active_yn",
                            "reason": "도메인 오류",
                        },
                    ],
                }
            ]
        )
        repository = self._repository(standard, FakeCollection())

        summary = repository.get_rejection_summary(run_id)

        self.assertEqual(summary["total_rejected_rows"], 1)
        self.assertEqual(summary["total_error_occurrences"], 3)
        self.assertEqual(summary["stages"]["standardization"]["rejected_rows"], 1)
        self.assertEqual(summary["stages"]["standardization"]["error_occurrences"], 3)
        self.assertEqual(len(summary["recent_rejections"]), 3)
        self.assertEqual(
            {item["code"] for item in summary["error_codes"]},
            {"MISSING_REQUIRED", "INVALID_DATE_FORMAT", "DOMAIN_VIOLATION"},
        )
        self.assertEqual(standard.find_calls[0][0], {"run_id": run_id})

    def test_summary_detects_duplicate_rows_empty_errors_and_malformed_codes(self):
        run_id = "run-unit-20260827T104049Z-0002"
        standard = FakeCollection(
            documents=[
                {"_source_row_number": 2, "errors": []},
                {
                    "_source_row_number": 2,
                    "errors": [
                        {
                            "error_code": "REJECTED_NORMALIZATION : WRONG_STAGE",
                            "column": "business_area_id",
                        },
                        "not-a-document",
                    ],
                },
            ]
        )
        repository = self._repository(standard, FakeCollection())

        summary = repository.get_rejection_summary(run_id)

        self.assertEqual(summary["duplicate_document_count"], 1)
        self.assertEqual(summary["rows_without_errors"], 1)
        self.assertEqual(summary["malformed_error_count"], 2)
        self.assertEqual(summary["total_error_occurrences"], 1)

    def test_same_code_occurrences_and_affected_rows_are_separate(self):
        run_id = "run-unit-20260827T104049Z-0003"
        code = "REJECTED_STANDARDIZATION : MISSING_REQUIRED"
        standard = FakeCollection(
            documents=[
                {
                    "_source_row_number": 1,
                    "errors": [{"error_code": code}, {"error_code": code}],
                },
                {"_source_row_number": 2, "errors": [{"error_code": code}]},
            ]
        )
        repository = self._repository(standard, FakeCollection())

        reason = repository.get_rejection_summary(run_id)["error_codes"][0]

        self.assertEqual(reason["occurrence_count"], 3)
        self.assertEqual(reason["affected_row_count"], 2)

    def test_run_counts_combines_both_collection_aggregations(self):
        run_ids = ["run-a", "run-b"]
        standard = FakeCollection(
            aggregate_rows=[{"_id": "run-a", "rejected_rows": 2, "error_occurrences": 4}]
        )
        normalization = FakeCollection(
            aggregate_rows=[{"_id": "run-b", "rejected_rows": 1, "error_occurrences": 1}]
        )
        repository = self._repository(standard, normalization)

        result = repository.get_run_counts(run_ids)

        self.assertEqual(result["run-a"]["standardization"]["rejected_rows"], 2)
        self.assertEqual(result["run-a"]["normalization"]["rejected_rows"], 0)
        self.assertEqual(result["run-b"]["normalization"]["error_occurrences"], 1)
        self.assertEqual(repository.get_run_counts([]), {})

    def test_missing_run_id_and_database_failures_are_repository_errors(self):
        repository = self._repository(FakeCollection(), FakeCollection())
        with self.assertRaises(MongoRepositoryError):
            repository.get_rejection_summary("")

        failing = self._repository(
            FakeCollection(failure=RuntimeError("mongo offline")),
            FakeCollection(),
        )
        with self.assertRaises(MongoRepositoryError) as raised:
            failing.get_rejection_summary("run-test")
        self.assertIsInstance(raised.exception.__cause__, RuntimeError)

    def test_sample_mode_does_not_open_injected_database(self):
        repository = MongoRepository(database=None, data_mode="sample")

        summary = repository.get_rejection_summary("run-sample-20260827T104049Z-0000")

        self.assertEqual(summary["total_rejected_rows"], 3)
        self.assertEqual(summary["total_error_occurrences"], 5)
