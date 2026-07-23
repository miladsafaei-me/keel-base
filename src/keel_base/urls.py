from django.urls import path

from . import views

app_name = "keel_base"

urlpatterns = [
    path("", views.home, name="home"),
    path("healthz", views.healthz, name="healthz"),
]
