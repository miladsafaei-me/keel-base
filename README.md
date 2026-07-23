# keel-base

The **fresh neutral skeleton** every Keel project forks from. It bundles two
things a new project always needs and never wants to re-derive:

1. **A settings-merge contract + collision-safe namespacing** — the proven pattern
   from `resonans-cms`, minted neutral. One call, `apply_base_defaults(globals())`,
   wires the Django core (apps, middleware, templates, static, i18n) with
   override-safe `setdefault`/extend semantics. The `keel_base` app uses an explicit
   `keel_base_core` label + `keel_base_core_*` db_tables so it never collides with a
   host's apps.
2. **The shared operations infra** — from SignalBots, generalized: rootless-podman
   `compose.yaml` / `compose.prod.yaml` (blue-green web tier), a canary-gated
   `deploy/prod-deploy.sh`, manual+batched GitHub Actions (`build-image` + opt-in
   `pr-checks`), a 3-mode `entrypoint.sh`, and the worktree-isolation +
   sync-local-to-main Claude hooks.

**Invariant:** the core imports **no** optional capability. keel-ui, keel-cms,
keel-content, keel-seo, and keel-web are added per fork (see `BOOTSTRAP.md`), each
referenced by version in `requirements.txt` — never vendored. That is what lets a
CMS-only fork and a signals-only fork share this same base without dragging in each
other's code.

## Layout

```
keel-base/
├── pyproject.toml / MANIFEST.in        the keel-base package (src/ layout, hatchling)
├── src/keel_base/                      the neutral core app
│   ├── conf.py                         apply_base_defaults(globals()) — the entry point
│   ├── apps.py / models.py / admin.py  SiteProfile (structured site facts, singleton)
│   ├── capabilities.py                 reads keel-capabilities.yml (installed-vs-enabled)
│   ├── views.py / urls.py              placeholder home + /healthz
│   └── templates/keel_base/            base.html (noindex) + home.html
├── backend/                            the forkable Django project
│   ├── config/                         thin settings host + urls/wsgi/asgi
│   ├── entrypoint.sh                   3 bootstrap modes (full / skip / none)
│   └── gunicorn.conf.py
├── compose.yaml / compose.prod.yaml    dev stack + blue-green prod stack
├── Dockerfile / requirements.txt       plain slim-python image (no capability deps)
├── deploy/
│   ├── prod-deploy.sh                  canary + blue-green cutover
│   ├── deploy.env.example              PROJECT_SLUG / IMAGE_REF / PROD_HOST blanks
│   ├── critical-paths.txt              pages the canary refuses to ship broken
│   └── nginx/site.conf.example         prod upstream sample
├── .github/workflows/                  build-image.yml + pr-checks.yml
├── .claude/                            worktree hooks + settings.json + data-dirs
├── keel-capabilities.yml               the capability registry (picker + panel source)
└── BOOTSTRAP.md                        one-time fork checklist (self-deletes)
```

## Quick start (local)

```bash
cp .env.example .env            # set a real SECRET_KEY + DB password
podman compose up -d --build
curl -s localhost:8080/healthz  # {"status": "ok"}
```

Then follow `BOOTSTRAP.md` to name the project and install capabilities.

## Relationship to other Keel repos

- **keel-kit** — the Claude plugin carrying the generic methodology (deploy, git,
  SEO, visualization rules). This repo's `CLAUDE.md` inherits from it.
- **keel-ui / keel-seo / keel-cms / keel-content / keel-web** — the optional
  capabilities a fork installs. keel-base is deliberately blind to all of them.
- **resonans-cms** — the ancestor whose `apply_cms_defaults` + namespacing pattern
  this skeleton was seeded from; it becomes a consumer generated from keel-base.
