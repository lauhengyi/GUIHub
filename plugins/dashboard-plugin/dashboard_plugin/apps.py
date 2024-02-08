# misago_users_online_plugin/apps.py
from django.apps import AppConfig


class VolunteerPlugin(AppConfig):
    name = "dashboard_plugin"

    def ready(self):
        pass