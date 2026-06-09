# ResumeAI

A Django app for uploading jobs and resumes and screening candidates with AI. Run it with Docker.

## Setup (step by step)

### Prerequisites

- **Docker** and **Docker Compose**
- An **OpenAI API key**

### Step 1 — Clone the repository

```bash
git clone git@github.com:sourabhossain/resume_screener.git
cd resume_screening_system
```

### Step 2 — Create your environment file

```bash
cp .env.example .env
```

### Step 3 — Edit `.env`

Set at least:

- `DB_PASSWORD`
- `SECRET_KEY`
- `OPENAI_API_KEY`

You can keep the other variables as in `.env.example` for Docker.

### Step 4 — Start the stack

```bash
docker-compose up -d --build
```

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

### Optional

- **Demo data:** `docker-compose exec web python manage.py seed_demo`
- **Link verification** (crawling sites like GitHub / LinkedIn): install Chromium in both containers:

  ```bash
  docker-compose exec web playwright install chromium
  docker-compose exec celery playwright install chromium
  ```
