#!/usr/bin/env bash
# Build one target's image on the production host and deploy it there.
#
#   bash ~/.cache/<project>-ship/server-ship.sh <target>
#
# Copied to the host and started by keel-base tools/deploy/ship.sh inside a
# transient systemd --user unit, with the checkout already reset to the commit
# being shipped and the per-project host ship lock held. It reads the project's
# deploy/ship.conf from that checkout, so the config always matches the commit.
#
# Images are built here, on the production host, instead of on a CI runner: the
# deploy then depends on neither a CI service nor a container registry, and a
# warm layer cache makes a routine build seconds rather than minutes. The build
# runs at the lowest CPU and IO priority so the live sites keep precedence.

set -euo pipefail

target="${1:?usage: server-ship.sh <target>}"
cd "$(git rev-parse --show-toplevel 2>/dev/null || echo .)"

conf="deploy/ship.conf"
[ -f "$conf" ] || { echo "[ship] ERROR: $PWD/$conf is missing" >&2; exit 2; }
PROJECT=""; TARGETS=""
# shellcheck disable=SC1090
. "$conf"

spec() { local v="TARGET_${target}_$1"; printf '%s' "${!v-}"; }
image="$(spec IMAGE)"; context="$(spec CONTEXT)"; file="$(spec FILE)"; script="$(spec DEPLOY)"
[ -n "$image" ] && [ -n "$script" ] || { echo "[ship] ERROR: target '$target' is not described in $conf" >&2; exit 2; }
context="${context:-.}"
file="${file:-Dockerfile}"

sha="$(git rev-parse HEAD)"
short="$(git rev-parse --short HEAD)"

# Build from a clean checkout of HEAD, never from the live working tree: that
# tree holds .env, secrets, media and other untracked files a COPY must not see.
build_dir="$HOME/.cache/$PROJECT-build"
if [ ! -e "$build_dir/.git" ]; then
    git worktree prune
    rm -rf "$build_dir"
    git worktree add --detach -q "$build_dir" "$sha"
fi
git -C "$build_dir" checkout --detach --force -q "$sha"
git -C "$build_dir" clean -ffdxq

echo "[ship] building $image:$short on $(hostname -s)..."
started=$SECONDS
nice -n 19 ionice -c 3 \
    podman build --layers \
        --file "$build_dir/$file" \
        --tag "$image:latest" \
        --tag "$image:$short" \
        --label "org.opencontainers.image.revision=$sha" \
        "$build_dir/$context"
echo "[ship] build done in $((SECONDS - started))s"

bash "$script"

# Keep the five newest commit-tagged images for rollback, then drop dangling
# layers. A tag still used by a container is refused by podman and simply kept.
podman images "$image" --sort created --format '{{.Tag}}' \
    | grep -vx -e latest -e '<none>' | tail -n +6 \
    | while read -r tag; do podman rmi "$image:$tag" >/dev/null 2>&1 || true; done
podman image prune -f >/dev/null 2>&1 || true
