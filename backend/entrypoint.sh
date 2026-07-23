#!/bin/bash
set -e
# Keel base entrypoint. WORKDIR is backend/. Three startup modes via
# ENTRYPOINT_BOOTSTRAP, matching the deploy contract in deploy/prod-deploy.sh:
#
# - full (default): wait for db, then migrate + collectstatic. Used by local
#   `podman compose up` so a fresh bring-up is fully usable.
# - skip: collectstatic only, no migrate. Set on the long-running prod web /
#   web-blue services (compose.prod.yaml) — migrate already ran via a separate
#   deploy oneshot, and skipping it here shortens the gunicorn-bind window during
#   a blue-green recreate (the window that produces 502s). collectstatic still
#   runs because STATIC_ROOT lives in the container's writable layer, not a volume.
# - none: wait for db reachability then exec, nothing else. Used by deploy
#   oneshots (`podman run --rm` for migrate) so they get the DNS-retry safety but
#   do not double-run collectstatic.
#
# Capability-specific bootstrap (e.g. keel-ui's generate_webp, once installed)
# does NOT belong in this base file. A fork drops an executable
# backend/scripts/bootstrap-extra.sh and it runs after collectstatic in full/skip
# modes — keeping the base capability-free.

db_host="${POSTGRES_HOST:-db}"
db_port="${POSTGRES_PORT:-5432}"

wait_for_db() {
    # Podman's aardvark-dns can briefly return "name not known" during rapid
    # container churn (blue-green deploys), and Postgres may still be booting on a
    # cold start. Without this loop, `migrate` crashes with "could not translate
    # host name" and leaves the sibling silently dead.
    for i in $(seq 1 60); do
        if python3 -c "import socket; s=socket.socket(); s.settimeout(2); s.connect(('${db_host}', ${db_port}))" 2>/dev/null; then
            return 0
        fi
        echo "[entrypoint] waiting for ${db_host}:${db_port}... (${i}/60)"
        sleep 1
    done
    return 1
}

run_extra() {
    if [ -x scripts/bootstrap-extra.sh ]; then
        echo "[entrypoint] running fork bootstrap-extra.sh"
        ./scripts/bootstrap-extra.sh
    fi
}

case "${ENTRYPOINT_BOOTSTRAP:-full}" in
    none)
        echo "[entrypoint] ENTRYPOINT_BOOTSTRAP=none — waiting for db, then exec"
        wait_for_db
        ;;
    skip)
        echo "[entrypoint] ENTRYPOINT_BOOTSTRAP=skip — collectstatic only"
        python3 manage.py collectstatic --noinput
        run_extra
        ;;
    *)
        wait_for_db
        python3 manage.py migrate --noinput
        python3 manage.py collectstatic --noinput
        run_extra
        ;;
esac

exec "$@"
