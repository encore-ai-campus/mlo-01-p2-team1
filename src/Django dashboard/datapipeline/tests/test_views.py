from django.test import SimpleTestCase
from django.urls import reverse


class DashboardViewSmokeTests(SimpleTestCase):
    """Local rendering regression checks; these never access external databases."""

    def test_dashboard_pages_render_and_link_to_each_other(self):
        pages = {
            "datapipeline:main": "DATA PIPELINE",
            "datapipeline:mysql": "ACCEPTED MONITOR",
            "datapipeline:mongodb": "REJECTION MONITOR",
            "datapipeline:gold": "INTELLIGENCE CENTER",
        }

        for route_name, heading in pages.items():
            with self.subTest(route=route_name):
                response = self.client.get(reverse(route_name))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, heading)
                self.assertContains(response, reverse("datapipeline:main"))
                self.assertContains(response, reverse("datapipeline:mysql"))
                self.assertContains(response, reverse("datapipeline:mongodb"))
                self.assertContains(response, reverse("datapipeline:gold"))
                self.assertContains(response, "echarts.min.js")

    def test_main_dashboard_includes_three_js_pipeline_scene(self):
        response = self.client.get(reverse("datapipeline:main"))

        self.assertContains(response, 'id="pipeline-scene"')
        self.assertContains(response, "pipeline-3d.js")
        self.assertContains(response, "pipeline-scene-data")

    def test_gold_dashboard_includes_constellation_and_feature_explorer(self):
        response = self.client.get(reverse("datapipeline:gold"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="gold-constellation"')
        self.assertContains(response, "gold-3d.js")
        self.assertContains(response, "MANAGER FEATURE EXPLORER")
        self.assertContains(response, "gold-scene-data")
