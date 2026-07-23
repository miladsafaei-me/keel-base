#!/usr/bin/env bash
# Keel production deploy — canary-gated blue-green cutover.
#
# Run from the repo root on the prod host (the GitHub Actions deploy job does
# `git reset --hard origin/main` then execs this). Lives in the repo so any edit
# ships via the normal flow. Generalized from SignalBots' proven script; every
# project-specific value is externalized into deploy/deploy.env (Bucket-3 blank)
# and deploy/critical-paths.txt, so a fork changes values, never this logic.
#
# Why a real file, not an inline `script:` block: appleboy/ssh-action ships such
# blocks through `bash -c "<long-string>"`, where any apostrophe or shell
# metacharacter is fragile (it caused two parse-error deploy failures upstream).

set -euo pipefail

cd "$(dirname "$0")/.."

# Project-specific values. deploy/deploy.env is the Bucket-3 blank a fork fills;
# defaults keep the script runnable unconfigured.
if [ -f deploy/deploy.env ]; then
    set -a
    # shellcheck disable=SC1091
    . deploy/deploy.env
    set +a
fi

PROJECT_SLUG="${PROJECT_SLUG:-keel}"
IMAGE_REF="${IMAGE_REF:-ghcr.io/OWNER/keel-web:latest}"
PROD_HOST="${PROD_HOST:-localhost}"
COMPOSE_PROD="${COMPOSE_PROD:-compose.prod.yaml}"

NETWORK="${PROJECT_SLUG}_default"
MEDIA_VOL="${PROJECT_SLUG}_media"
WEB="${PROJECT_SLUG}-web"
WEB_BLUE="${PROJECT_SLUG}-web-blue"
CANARY_NAME="${PROJECT_SLUG}-canary"
CANARY_PORT="${CANARY_PORT:-8009}"

# Serialize deploys on the host. The GitHub deploy job already runs one at a time,
# but a manual run could overlap. Hold an exclusive lock for the whole script; a
# second invocation waits up to 5m then aborts rather than corrupting the pair.
# The 5m wait is deliberately shorter than the ssh-action command_timeout so a
# stuck deploy fails cleanly inside the GH window instead of leaking an orphan.
#
# fd 9 is closed (`9>&-`) on every `podman compose up`/`podman run` below: without
# it the long-lived conmon of each recreated container inherits fd 9 and holds the
# flock for the container's ENTIRE lifetime, so the next deploy blocks forever.
exec 9>/tmp/${PROJECT_SLUG}-deploy.lock
if ! flock -w 300 9; then
    echo "[deploy] ERROR: another deploy still holds the lock after 5m — aborting"
    exit 1
fi

# Pin the cache version to the git short SHA so every release auto-invalidates
# @cache_page-cached views. Exported so compose substitutes it into compose.prod.yaml.
export RELEASE_VERSION="$(git rev-parse --short HEAD)"
echo "[deploy] RELEASE_VERSION=${RELEASE_VERSION}  IMAGE_REF=${IMAGE_REF}"

# Optional nginx config sync (set NGINX_CONF_SRC + NGINX_CONF_DST in deploy.env).
if [ -n "${NGINX_CONF_SRC:-}" ] && [ -n "${NGINX_CONF_DST:-}" ]; then
    echo "[deploy] Syncing nginx config..."
    if ! sudo cmp -s "$NGINX_CONF_SRC" "$NGINX_CONF_DST"; then
        echo "[deploy] nginx config changed — applying"
        sudo install -m 0644 "$NGINX_CONF_SRC" "$NGINX_CONF_DST"
        sudo nginx -t
        sudo systemctl reload nginx
    fi
fi

echo "[deploy] Pulling new image..."
podman pull "$IMAGE_REF"

