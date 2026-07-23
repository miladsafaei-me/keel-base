# BOOTSTRAP — turn this skeleton into a real project

This is the fork checklist. It is written to be run by an LLM assistant (or a
human) once, right after cloning `keel-base` into a new repo. Work top to bottom;
each step is idempotent. **When every box is checked, delete this file** — it has
no role in a live project.

> Skeleton status: this is a *neutral base*. It boots, serves a placeholder home
> page at `/` and a `/healthz` probe, and ships the shared infra (podman compose,
> canary deploy, CI, worktree hooks). It imports **no** capability — you add the
> ones you need below.

## 1. Name the project

- [ ] Choose a slug (lowercase, no spaces), e.g. `acme`.
- [ ] Set it everywhere it appears as a Bucket-3 blank:
  - `compose.yaml` and `compose.prod.yaml`: `name: <slug>`
  - `.env` (from `.env.example`): `COMPOSE_PROJECT_NAME`, `PROJECT_SLUG`
  - `deploy/deploy.env` (from `deploy/deploy.env.example`): `PROJECT_SLUG`, `IMAGE_REF`, `PROD_HOST`
- [ ] Keep `PROJECT_SLUG` identical to the compose `name:` — the deploy references
  `<slug>_default` (network) and `<slug>_media` (volume).

## 2. Secrets & environment

- [ ] `cp .env.example .env`, set a real `DJANGO_SECRET_KEY` and DB password.
- [ ] Add GitHub Actions secrets for deploy: `DEPLOY_HOST`, `DEPLOY_USER`,
  `DEPLOY_SSH_KEY`, `DEPLOY_PATH` (`gh secret set ...`).

## 3. Identity (SiteProfile)

- [ ] Bring the stack up (`podman compose up -d`), then seed the singleton:
  `podman exec <slug>-web python manage.py shell -c "from keel_base.models import SiteProfile; p=SiteProfile.load(); p.brand_name='Acme'; p.primary_domain='acme.com'; p.save()"`

## 4. Choose capabilities

The catalog is `keel-capabilities.yml`. For each capability you want:

- [ ] Uncomment + pin its package in `requirements.txt` (referenced by version,
  never vendored).
- [ ] Add its app(s) to `INSTALLED_APPS` in `config/settings.py` **after**
  `apply_base_defaults(globals())`, and wire its URLs in `config/urls.py`.
- [ ] Satisfy its `contracts` (see the registry entry) — e.g. brand tokens for
  `ui`, a landing seed for `seo`.
- [ ] Record it in `SiteProfile.enabled_capabilities` (the admin panel flags any
  capability enabled-but-not-installed).
- [ ] Respect `requires`: install dependencies first (`cms` needs `ui`;
  `content_pipeline` needs `ui` + `cms`).

Capability packages that need extra runtime (e.g. `ui`/`content_pipeline` want
Playwright + fonts) tell you to switch the `Dockerfile` `FROM` to the Playwright
base and add a `backend/scripts/bootstrap-extra.sh` (the entrypoint runs it).

## 5. Deploy surface

- [ ] List your high-traffic public pages in `deploy/critical-paths.txt` (the
  canary smoke-tests each before cutover).
- [ ] If you front the app with system nginx, copy `deploy/nginx/site.conf.example`
  to `deploy/nginx/site.conf`, edit `server_name`, and point
  `deploy/deploy.env`'s `NGINX_CONF_SRC`/`NGINX_CONF_DST` at it.

## 6. First ship

- [ ] Commit, push to `main` (accumulate-on-main — this does NOT deploy).
- [ ] When ready: `gh workflow run "Build & push web image"`, watch it until
  build + canary + deploy are green.
- [ ] Verify prod: `curl -s https://<domain>/healthz` returns `{"status":"ok"}`.

## 7. Clean up

- [ ] Delete this `BOOTSTRAP.md`.
- [ ] Trim the placeholder home view/template if your `/` is a real page.
