"""Gunicorn defaults for a Keel fork (WORKDIR: backend/).

``timeout`` is generous so a long capability request (e.g. a content-pipeline
generation or a Playwright render, once those capabilities are installed) does not
get killed and surface as a 502. A fork with only fast views can lower it.

``reload`` is gated on GUNICORN_RELOAD ("1" in local .env, unset on prod) so local
dev auto-reloads on .py changes via the bind-mount while prod keeps static workers.
"""

import os

bind = "0.0.0.0:8000"
workers = int(os.environ.get("GUNICORN_WORKERS", "2"))
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "1200"))
graceful_timeout = 120
reload = os.environ.get("GUNICORN_RELOAD", "0") == "1"
