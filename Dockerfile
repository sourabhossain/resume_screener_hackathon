# ── Stage 1: build the Tailwind stylesheet ───────────────────────────────
# Compiles static/src/input.css → static/css/app.css, purged against the
# templates. Keeps the Tailwind toolchain out of the Python runtime image.
FROM node:20-slim AS css
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci || npm install
COPY tailwind.config.js ./
COPY static/src ./static/src
COPY templates ./templates
RUN npx tailwindcss -i ./static/src/input.css -o ./static/css/app.css --minify

# ── Stage 2: Python application ──────────────────────────────────────────
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# curl: healthchecks in docker-compose; Chromium deps come from playwright --with-deps
# (MySQL access uses pure-Python PyMySQL, so no native client/build deps are needed)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/
RUN pip install --upgrade pip && pip install -r requirements.txt \
    && python -m playwright install chromium --with-deps

COPY . /app/

# Overwrite any committed CSS with the freshly compiled stylesheet.
COPY --from=css /app/static/css/app.css /app/static/css/app.css

CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
