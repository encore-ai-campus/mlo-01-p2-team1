class BusinessRepository:
    """Legacy-source read boundary.

    The return shape is the contract used by the service layer. Replace the
    sample body with the team's legacy DB query when its schema is available.
    """

    def get_legacy_summary(self):
        return {
            "source_count": 4,
            "total_received": 128_400,
            "latest_batch": "LEGACY-20260827-0940",
            "sources": [
                {"name": "CRM", "records": 38_420, "state": "수집 완료"},
                {"name": "ERP", "records": 44_180, "state": "수집 완료"},
                {"name": "POS", "records": 31_250, "state": "수집 완료"},
                {"name": "PARTNER", "records": 14_550, "state": "수집 완료"},
            ],
        }
