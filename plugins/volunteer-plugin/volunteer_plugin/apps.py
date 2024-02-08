# misago_users_online_plugin/apps.py
from django.apps import AppConfig


class VolunteerPlugin(AppConfig):
    name = "volunteer_plugin"

    def ready(self):
        pass