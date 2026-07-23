from django.http import JsonResponse
from django.shortcuts import render

from .models import SiteProfile


def home(request):
    """Neutral landing for a fresh fork; a real project overrides this URL."""
    try:
        profile = SiteProfile.load()
        ctx = {
            "brand_name": profile.brand_name,
            "enabled_capabilities": profile.enabled_capabilities,
        }
    except Exception:
        # Pre-migrate / no-DB boot (e.g. a bare `check`): still render something.
        ctx = {"brand_name": "Keel Site", "enabled_capabilities": []}
    return render(request, "keel_base/home.html", ctx)


def healthz(request):
    """Liveness probe for the canary + compose healthchecks. No DB dependency."""
    return JsonResponse({"status": "ok"})
