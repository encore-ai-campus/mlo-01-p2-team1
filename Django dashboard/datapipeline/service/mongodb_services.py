from django.utils import timezone

from datapipeline.repository.mongodb_repository import MongoRepository


class MongoDBDashboardService:
    """Build the rejected-data dashboard from the MongoDB repository contract."""

    def __init__(self, mongodb_repository=None):
        self.mongodb_repository = mongodb_repository or MongoRepository()

    @staticmethod
    def _base_context():
        return {
            "active_section": "mongodb",
            "data_mode": "DEMO DATA",
            "updated_at": timezone.localtime().strftime("%Y-%m-%d %H:%M:%S KST"),
        }

    def get_dashboard(self):
        mongo = self.mongodb_repository.get_rejection_summary()
        context = self._base_context()
        context.update(
            {
                "mongo": mongo,
                "chart_payload": {
                    "mongoReasonVolume": {
                        "type": "bar",
                        "labels": [reason["label"] for reason in mongo["reasons"]],
                        "datasets": [
                            {"label": "반려 건수", "color": "#8b5cf6", "values": [reason["count"] for reason in mongo["reasons"]]}
                        ],
                    },
                    "mongoStageSplit": {
                        "type": "doughnut",
                        "labels": ["표준화 rejected", "정규화 rejected"],
                        "datasets": [
                            {"values": [mongo["standardized"]["rejected"], mongo["normalized"]["rejected"]], "colors": ["#8b5cf6", "#f59e0b"]}
                        ],
                        "centerText": "26,640",
                        "centerLabel": "총 반려",
                    },
                    "mongoCollectionLoad": {
                        "type": "bar",
                        "horizontal": True,
                        "labels": [collection["name"] for collection in mongo["collections"]],
                        "datasets": [
                            {"label": "적재율", "color": "#a855f7", "values": [collection["rate"] for collection in mongo["collections"]]}
                        ],
                        "suffix": "%",
                    },
                    "mongoRejectTrend": {
                        "type": "line",
                        "labels": ["07:00", "07:15", "07:30", "07:45", "08:00", "08:15", "08:30", "08:45", "09:00", "09:15", "09:30", "09:45"],
                        "datasets": [
                            {"label": "rejected", "color": "#a855f7", "fill": True, "values": [1.42, 1.66, 1.58, 1.91, 1.77, 2.08, 1.96, 2.27, 2.12, 2.36, 2.24, 2.41]}
                        ],
                        "suffix": "K",
                    },
                },
            }
        )
        return context
