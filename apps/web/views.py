from django.conf import settings
from django.shortcuts import render


def index(request):
    """Single-page web client for the API (all data is loaded via fetch + JWT)."""
    return render(request, "web/index.html", {"demo_tools": settings.DEBUG})
