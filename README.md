# Career

Upload jobs and resumes, and screen candidates with AI. Runs with Docker.

## Requirements

- Docker & Docker Compose
- An OpenAI API key

## Setup

```bash
# 1. Clone
git clone git@github.com:sourabhossain/resume_screener_hackathon.git
cd resume_screener_hackathon

# 2. Create your .env (then set OPENAI_API_KEY in it)
cp .env.example .env

# 3. Start everything
docker-compose up -d --build

# 4. Set up the database and an admin login
docker-compose exec web python manage.py migrate
docker-compose exec web python manage.py createsuperuser

# 5. (Optional) Load demo jobs and resumes
docker-compose exec web python manage.py seed_demo
```

## Use

- App: http://localhost:8000 — log in with the admin user you created
- Database UI (phpMyAdmin): http://localhost:5050 — log in with `DB_USER` / `DB_PASSWORD` from `.env`

## Frontend / CSS

Styling is built with the Tailwind CLI (no in-browser CDN). The source is
`static/src/input.css` + `tailwind.config.js`; the compiled, purged output is
`static/css/app.css`, which `base.html` loads via `{% static %}`.

- **Docker (production image):** the image builds the stylesheet automatically (multi-stage build).
- **Docker (local dev):** the image build is *not* enough. `docker-compose.yml` mounts
  the project over `/app`, so the host's `static/css/app.css` hides the one compiled
  into the image. After changing any template or `input.css`, rebuild and re-collect:

  ```bash
  docker run --rm -v "$PWD:/app" -w /app node:20-slim \
    npx tailwindcss -i ./static/src/input.css -o ./static/css/app.css --minify
  docker compose exec web python manage.py collectstatic --noinput
  ```

  Skip this and new Tailwind classes silently do nothing — no error, just unstyled markup.
- **Local (non-Docker) dev:**

  ```bash
  npm install
  npm run build:css      # one-off build
  npm run watch:css      # rebuild on change while developing
  ```

## Employee Information Form

Shortlisting a candidate emails them a link plus a one-time code; they fill in a
130-question form (Sections A–D7 of
`SSL_Wireless_Employee_Information_Form_FINAL_UPDATED.pdf`) and the recruiter
reads it back under **Information Form** on the candidate page.

The whole form is defined as data in `apps/employee_form/schema.py` — add or
change a question there and nothing else needs touching.

### Going live

`manage.py check` refuses to start on a misconfiguration, so run it as part of the
deploy. The settings it guards:

| Variable | Must be |
|---|---|
| `SITE_BASE_URL` | The public HTTPS address candidates can reach. Emailed links are built from this, **not** from the request — left at `localhost`, every invitation is a dead link. |
| `EMAIL_BACKEND` | `django.core.mail.backends.smtp.EmailBackend`. Anything else prints emails instead of sending them. |
| `EMAIL_HOST` | `smtp.office365.com` for this tenant. `smtp.sslwireless.com` and `mail.sslwireless.com` both resolve to `127.0.0.1` and are unreachable. |
| `DEFAULT_FROM_EMAIL` | The same mailbox as `EMAIL_HOST_USER`. Microsoft 365 rejects a mismatch with `554 5.2.252 SendAsDenied`. |

Also required:

- **Celery must be running.** Invitations are sent by
  `apps.employee_form.tasks.send_employee_form_invite` on the `screening` queue.
  Without a worker, forms are created but no email goes out.
- **The email settings must reach the _worker_, not just `web`.** The worker is the
  process that talks to SMTP. After editing `.env`, recreate every service —
  `restart` does not re-read the env file:

  ```bash
  docker compose up -d --force-recreate web celery-screening celery-verification celery-beat
  ```

  Get this wrong and the symptom is confusing: the site looks correctly
  configured, the form says **Invite sent**, and the email is quietly printed to
  the worker's log instead. Verify with:

  ```bash
  docker compose exec celery-screening python -c \
    "import django;django.setup();from django.conf import settings;print(settings.EMAIL_BACKEND, settings.EMAIL_HOST)"
  ```

  A non-SMTP backend also logs `employee_form.invite_not_delivered` on every send.

A failed send is recorded on the form and shown to the recruiter as
**Invite failed** with the reason, next to a Resend button — it never fails silently.

### Two deliberate differences from the PDF

- **Q1 Requisition ID is dropped** (a candidate cannot know it), so this form has
  130 questions and our Q1 is the PDF's Q2.
- **No employer block is hard-required.** The PDF marks Employers 1–4 required,
  which would make the form unsubmittable for a fresher. Instead an employer is
  optional until its name is filled in, at which point the rest of that block
  becomes required.

### Still to confirm

`DEPARTMENT_ROUTING` in `schema.py` maps all 25 departments to Sections D1–D6.
Only `Banking and Financial Services → D1` is confirmed; the other 24 are inferred
from the section titles and should be checked against the form's Branching Setup
Guide. A wrong entry asks a candidate the wrong department's questions.
