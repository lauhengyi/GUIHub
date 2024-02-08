# misago_users_online_plugin/urls.py
from django.urls import path

from . import views

app_name = "volunteer-plugin"
urlpatterns = [
    path("volunteer/", views.index, name="index"),
]