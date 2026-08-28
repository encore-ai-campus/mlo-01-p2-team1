from django.shortcuts import render

from datapipeline.service.gold_services import GoldDashboardService
from datapipeline.service.main_services import MainDashboardService
from datapipeline.service.mongodb_services import MongoDBDashboardService
from datapipeline.service.mysql_services import MySQLDashboardService


main_dashboard_service = MainDashboardService()
mysql_dashboard_service = MySQLDashboardService()
mongodb_dashboard_service = MongoDBDashboardService()
gold_dashboard_service = GoldDashboardService()


def main_dashboard(request):
    return render(
        request,
        "datapipeline/main-dashboard.html",
        main_dashboard_service.get_dashboard(),
    )


def mysql_dashboard(request):
    return render(
        request,
        "datapipeline/mysql-dashboard.html",
        mysql_dashboard_service.get_dashboard(),
    )


def mongodb_dashboard(request):
    return render(
        request,
        "datapipeline/mongodb-dashboard.html",
        mongodb_dashboard_service.get_dashboard(),
    )


def gold_dashboard(request):
    return render(
        request,
        "datapipeline/gold-dashboard.html",
        gold_dashboard_service.get_dashboard(),
    )
