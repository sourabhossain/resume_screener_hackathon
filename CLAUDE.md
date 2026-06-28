# Career — AI Resume Screening

## Project Overview
**Career** is a Django web app where recruiters post jobs and candidates apply via a
public careers page; an AI pipeline screens each resume, assigns a tier + hire
recommendation, verifies the candidate's links, and supports panel interview
scheduling with token-based evaluation forms. It is a **single-company internal
tool**: every authenticated recruiter sees and acts on all jobs/candidates (access is
intentionally NOT isolated per owner — see [apps/core/models.py:105](apps/core/models.py#L105)).

## Tech Stack
- **Backend:** Django 5, MySQL 8 (utf8mb4, STRICT mode), Python 3.11
- **Async:** Celery 5 + Redis (broker, result backend, shared cache)
- **AI:** LangGraph workflow + LangChain-OpenAI; model `OPENAI_MODEL` ([config/settings/base.py:296](config/settings/base.py#L296))
- **Docs/parsing:** pypdf, python-docx; link crawl via httpx + Playwright (Chromium)
- **API:** Django REST Framework + drf-spectacular (Swagger `/api/docs/`, ReDoc `/api/redoc/`)
- **Frontend:** Django templates + HTMX + Alpine.js + Tailwind (compiled CLI, no CDN)
- **Server:** Gunicorn (gthread) + WhiteNoise static
- **Tests:** pytest-django + factory-boy (SQLite in-memory, eager Celery)
- **Infra:** Docker Compose (`docker-compose.yml` dev, `docker-compose.prod.yml` prod)

## Key Directories
- `apps/core/` — jobs, resumes, AI pipeline, public careers, REST API, dashboard
  - `apps/core/views/` — view package split by concern (jobs/resumes/careers/screening/users/media/auth); `_helpers.py` holds shared queryset/guard helpers, `__init__.py` re-exports all names
  - `apps/core/services/` — **business logic lives here, not in views** (see patterns doc)
  - `apps/core/prompts/` — LLM prompts: `_base/` shared + `roles/*.fragment.txt` per job family
  - `apps/core/management/commands/` — `seed_demo`, `close_expired_jobs`, `fix_contact_info`
- `apps/interviews/` — interview scheduling + public token evaluation forms + rank report
- `config/` — `settings/{base,dev,prod,test}.py`, `celery.py`, `middleware.py`, `urls.py`, `cache_backends.py`
- `templates/` — `core/`, `careers/`, `interviews/`, `auth/`; `*/partials/` are HTMX fragments
- `static/src/input.css` → compiled to `static/css/app.css` (Tailwind CLI)
- Golden AI eval harness: `golden_eval.py`, `golden_cases.txt`, [apps/core/services/golden_checks.py](apps/core/services/golden_checks.py)

## Essential Commands
All commands run inside Docker (the project is Docker-only).

```bash
# Start the full stack (web, db, redis, celery workers, beat)
docker compose up -d --build

# Database + admin user
docker compose exec web python manage.py migrate
docker compose exec web python manage.py createsuperuser
docker compose exec web python manage.py seed_demo          # optional demo data

# Tests (SQLite in-memory; settings forced via pytest.ini --ds=config.settings.test)
docker compose exec web python -m pytest                    # full suite
docker compose exec web python -m pytest apps/core/tests/test_hardening.py   # one module

# Migrations / sanity
docker compose exec web python manage.py makemigrations
docker compose exec web python manage.py check
docker compose exec web python manage.py makemigrations --check --dry-run   # drift check

# AI golden evaluation (real LLM; needs OPENAI_API_KEY)
docker compose exec web python golden_eval.py

# Frontend CSS (only when editing templates / input.css)
npm run build:css        # one-off    | npm run watch:css   # during dev
```

- App: http://localhost:8000 · phpMyAdmin: http://localhost:5050
- Celery queues: `screening` (concurrency 8) and `verification` (concurrency 2, RAM-heavy Chromium) — see `docker-compose.yml`
- Prod requires `.env` with `SECRET_KEY`, `ALLOWED_HOSTS`, `REDIS_PASSWORD`, DB vars (prod settings fail fast if missing — [config/settings/prod.py:9](config/settings/prod.py#L9))

## How It Fits Together (high level)
- A resume upload (web or API) sets status `processing` and queues `screen_resume_task`
  ([apps/core/tasks.py](apps/core/tasks.py)).
- `ResumeService.process_resume` extracts text → runs the LangGraph pipeline
  (`detect → extract → match → score → rank`, [apps/core/services/ai_screener.py:383](apps/core/services/ai_screener.py#L383))
  → persists scores → queues link verification on commit
  ([apps/core/services/resume_service.py:188](apps/core/services/resume_service.py#L188)).
- Tier/recommendation are derived from `final_score` as the single source of truth
  ([apps/core/models.py](apps/core/models.py), `assign_tier_and_recommendation_from_final_score`).
- HTMX polls fragment views to live-update pipeline rows as screening completes.

## Conventions
- Code style is enforced by linters — do not add formatting rules here.
- Every recruiter resume lookup goes through `_get_active_resume` so deleted-job
  candidates stay hidden ([apps/core/views/_helpers.py](apps/core/views/_helpers.py)).
- Soft delete is the only delete; never hard-delete records. Cascades are declarative
  (`SOFT_DELETE_CASCADE`) — see patterns doc.
- New view functions: add to the right `apps/core/views/*.py` module **and** re-export in
  `apps/core/views/__init__.py` so `urls.py` (`views.<name>`) keeps resolving.
- Treat all resume/job text as untrusted (public submissions): keep the prompt-injection
  guard and score clamping; validate candidate-supplied URLs through `url_safety` before fetching.

## Additional Documentation
Check these when working on the relevant area:
- [.claude/docs/architectural_patterns.md](.claude/docs/architectural_patterns.md) — soft-delete cascade, service layer, LangGraph pipeline, LLM client, prompt composition, DRF/HTMX/Celery conventions, middleware, settings, security patterns. **Read before adding models, services, views, tasks, or API endpoints.**
- [SCORING.md](SCORING.md) — scoring formula, per-family weights, tier thresholds.
- [README.md](README.md) — first-time setup, env vars, CSS build details.
