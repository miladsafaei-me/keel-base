# CLAUDE.md

Guidance for Claude Code when working in **keel-base** — the neutral skeleton Keel
projects fork from. This repo is *the base itself*, not a project that uses it.
Treat it like a library + template: stable labels, no business logic from any
particular consumer, every project-specific value expressed as a Bucket-3 blank.

## Keel platform — inherited methodology

keel-base is part of the **Keel** platform. The generic, cross-project methodology
(deploy model, git + secrets, SEO core, copywriting, comment safety, front-end
architecture, visualization) is maintained canonically in the **`keel-kit`** plugin
(`~/www/keel-kit` · github.com/miladsafaei-me/keel-kit) — see its `PLATFORM.md` and
`methodology/` docs. When a *generic* rule needs to change, change it upstream in
keel-kit, not here. This file only records what is specific to the base skeleton.

## The core invariant — do not break

**The base core imports NO optional capability.** `apply_base_defaults` wires only
Django + the `keel_base` app. keel-ui / keel-cms / keel-content / keel-seo /
keel-web are added by a fork *after* the call (in `config/settings.py`), and pinned
in `requirements.txt` — **referenced by version, never vendored** (never copied into
this repo). This is what keeps a CMS-only fork and a signals-only fork able to share
one base. If you find yourself importing a `keel_ui`/`keel_cms`/etc. symbol anywhere
under `src/keel_base/`, stop — that belongs in the capability or the fork.

## Namespacing discipline (do not break)

The core app uses app label `keel_base_core` and every model sets an explicit
`db_table = "keel_base_core_<model>"`. This is how the package coexists safely with a
host's own apps and third-party apps. **Never rename a released label or db_table** —
host projects rely on them for FKs and migrations. Additive changes only.

## Bucket-3 blanks — the neutrality rule

A project-specific value never appears hard-coded in this repo; it is a *blank* the
fork fills. Current blanks: `PROJECT_SLUG` / compose `name:` / `COMPOSE_PROJECT_NAME`,
`IMAGE_REF`, `PROD_HOST`, host ports, `deploy/critical-paths.txt`, `deploy/nginx/`,
`SiteProfile` field values, `.claude/worktree-data-dirs`. When you add infra, drive
any project-specific value through `.env` / `deploy/deploy.env` / a `*.example` file —
do not bake it in.

## Language rule — non-negotiable

All code, templates, comments, identifiers, and docs are **English only**. Non-English
UI in a fork goes through Django i18n (`gettext`), never hard-coded strings.

## Layout & conventions

- **`src/keel_base/`** is the pip package (hatchling, `src/` layout) — mirrors the
  shape of keel-ui / keel-seo.
- **`backend/`** is the forkable Django project. `config/settings.py` is a thin host
  that calls `apply_base_defaults(globals())` then sets only host-specifics.
- **Migrations:** never write one without reading what it does. The base ships exactly
  one migration (`SiteProfile`); keep it minimal.
- **Comments:** multi-line comments use block/paired syntax; Django templates use
  `{% comment %}…{% endcomment %}`, never multi-line `{# … #}`. No banner-rail comments.
- **Podman/compose:** every service carries `restart: unless-stopped`; every host bind
  mount ends in `:z`. Never `docker` — `podman` everywhere.

## Deploy model (inherited from keel-kit `deploy-standard.md`)

Accumulate-on-main, deploy-on-command, batched. Pushing to `main` does **not** build
or deploy. A human ships a batch with `gh workflow run "Build & push web image"`,
which builds current `main` HEAD once and runs the canary-gated `prod-deploy.sh`.
The canary boots the new image outside the nginx upstream, smokes every
`deploy/critical-paths.txt` page against real prod data, and aborts before cutover on
any failure — so a broken release reaches zero users.

## Self-check before shipping

- `python3 -m py_compile` the whole `src/keel_base` + `backend` tree.
- `grep` for any residual hard-coded project value or capability import.
- No banner comments; English only.
