from django.urls import path

from . import views

app_name = "datapipeline"

urlpatterns = [
    path("", views.main_dashboard, name="main"),
    path("mysql/", views.mysql_dashboard, name="mysql"),
    path("mongodb/", views.mongodb_dashboard, name="mongodb"),
]
