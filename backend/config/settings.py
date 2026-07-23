"""Django settings for a Keel fork — a thin host over keel-base's contract.

The pattern: call ``apply_base_defaults(globals())`` for the neutral core, then set
only what is host-specific below (DB, secret, hosts, static/media, capabilities).
Capability packages (keel-ui / keel-cms / keel-content / keel-seo / keel-web) are
appended to INSTALLED_APPS *after* the call by BOOTSTRAP.md — the base never wires
them itself.
"""

from __future__ import annotations

import os
from pathlib import Path

from keel_base.conf import apply_base_defaults

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

BASE_DIR = Path(__file__).resolve().parent.parent


def _env_truthy(key: str, default: str = "0") -> bool:
    return os.environ.get(key, default).strip().lower() in ("1", "true", "yes", "on")


SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "insecure-dev-key-change-me")
DEBUG = _env_truthy("DJANGO_DEBUG", "1")
ALLOWED_HOSTS = [
    h.strip()
    for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
    if h.strip()
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

# Neutral Keel core: apps, middleware, templates, static, i18n/timezone.
apply_base_defaults(globals())

# Host-specific INSTALLED_APPS additions go here (BOOTSTRAP appends chosen
# capability packages), e.g.:
#     INSTALLED_APPS += ["keel_seo", "keel_ui"]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "keel"),
        "USER": os.environ.get("POSTGRES_USER", "keel"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", "keel"),
        "HOST": os.environ.get("POSTGRES_HOST", "127.0.0.1"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
    }
}

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

# Behind Cloudflare/nginx TLS termination: trust the proxy's scheme header so the
# app treats forwarded HTTPS as secure instead of redirect-looping.
if _env_truthy("DJANGO_BEHIND_PROXY"):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Bumped per release (deploy/prod-deploy.sh sets RELEASE_VERSION to the git SHA) so
# any @cache_page-cached view auto-invalidates on deploy. "dev" locally.
CACHE_VERSION = os.environ.get("RELEASE_VERSION", "dev")

if not DEBUG:
    SECURE_SSL_REDIRECT = _env_truthy("DJANGO_SECURE_SSL_REDIRECT", "0")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
