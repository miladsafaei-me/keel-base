# TODO

This file is the single source of truth for pending, follow-up, and deferred work on this project. See CLAUDE.md for the tracking rule.

Guidelines:
- Add a task here as soon as it's identified — with priority, prerequisites/dependencies, and enough context to pick it up cold.
- Group by priority: P0 (urgent / blocking / production risk), P1 (next up), P2 (backlog / nice-to-have).
- Note real dependencies explicitly ("Blocked by: ...", "Requires: ...").
- Delete a task from this file the moment it's done. This file only ever holds what's left.

## P1 — Next up
- [ ] Add `CSRF_TRUSTED_ORIGINS` to the base settings. `backend/config/settings.py` sets `ALLOWED_HOSTS` from `DJANGO_ALLOWED_HOSTS` but never sets `CSRF_TRUSTED_ORIGINS`, and `.env.example` has no corresponding key. Any fork reached through the compose nginx proxy on a non-default port (every local fork, and prod) gets "Origin checking failed — … does not match any trusted origins" on the first admin/login POST. Documented as a keel-base-owned gap in `~/www/keel-kit/methodology/new-project-bootstrap-plan.md` (§3b, "high priority, blocks admin use on a fresh fork") — that doc's top banner claims the whole file is "implemented (2026-07-25)", but this specific item was never actually landed in this repo (verified: no `CSRF_TRUSTED_ORIGINS`/`TRUSTED_ORIGIN` anywhere in the tree). Fix: read a comma-separated `DJANGO_CSRF_TRUSTED_ORIGINS` env var in `settings.py` (same pattern as `DJANGO_ALLOWED_HOSTS`), set `CSRF_TRUSTED_ORIGINS` from it, add a documented line + example value to `.env.example`, and once fixed, correct/remove the stale item in the keel-kit plan doc.

## P2 — Backlog
- [ ] Once the CSRF fix above lands, double-check `keel-new.sh` (keel-kit) fills `DJANGO_CSRF_TRUSTED_ORIGINS` for the generated `.env` (local ports) and `deploy/deploy.env` (prod host) so a generated fork doesn't hit the same 403 on first boot.
