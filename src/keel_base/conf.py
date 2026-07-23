"""Settings-merge contract for keel-base.

A consuming project calls ``apply_base_defaults(globals())`` once from its Django
settings module and gets the neutral Keel core wired: the ``keel_base`` core app,
a sane middleware stack, static/template dirs, and baseline i18n/timezone. Every
value is applied with ``setdefault`` / extend semantics — never replace — so the
host overrides anything by assigning after the call.

Invariant (do NOT break): the core imports NO optional capability. keel-ui,
keel-cms, keel-content, keel-seo, and keel-web are added by the host *after* this
call (BOOTSTRAP.md wires them into INSTALLED_APPS + requirements). Keeping the core
capability-free is what lets a fork install only the capabilities it needs — a
CMS-only fork and a signals-only fork share this same base.

Modeled on resonans-cms's ``apply_cms_defaults`` pattern, neutralized to a base.
"""

from __future__ import annotations

import os
from pathlib import Path

_PACKAGE_DIR = Path(__file__).resolve().parent
_TEMPLATES_DIR = _PACKAGE_DIR / "templates"
_STATIC_DIR = _PACKAGE_DIR / "static"


def _env_truthy(key: str, default: str = "0") -> bool:
    return os.environ.get(key, default).strip().lower() in ("1", "true", "yes", "on")


# Neutral core apps only. No allauth, no Unfold, no capability packages — those
# belong to keel-web / a chosen capability, not the base. A fork that wants them
# appends them after apply_base_defaults(globals()).
DEFAULT_APPS = (
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "keel_base",
)

DEFAULT_MIDDLEWARE = (
    "django.middleware.security.SecurityMiddleware",
    # WhiteNoise serves collected static without a separate web server. Kept here
    # because static serving is base infrastructure, not an optional capability.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
)


def apply_base_defaults(namespace: dict) -> None:
    """Merge keel-base defaults into a Django settings ``globals()`` dict.

    Existing keys are respected (``setdefault``); INSTALLED_APPS / MIDDLEWARE are
    extended, never replaced, so a host adds its own apps and capability packages
    without losing the base.
    """
    apps = list(namespace.get("INSTALLED_APPS", []))
    for app in DEFAULT_APPS:
        if app not in apps:
            apps.append(app)
    namespace["INSTALLED_APPS"] = apps

    middleware = list(namespace.get("MIDDLEWARE", []))
    for mw in DEFAULT_MIDDLEWARE:
        if mw not in middleware:
            middleware.append(mw)
    namespace["MIDDLEWARE"] = middleware

    namespace.setdefault("DEFAULT_AUTO_FIELD", "django.db.models.BigAutoField")
    # No AUTH_USER_MODEL here on purpose: the base uses Django's default User so a
    # fork without keel-web still boots. keel-web sets AUTH_USER_MODEL when installed.

    namespace.setdefault("LANGUAGE_CODE", "en-us")
    namespace.setdefault("TIME_ZONE", "UTC")
    namespace.setdefault("USE_I18N", True)
    namespace.setdefault("USE_TZ", True)

    # WhiteNoise compressed-manifest storage keeps prod static serving self-contained.
    namespace.setdefault(
        "STORAGES",
        {
            "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
            "staticfiles": {
                "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
            },
        },
    )

    templates = list(namespace.get("TEMPLATES", []))
    if not templates:
        templates = [
            {
                "BACKEND": "django.template.backends.django.DjangoTemplates",
                "DIRS": [],
                "APP_DIRS": True,
                "OPTIONS": {
                    "context_processors": [
                        "django.template.context_processors.debug",
                        "django.template.context_processors.request",
                        "django.contrib.auth.context_processors.auth",
                        "django.contrib.messages.context_processors.messages",
                    ],
                },
            }
        ]
    dirs = list(templates[0].get("DIRS", []))
    if str(_TEMPLATES_DIR) not in dirs:
        dirs.append(str(_TEMPLATES_DIR))
    templates[0]["DIRS"] = dirs
    namespace["TEMPLATES"] = templates

    staticfiles_dirs = list(namespace.get("STATICFILES_DIRS", []))
    if str(_STATIC_DIR) not in staticfiles_dirs and _STATIC_DIR.exists():
        staticfiles_dirs.append(str(_STATIC_DIR))
    namespace["STATICFILES_DIRS"] = staticfiles_dirs
