from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    # Neutral base routes (home + healthz). A real fork mounts its own capability
    # URLconfs here (e.g. blog, signals) and typically overrides "".
    path("", include("keel_base.urls")),
]
