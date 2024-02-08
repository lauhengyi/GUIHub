# misago_users_online_plugin/urls.py
from django.urls import path

from . import views

app_name = "dashboard-plugin"
urlpatterns = [
    path("dashboard/", views.index, name="index"),
]