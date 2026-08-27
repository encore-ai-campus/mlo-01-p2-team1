class MongoRepository:
    """MongoDB rejected-data read boundary.

    Replace this sample body with collection aggregations when connection and
    field names are agreed with the data team.
    """

    def get_rejection_summary(self):
        return {
            "standardized": {"rejected": 20_160, "input": 128_400, "rate": 15.7},
            "normalized": {"rejected": 6_480, "input": 108_240, "rate": 6.0},
            "load": {"loaded": 26_320, "expected": 26_640, "rate": 98.8},
            "freshness": "38초 전",
            "collections": [
                {
                    "name": "standardization_rejected",
                    "stage": "표준화",
                    "loaded": 19_958,
                    "expected": 20_160,
                    "rate": 99.0,
                    "status": "정상",
                },
                {
                    "name": "normalization_rejected",
                    "stage": "정규화",
                    "loaded": 6_362,
                    "expected": 6_480,
                    "rate": 98.2,
                    "status": "정상",
                },
            ],
            "reasons": [
                {"code": "MISSING_REQUIRED", "label": "필수값 누락", "count": 10_123, "rate": 38.0},
                {"code": "INVALID_TYPE", "label": "타입 불일치", "count": 7_459, "rate": 28.0},
                {"code": "DUPLICATE", "label": "중복 데이터", "count": 5_062, "rate": 19.0},
                {"code": "REFERENCE_NOT_FOUND", "label": "참조값 없음", "count": 2_664, "rate": 10.0},
                {"code": "OUT_OF_RANGE", "label": "허용범위 초과", "count": 1_332, "rate": 5.0},
            ],
            "recent_rejections": [
                {"time": "09:41:18", "record": "ORD-884201", "stage": "정규화", "reason": "REFERENCE_NOT_FOUND"},
                {"time": "09:40:52", "record": "CUS-192784", "stage": "표준화", "reason": "MISSING_REQUIRED"},
                {"time": "09:40:31", "record": "PAY-540221", "stage": "표준화", "reason": "INVALID_TYPE"},
                {"time": "09:39:47", "record": "PRD-029118", "stage": "정규화", "reason": "DUPLICATE"},
                {"time": "09:39:12", "record": "ORD-884172", "stage": "표준화", "reason": "OUT_OF_RANGE"},
            ],
        }
