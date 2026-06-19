# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Vigil** is a full-stack uptime monitoring system. Users register, add HTTP endpoints, and the system automatically checks them every 5 minutes via Celery Beat, triggers email alerts on outages, and displays results in an Angular dashboard.

## Development Commands

### Backend (from `backend/`)

```bash
source venv/bin/activate
pip install -r requirements/dev.txt
python manage.py migrate
python manage.py runserver                        # Django dev server on :8000

# Run in separate terminals:
celery -A config worker -l info                   # task worker
celery -A config beat -l info                     # beat scheduler (5-min checks)

# Tests
python manage.py test apps.monitors               # all monitor tests
python manage.py test apps.monitors.tests.test_tasks.TasksTest.test_check_endpoint_up  # single test

# Lint
flake8 .
black .
isort .
```

### Frontend (from `frontend/`)

```bash
npm install
ng serve                  # dev server on :4200 (proxies /api → :8000)
ng build                  # production build
ng test                   # vitest unit tests
```

### Docker (full stack)

```bash
docker-compose up --build
# Serves at http://localhost:80 — nginx handles Angular static + /api proxy to Django
```

## Architecture

### Backend

Django 6 + DRF with two apps:

- **`apps/accounts/`** — custom `User` model (`AUTH_USER_MODEL = 'accounts.User'`); registration endpoint returns an auth token on success.
- **`apps/monitors/`** — core domain. Models: `Endpoint → CheckResult`, `Endpoint → Incident`, `FailedEmail`. All PKs are UUIDs.

**Celery task flow** (`apps/monitors/tasks.py`):
1. Beat fires `schedule_checks` every 5 min → fans out `check_endpoint.delay(id)` per active endpoint.
2. `check_endpoint` performs the HTTP request, saves a `CheckResult`, and detects status changes. On DOWN/UP transitions it creates/closes an `Incident` and calls `send_alert_email.delay(...)`.
3. `send_alert_email` respects a per-user cooldown, sends via `send_mail`, and on failure writes a `FailedEmail` dead-letter record before retrying (max 2 retries, 300 s delay).

`check_endpoint` has an **idempotency guard**: it skips re-checking an endpoint that was checked less than `interval_minutes` ago.

**Settings split**: `config/settings/base.py` → `dev.py` / `prod.py`. Dev uses SQLite + `console` email backend + CORS open to `:4200`. The active settings module is selected via `DJANGO_SETTINGS_MODULE` (defaults to `config.settings.dev`). Celery reads `CELERY_*`-namespaced keys from Django settings.

**Authentication**: DRF `TokenAuthentication`. The token is obtained at `POST /api/auth/token/` and must be in the `Authorization: Token <token>` header for all API calls.

**API docs**: Swagger UI at `/api/docs/` (drf-spectacular), schema at `/api/schema/`.

### Frontend

Angular 21 with standalone components and `inject()`-based DI (no constructor injection). No NgModules.

- **`core/services/auth.service.ts`** — stores the DRF token in `localStorage` under key `vigil_token`; exposes `isAuthenticated$` (`BehaviorSubject`).
- **`core/interceptors/auth.interceptor.ts`** — attaches `Authorization: Token <token>` to every outgoing request.
- **`core/guards/auth.guard.ts`** — redirects unauthenticated users to `/login`.
- **`features/dashboard/`** — lazy-loaded; displays endpoint list with status, response-time chart (Chart.js), and summary cards.

The dev proxy (`proxy.conf.json`) rewrites `/api/*` to `http://localhost:8000`, so no CORS handling is needed during development.

## Static Files

Static files come from Django admin, DRF's browsable API, and drf-spectacular's Swagger UI — no project-level `STATICFILES_DIRS` are needed.

`STATIC_ROOT` is `backend/staticfiles/` (gitignored, never committed).

| Environment | Storage backend | `collectstatic` output |
|---|---|---|
| dev (`config.settings.dev`) | `StaticFilesStorage` | plain copy, no manifest — safe to `runserver` without running collectstatic first |
| prod (`config.settings.prod`) | `whitenoise.storage.CompressedManifestStaticFilesStorage` | content-hashed filenames + `.gz` siblings + `staticfiles.json` manifest |

`WhiteNoiseMiddleware` must remain in position 2 in `MIDDLEWARE` (immediately after `SecurityMiddleware`). It serves files from `STATIC_ROOT` at runtime.

In Docker production the `backend/entrypoint.sh` runs `collectstatic --noinput` automatically before gunicorn starts. Running it manually:

```bash
# dev — plain copy
python manage.py collectstatic --noinput

# prod — hashed + gzipped (set required env vars first)
DJANGO_SETTINGS_MODULE=config.settings.prod python manage.py collectstatic --noinput
```

`CompressedManifestStaticFilesStorage` raises `ValueError: Missing staticfiles.json manifest file` if gunicorn starts before `collectstatic` has run. The entrypoint prevents this in Docker; locally you must run it manually when using prod settings with gunicorn.

## Key Conventions

- `Endpoint.is_active=False` suppresses both scheduling and idempotency checks — use this to pause monitoring without deletion.
- Status < 500 is treated as "up" in `check_endpoint` (4xx counts as up). Change the threshold in `tasks.py:32` if that behaviour needs to change.
- The Celery app is named `vigil` (`config/celery.py`) and discovered via `app.autodiscover_tasks()` — task modules must be named `tasks.py` inside each Django app.
- `TIME_ZONE = 'Africa/Lusaka'` in base settings; Celery is pinned to `UTC`. Keep this split in mind when comparing timestamps.
