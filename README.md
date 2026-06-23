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

- **Docker:** the image builds the stylesheet automatically (multi-stage build), so no extra step is needed.
- **Local (non-Docker) dev:** run the build once after cloning, and rebuild whenever you change templates or `input.css`:

  ```bash
  npm install
  npm run build:css      # one-off build
  npm run watch:css      # rebuild on change while developing
  ```
