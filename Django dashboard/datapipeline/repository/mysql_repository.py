class PipelineRepository:
    """MySQL accepted-data read boundary.

    Only this class needs to change when the accepted-table schema arrives.
    """

    def get_acceptance_summary(self):
        return {
            "standardized": {"accepted": 108_240, "input": 128_400, "rate": 84.3},
            "normalized": {"accepted": 101_760, "input": 108_240, "rate": 94.0},
            "load": {"loaded": 98_706, "expected": 101_760, "rate": 97.0},
            "freshness": "42초 전",
            "tables": [
                {
                    "name": "standard_customers",
                    "stage": "표준화",
                    "loaded": 24_950,
                    "expected": 25_000,
                    "rate": 99.8,
                    "status": "정상",
                },
                {
                    "name": "standard_transactions",
                    "stage": "표준화",
                    "loaded": 48_640,
                    "expected": 50_000,
                    "rate": 97.3,
                    "status": "정상",
                },
                {
                    "name": "normalized_products",
                    "stage": "정규화",
                    "loaded": 14_930,
                    "expected": 15_000,
                    "rate": 99.5,
                    "status": "정상",
                },
                {
                    "name": "normalized_orders",
                    "stage": "정규화",
                    "loaded": 10_186,
                    "expected": 11_760,
                    "rate": 86.6,
                    "status": "확인 필요",
                },
            ],
            "recent_batches": [
                {"id": "B-0827-0940", "stage": "정규화", "rows": 8_420, "duration": "01:42", "status": "완료"},
                {"id": "B-0827-0920", "stage": "표준화", "rows": 10_180, "duration": "02:11", "status": "완료"},
                {"id": "B-0827-0900", "stage": "정규화", "rows": 7_960, "duration": "01:39", "status": "완료"},
                {"id": "B-0827-0840", "stage": "표준화", "rows": 9_740, "duration": "02:06", "status": "완료"},
            ],
            "hourly_rate": [86, 90, 89, 93, 92, 95, 96, 94, 98, 97, 99, 97],
        }
