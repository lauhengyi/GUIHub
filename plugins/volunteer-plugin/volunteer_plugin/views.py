# misago_users_online_plugin/views.py
from datetime import timedelta

from django.http import HttpRequest, HttpResponse
from django.core.exceptions import PermissionDenied
from django.shortcuts import render
from django.utils import timezone
from django.utils.translation import pgettext
from misago.users.models import Online


def index(request: HttpRequest) -> HttpResponse:
    if not request.user.is_authenticated:
        raise PermissionDenied(
            pgettext(
                "volunteer plugin",
                "You need to be signed in to view this page.",
            )
        )

    users_online = Online.objects.filter(
        last_click__gte=timezone.now() - timedelta(minutes=15),
    ).select_related("user")

    return render(
        request,
        "volunteer/index.html",
        {"users_online": users_online},
    )