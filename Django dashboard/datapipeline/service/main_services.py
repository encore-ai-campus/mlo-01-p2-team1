from django.utils import timezone

from datapipeline.repository.main_repository import BusinessRepository
from datapipeline.repository.mongodb_repository import MongoRepository
from datapipeline.repository.mysql_repository import PipelineRepository


class MainDashboardService:
    """Aggregate every pipeline source for the command-center dashboard."""

    def __init__(self, main_repository=None, mysql_repository=None, mongodb_repository=None):
        self.main_repository = main_repository or BusinessRepository()
        self.mysql_repository = mysql_repository or PipelineRepository()
        self.mongodb_repository = mongodb_repository or MongoRepository()

    @staticmethod
    def _base_context():
        return {
            "active_section": "main",
            "data_mode": "DEMO DATA",
            "updated_at": timezone.localtime().strftime("%Y-%m-%d %H:%M:%S KST"),
        }

    def get_dashboard(self):
        legacy = self.main_repository.get_legacy_summary()
        mysql = self.mysql_repository.get_acceptance_summary()
        mongo = self.mongodb_repository.get_rejection_summary()
        total_loaded = mysql["load"]["loaded"] + mongo["load"]["loaded"]
        total_expected = legacy["total_received"]
        overall_load_rate = round(total_loaded / total_expected * 100, 1)

        context = self._base_context()
        context.update(
            {
                "legacy": legacy,
                "mysql": mysql,
                "mongo": mongo,
                "overall_load_rate": overall_load_rate,
                "total_loaded": total_loaded,
                "pipeline_events": [
                    {"time": "09:41", "label": "MongoDB 반려 사유 집계 완료", "tone": "purple"},
                    {"time": "09:40", "label": "정규화 accepted 배치 적재 완료", "tone": "green"},
                    {"time": "09:38", "label": "표준화 품질 규칙 32개 통과", "tone": "blue"},
                    {"time": "09:35", "label": "Legacy ERP 증분 수집 완료", "tone": "orange"},
                ],
                "scene_payload": {
                    "legacy": legacy["total_received"],
                    "standardized": mysql["standardized"]["accepted"],
                    "normalized": mysql["normalized"]["accepted"],
                    "mysqlLoaded": mysql["load"]["loaded"],
                    "mongoLoaded": mongo["load"]["loaded"],
                    "standardRejected": mongo["standardized"]["rejected"],
                    "normalRejected": mongo["normalized"]["rejected"],
                    "overallRate": overall_load_rate,
                },
                "chart_payload": {
                    "pipelineThroughput": {
                        "type": "line",
                        "labels": ["07:00", "07:15", "07:30", "07:45", "08:00", "08:15", "08:30", "08:45", "09:00", "09:15", "09:30", "09:45"],
                        "datasets": [
                            {"label": "수집", "color": "#f59e0b", "values": [74, 82, 78, 91, 86, 94, 89, 98, 92, 102, 99, 108]},
                            {"label": "정규화", "color": "#14b8a6", "values": [61, 70, 67, 77, 73, 80, 76, 85, 81, 88, 86, 93]},
                        ],
                        "suffix": "K",
                    },
                    "qualityDistribution": {
                        "type": "doughnut",
                        "labels": ["MySQL accepted", "MongoDB rejected", "적재 대기"],
                        "datasets": [
                            {"values": [98_706, 26_320, 3_374], "colors": ["#14b8a6", "#8b5cf6", "#e2e8f0"]}
                        ],
                        "centerText": f"{overall_load_rate}%",
                        "centerLabel": "전체 적재율",
                    },
                    "legacySourceVolume": {
                        "type": "bar",
                        "horizontal": True,
                        "labels": [source["name"] for source in legacy["sources"]],
                        "datasets": [
                            {
                                "label": "수집량",
                                "color": "#20d9ff",
                                "values": [source["records"] for source in legacy["sources"]],
                            }
                        ],
                    },
                    "rejectReasonVolume": {
                        "type": "bar",
                        "horizontal": True,
                        "labels": [reason["label"] for reason in mongo["reasons"]],
                        "datasets": [
                            {
                                "label": "반려 건수",
                                "color": "#a855f7",
                                "values": [reason["count"] for reason in mongo["reasons"]],
                            }
                        ],
                    },
                },
            }
        )
        return context