# oneshot: run a manage.py command in a throwaway container on the new image. We
# bypass `podman compose run --rm web` on purpose — podman-compose v1.x treats it
# as "operate on the whole project" and STOPS every running service first, opening
# a no-upstream window that surfaces as a 502. `podman run` talks to the engine
# directly and never touches project containers. ENTRYPOINT_BOOTSTRAP=none so the
# entrypoint waits for db (DNS-race safety) but does not re-run collectstatic.
oneshot() {
    podman run --rm \
        --network "$NETWORK" \
        --env-file .env \
        -e POSTGRES_HOST=db \
        -e POSTGRES_PORT=5432 \
        -e REDIS_URL=redis://redis:6379/0 \
        -e DJANGO_BEHIND_PROXY=1 \
        -e RELEASE_VERSION="${RELEASE_VERSION}" \
        -e ENTRYPOINT_BOOTSTRAP=none \
        -v "${MEDIA_VOL}:/app/backend/media:z" \
        "$IMAGE_REF" \
        "$@"
}

# Apply migrations on the new image BEFORE swapping running containers — schema is
# in place before the new app code starts serving.
echo "[deploy] Running migrations..."
oneshot python manage.py migrate --noinput

# Critical pages the deploy refuses to ship broken. wait_for_port only proves a
# container ANSWERS on its port; it does not prove the app can RENDER these. Read
# from deploy/critical-paths.txt (one path per line, # comments allowed). Default
# to just "/" so an unconfigured fork still gates on the homepage.
CRITICAL_PATHS=()
if [ -f deploy/critical-paths.txt ]; then
    while IFS= read -r line; do
        line="${line%%#*}"; line="$(echo "$line" | xargs || true)"
        [ -n "$line" ] && CRITICAL_PATHS+=("$line")
    done < deploy/critical-paths.txt
fi
[ ${#CRITICAL_PATHS[@]} -eq 0 ] && CRITICAL_PATHS=("/")

# probe_http <port>: exits 0 + prints the HTTP code only on a real 2xx/3xx. curl -w
# always prints a status (000 on connect-refused/timeout) AND exits non-zero on
# transport failure — so a naive `|| echo 000` would double-append into "000000".
probe_http() {
    local port="$1" code
    code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 3 \
        "http://127.0.0.1:${port}/" 2>/dev/null || true)
    if [ -z "$code" ]; then code="000"; fi
    case "$code" in
        *[!0-9]*) return 1 ;;
        000)      return 1 ;;
        5??)      return 1 ;;
        ???)      printf "%s" "$code"; return 0 ;;
        *)        return 1 ;;
    esac
}

# wait_for_port <port> <name>: wait up to 120s for a stable HTTP 2xx/3xx. After
# first success, require 5 consecutive successes — a container can bind at the
# port-forwarder while its entrypoint is still running and about to crash.
wait_for_port() {
    local port="$1" name="$2" i j code code2
    echo "[deploy] Waiting for ${name} on 127.0.0.1:${port}..."
    for i in $(seq 1 120); do
        if code=$(probe_http "$port"); then
            echo "[deploy] ${name} ready after ${i}s (HTTP ${code})"
            for j in 1 2 3 4 5; do
                sleep 1
                if ! code2=$(probe_http "$port"); then
                    echo "[deploy] ${name} regressed ${j}s after ready — keep waiting"
                    continue 2
                fi
            done
            echo "[deploy] ${name} stayed healthy for 5s — committed"
            return 0
        fi
        sleep 1
    done
    echo "[deploy] ERROR: ${name} did not become ready within 120s — recent logs:"
    podman logs --tail 80 "${name}" || true
    return 1
}

# smoke <port>: GET every critical path straight at gunicorn on 127.0.0.1:<port>.
# Sends the prod Host so ALLOWED_HOSTS passes, and X-Forwarded-Proto: https so the
# app renders instead of 301-to-https. Non-zero on the first 4xx/5xx/transport error.
smoke() {
    local port="$1" path code bad=0
    for path in "${CRITICAL_PATHS[@]}"; do
        code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 15 \
            -H "Host: ${PROD_HOST}" -H "X-Forwarded-Proto: https" \
            "http://127.0.0.1:${port}${path}" 2>/dev/null || true)
        if [ -z "$code" ]; then code="000"; fi
        case "$code" in
            2??|3??) echo "[deploy]   OK   ${code}  ${path}" ;;
            *)       echo "[deploy]   FAIL ${code}  ${path}"; bad=1 ;;
        esac
    done
    return $bad
}

