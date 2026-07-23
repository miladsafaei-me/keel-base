#!/usr/bin/env bash
#
# Post-ship local sync: after a session lands work on origin/main, fast-forward the
# LOCAL main tree and restart the local web container so the local preview reflects
# the latest main WITHOUT waiting for a prod deploy.
#
# Called by the agent right after `git push origin HEAD:main`. It is the only bridge
# between the per-session worktrees (NOT bind-mounted into any container) and the
# local podman stack (which serves ./backend from the main tree). It does NOT touch
# GitHub Actions — no image build, nothing ships to prod — so the accumulate-on-main
# / deploy-on-command model is unchanged.
#
# REPO derives from this script's own location. PROJECT_SLUG + NGINX_PORT come from
# the repo's .env (fallback: keel / 8080). Safety: acts ONLY on a clean `main`;
# fast-forward only; flock-serialized against parallel sessions.

set -u

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SLUG="$(basename "$REPO")"
LOCK="/tmp/${SLUG}-sync-local.lock"

# Pull PROJECT_SLUG + NGINX_PORT from .env without executing it.
PROJECT_SLUG="keel"
NGINX_PORT="8080"
if [ -f "$REPO/.env" ]; then
  v="$(grep -E '^PROJECT_SLUG=' "$REPO/.env" | tail -1 | cut -d= -f2-)"; [ -n "$v" ] && PROJECT_SLUG="$v"
  v="$(grep -E '^NGINX_PORT=' "$REPO/.env" | tail -1 | cut -d= -f2-)"; [ -n "$v" ] && NGINX_PORT="$v"
fi
WEB="${PROJECT_SLUG}-web"
NGINX="${PROJECT_SLUG}-nginx"

exec 9>"$LOCK"
if ! flock -w 90 9; then
  echo "[sync-local] another sync holds the lock; skipping."
  exit 0
fi

branch="$(git -C "$REPO" rev-parse --abbrev-ref HEAD 2>/dev/null)"
if [ "$branch" != "main" ]; then
  echo "[sync-local] local tree is on '$branch', not main — skipping to preserve WIP."
  exit 0
fi
if [ -n "$(git -C "$REPO" status --porcelain 2>/dev/null)" ]; then
  echo "[sync-local] local main tree has uncommitted changes — skipping to preserve WIP."
  exit 0
fi

before="$(git -C "$REPO" rev-parse HEAD 2>/dev/null)"
git -C "$REPO" fetch -q origin main || { echo "[sync-local] fetch failed; skipping."; exit 0; }
if ! git -C "$REPO" merge --ff-only origin/main >/dev/null 2>&1; then
  echo "[sync-local] local main is not fast-forwardable from origin/main — skipping."
  exit 0
fi
after="$(git -C "$REPO" rev-parse HEAD 2>/dev/null)"

if [ "$before" = "$after" ]; then
  echo "[sync-local] already up to date ($after)."
  exit 0
fi

echo "[sync-local] ${before:0:7} -> ${after:0:7}; restarting local web..."
# Restart the SAME web container (not `compose up --force-recreate`): code is
# bind-mounted, so restarting re-runs the entrypoint bootstrap (migrate +
# collectstatic) against the new files while keeping the container's podman IP, so
# nginx's cached upstream stays valid and no 502 window opens. `9>&-` closes the
# lock fd for the child so conmon does not inherit and hold the flock forever.
podman restart "$WEB" >/dev/null 2>&1 9>&-
podman start "$NGINX" >/dev/null 2>&1 9>&-

# web re-runs migrate + collectstatic on restart (~10-20s); poll for a healthy
# homepage instead of reporting the transient bootstrap-window error.
code=000
for _ in $(seq 1 20); do
  sleep 2
  code="$(curl -s -o /dev/null -w '%{http_code}' "http://localhost:${NGINX_PORT}/" 2>/dev/null)"
  [ "$code" = "200" ] && break
done
echo "[sync-local] localhost:${NGINX_PORT} now on ${after:0:7} (homepage HTTP $code)."
