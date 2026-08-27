from django.test import SimpleTestCase
from django.urls import reverse

from datapipeline.service.main_services import MainDashboardService
from datapipeline.service.mongodb_services import MongoDBDashboardService
from datapipeline.service.mysql_services import MySQLDashboardService


class DashboardRouteTests(SimpleTestCase):
    def test_dashboard_pages_render_and_link_to_each_other(self):
        pages = {
            "datapipeline:main": "DATA PIPELINE",
            "datapipeline:mysql": "ACCEPTED MONITOR",
            "datapipeline:mongodb": "REJECTION MONITOR",
        }

        for route_name, heading in pages.items():
            with self.subTest(route=route_name):
                response = self.client.get(reverse(route_name))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, heading)
                self.assertContains(response, reverse("datapipeline:main"))
                self.assertContains(response, reverse("datapipeline:mysql"))
                self.assertContains(response, reverse("datapipeline:mongodb"))
                self.assertContains(response, "echarts.min.js")

    def test_main_dashboard_includes_three_js_pipeline_scene(self):
        response = self.client.get(reverse("datapipeline:main"))

        self.assertContains(response, 'id="pipeline-scene"')
        self.assertContains(response, "pipeline-3d.js")
        self.assertContains(response, "pipeline-scene-data")


class DashboardServiceTests(SimpleTestCase):
    def test_main_load_rate_is_derived_from_repository_totals(self):
        context = MainDashboardService().get_dashboard()

        expected = round(context["total_loaded"] / context["legacy"]["total_received"] * 100, 1)
        self.assertEqual(context["overall_load_rate"], expected)
        self.assertEqual(context["data_mode"], "DEMO DATA")

    def test_database_services_use_their_own_repository_contracts(self):
        mysql_context = MySQLDashboardService().get_dashboard()
        mongodb_context = MongoDBDashboardService().get_dashboard()

        self.assertIn("mysql", mysql_context)
        self.assertNotIn("mongo", mysql_context)
        self.assertIn("mongo", mongodb_context)
        self.assertNotIn("mysql", mongodb_context)
