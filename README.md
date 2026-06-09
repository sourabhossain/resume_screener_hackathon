# ResumeAI

A Django app for uploading jobs and resumes and screening candidates with AI. Run it with Docker.

## Tech stack

- **Backend:** Django 5
- **Database:** MySQL 8 (accessed with the pure-Python **PyMySQL** driver — no native client to compile)
- **Async tasks:** Celery + Redis
- **AI:** LangGraph / LangChain + OpenAI
- **DB admin UI:** phpMyAdmin

## Services

| Service     | URL / Port              | Notes                          |
| ----------- | ----------------------- | ------------------------------ |
| web (Django)| http://localhost:8000   | The app                        |
| phpMyAdmin  | http://localhost:5050   | Browse / manage the database   |
| db (MySQL)  | localhost:3307 → 3306   | MySQL 8                        |
| redis       | localhost:6380 → 6379   | Celery broker / result backend |
| celery      | —                       | Background worker              |

## Setup (step by step)

### Prerequisites

- **Docker** and **Docker Compose**
- An **OpenAI API key**

### Step 1 — Clone the repository

```bash
git@github.com:sourabhossain/resume_screener_hackathon.git
cd resume_screener_hackathon
```

### Step 2 — Create your environment file

```bash
cp .env.example .env
```

### Step 3 — Edit `.env`

Set at least:

- `DB_PASSWORD` — password for the app's MySQL user
- `DB_ROOT_PASSWORD` — MySQL root password
- `SECRET_KEY`
- `OPENAI_API_KEY`

You can keep the other variables as in `.env.example` for Docker.

### Step 4 — Start the stack

```bash
docker-compose up -d --build
```

This starts MySQL, Redis, the web app, the Celery worker, and phpMyAdmin.

### Step 5 — Apply database migrations

```bash
docker-compose exec web python manage.py migrate
```

### Step 6 — Create an admin user

```bash
docker-compose exec web python manage.py createsuperuser
```

Follow the prompts (username, email, password).

### Step 7 — Collect static files

```bash
docker-compose exec web python manage.py collectstatic --noinput
```

### Step 8 — Open the app

Go to **http://localhost:8000** in your browser and log in with the superuser you created.

---

## Database UI (phpMyAdmin)

Open **http://localhost:5050**. It is pre-pointed at the `db` host, so just log in with your MySQL credentials from `.env`:

- App user: `DB_USER` / `DB_PASSWORD`
- Or root: `root` / `DB_ROOT_PASSWORD`

---

### Optional

- **Demo data:** `docker-compose exec web python manage.py seed_demo`
- **Link verification** (crawling sites like GitHub / LinkedIn): install Chromium in both containers:

  ```bash
  docker-compose exec web playwright install chromium
  docker-compose exec celery playwright install chromium
  ```
