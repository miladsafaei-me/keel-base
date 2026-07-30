# Neutral Keel base image. Plain slim Python — deliberately NO Playwright, no
# fonts, no capability packages baked in. Those are capability concerns: a fork
# that installs keel-ui (hero rasterization) or keel-content (Playwright renders)
# switches this FROM to the Playwright image and adds the fonts/system deps it
# needs. The base stays small so a CMS-only or signals-only fork carries nothing
# it does not use.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV DEBIAN_FRONTEND=noninteractive

WORKDIR /app

# `git` is required at build time: a fork pins capabilities as `keel-* @ git+https://…`
# and `pip install` shells out to git to fetch them. libpq5 is the Postgres client lib.
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Install deps first for layer caching. requirements.txt installs this repo's
# keel-base package (`.[server]`) plus any capability pins a fork adds.
COPY pyproject.toml MANIFEST.in README.md ./
COPY src/ ./src/
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Optional browser stack for keel-crawler[browser] (crawl4ai + Playwright anti-bot
# crawling), implemented ONCE here so every fork can use it instead of wiring its own
# Playwright base image. A fork that needs browser crawling: (1) pins
# `keel-crawler[browser]` in requirements.txt (brings crawl4ai + playwright + lxml),
# and (2) builds with `--build-arg KEEL_BROWSER=1` — which installs the Chromium binary
# and its system libraries here. Default 0 keeps CMS-only / signals-only forks slim:
# the RUN is a no-op and Playwright's Python deps never arrive unless the fork pins the
# extra. The GitHub Actions build passes this arg (see .github/workflows).
ARG KEEL_BROWSER=0
RUN if [ "$KEEL_BROWSER" = "1" ]; then \
        python -m playwright install --with-deps chromium; \
    fi

# The capability registry lives at the repo root, not inside the package. Copy it
# to /app so keel_base.capabilities.load_registry() (which searches upward from the
# gunicorn WORKDIR /app/backend) resolves it at runtime — otherwise the catalog is
# empty and the admin "enabled-but-not-installed" flag can't work. Copied after the
# pip layer so editing it never busts the dependency cache.
COPY keel-capabilities.yml ./

COPY backend/ ./backend/

WORKDIR /app/backend

EXPOSE 8000
ENTRYPOINT ["sh", "entrypoint.sh"]
CMD ["gunicorn", "-c", "gunicorn.conf.py", "config.wsgi:application"]
