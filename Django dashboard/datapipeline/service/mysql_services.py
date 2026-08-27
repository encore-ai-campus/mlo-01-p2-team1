from django.utils import timezone

from datapipeline.repository.mysql_repository import PipelineRepository


class MySQLDashboardService:
    """Build the accepted-data dashboard from the MySQL repository contract."""

    def __init__(self, mysql_repository=None):
        self.mysql_repository = mysql_repository or PipelineRepository()

    @staticmethod
    def _base_context():
        return {
            "active_section": "mysql",
            "data_mode": "DEMO DATA",
            "updated_at": timezone.localtime().strftime("%Y-%m-%d %H:%M:%S KST"),
        }

    def get_dashboard(self):
        mysql = self.mysql_repository.get_acceptance_summary()
        context = self._base_context()
        context.update(
            {
                "mysql": mysql,
                "chart_payload": {
                    "mysqlLoadTrend": {
                        "type": "line",
                        "labels": ["07:00", "07:15", "07:30", "07:45", "08:00", "08:15", "08:30", "08:45", "09:00", "09:15", "09:30", "09:45"],
                        "datasets": [
                            {"label": "적재율", "color": "#f59e0b", "fill": True, "values": mysql["hourly_rate"]}
                        ],
                        "suffix": "%",
                    },
                    "mysqlStageVolume": {
                        "type": "bar",
                        "labels": ["수집", "표준화 승인", "정규화 승인", "MySQL 적재"],
                        "datasets": [
                            {"label": "레코드(K)", "color": "#14b8a6", "values": [128.4, 108.2, 101.8, 98.7]}
                        ],
                        "suffix": "K",
                    },
                    "mysqlTableLoad": {
                        "type": "bar",
                        "horizontal": True,
                        "labels": [table["name"] for table in mysql["tables"]],
                        "datasets": [
                            {"label": "적재율", "color": "#20d9ff", "values": [table["rate"] for table in mysql["tables"]]}
                        ],
                        "suffix": "%",
                    },
                    "mysqlAcceptance": {
                        "type": "doughnut",
                        "labels": ["정규화 accepted", "단계 이탈", "적재 대기"],
                        "datasets": [
                            {"values": [98_706, 26_640, 3_054], "colors": ["#15e6c1", "#a855f7", "#f59e0b"]}
                        ],
                        "centerText": "97.0%",
                        "centerLabel": "MySQL 적재율",
                    },
                },
            }
        )
        return context