# Canary gate: validate the new image BEFORE it can take any live traffic. nginx
# load-balances onto web-blue the instant it is recreated, and a Django 500 is NOT
# in proxy_next_upstream — so a broken image entering the upstream is user-visible.
# We first boot the new image as a throwaway OUTSIDE the nginx upstream, smoke every
# critical page against real prod data, and only proceed if clean. If not, we abort
# with web (8006) AND web-blue (8007) still on the previous image — zero user impact.
cleanup_canary() { podman rm -f "$CANARY_NAME" >/dev/null 2>&1 || true; }
trap cleanup_canary EXIT

echo "[deploy] Canary: booting new image on ${CANARY_PORT} (outside the nginx upstream)..."
podman run -d --replace --name "$CANARY_NAME" \
    --network "$NETWORK" \
    -p "127.0.0.1:${CANARY_PORT}:8000" \
    --env-file .env \
    -e POSTGRES_HOST=db \
    -e POSTGRES_PORT=5432 \
    -e REDIS_URL=redis://redis:6379/0 \
    -e DJANGO_BEHIND_PROXY=1 \
    -e RELEASE_VERSION="${RELEASE_VERSION}" \
    -e ENTRYPOINT_BOOTSTRAP=skip \
    -v "${MEDIA_VOL}:/app/backend/media:z" \
    "$IMAGE_REF" 9>&-

if ! wait_for_port "$CANARY_PORT" "$CANARY_NAME"; then
    echo "[deploy] ERROR: canary did not become ready — aborting deploy."
    echo "[deploy] web (8006) and web-blue (8007) remain on the PREVIOUS image — no user impact."
    exit 1
fi

echo "[deploy] Canary: smoking ${#CRITICAL_PATHS[@]} critical pages against real prod data..."
if ! smoke "$CANARY_PORT"; then
    echo "[deploy] ERROR: new image failed critical-page smoke — ABORTING deploy."
    echo "[deploy] web (8006) and web-blue (8007) remain on the PREVIOUS image — no user impact."
    podman logs --tail 80 "$CANARY_NAME" || true
    exit 1
fi
echo "[deploy] Canary passed — new image renders every critical page. Proceeding with cutover."
cleanup_canary
trap - EXIT

# Blue-green recreate: blue (8007) first while web (8006) keeps serving; once blue
# is healthy, recreate web while blue takes the load. nginx upstream lists both
# with max_fails=0 + proxy_next_upstream, so a request hitting the recreating side
# re-routes to the live sibling — no user-visible 502. --no-deps everywhere so the
# recreate does not also target db/redis.
echo "[deploy] Recreating ${WEB_BLUE}..."
podman compose -f "$COMPOSE_PROD" up -d --no-deps --force-recreate web-blue 9>&-
wait_for_port 8007 "$WEB_BLUE"

echo "[deploy] Recreating ${WEB}..."
podman compose -f "$COMPOSE_PROD" up -d --no-deps --force-recreate web 9>&-
wait_for_port 8006 "$WEB"

# Final guard: both sides must be running at end of deploy. Catches a container that
# became reachable, settled, then died before the next step.
for c in "$WEB" "$WEB_BLUE"; do
    state=$(podman inspect --format "{{.State.Status}}" "$c" 2>/dev/null || echo missing)
    if [ "$state" != "running" ]; then
        echo "[deploy] ERROR: ${c} is in state [${state}] at end of deploy — recent logs:"
        podman logs --tail 80 "$c" || true
        exit 1
    fi
done

# Recreate any background workers (celery/celery-beat) IF this fork defines them —
# after both web sides are live so a failed worker image does not block the web
# rollout. A base fork with no workers skips this cleanly.
workers=""
for svc in celery celery-beat; do
    if podman compose -f "$COMPOSE_PROD" config --services 2>/dev/null | grep -qx "$svc"; then
        workers="$workers $svc"
    fi
done
if [ -n "$workers" ]; then
    echo "[deploy] Recreating workers:${workers}..."
    # shellcheck disable=SC2086
    podman compose -f "$COMPOSE_PROD" up -d --no-deps --force-recreate $workers 9>&-
fi

podman image prune -f

echo "[deploy] Deploy complete — new image live on ${WEB} + ${WEB_BLUE}."
exit 0
