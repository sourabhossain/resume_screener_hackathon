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

# ── Stage 2: Python application (web, screening, beat) ───────────────────
# No playwright browser install here: it is only used by the verification
# worker (see target below).
FROM python:3.11-slim AS app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Tesseract reads CVs that arrive as scanned images or as pictures (PyMuPDF's
# built-in OCR calls it). Retried, because the Debian mirrors time out now and
# then; the check fails the build if the English model did not arrive.
RUN apt-get -o Acquire::Retries=5 update \
    && apt-get -o Acquire::Retries=5 install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/* \
    && test -f /usr/share/tesseract-ocr/5/tessdata/eng.traineddata
ENV TESSDATA_PREFIX=/usr/share/tesseract-ocr/5/tessdata
# One thread per OCR run: the screening worker runs several tasks at once, and
# Tesseract's own threading on top of that slows every one of them down.
ENV OMP_THREAD_LIMIT=1

COPY requirements.txt /app/
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . /app/

# Overwrite any committed CSS with the freshly compiled stylesheet.
COPY --from=css /app/static/css/app.css /app/static/css/app.css

CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]

# ── Stage 3: Verification worker (Playwright/Chromium) ───────────────────
# Uses Microsoft's image so Chromium + OS libs ship preinstalled (no apt-get).
FROM mcr.microsoft.com/playwright/python:v1.60.0-noble AS verification

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt /app/
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . /app/

COPY --from=css /app/static/css/app.css /app/static/css/app.css

CMD ["celery", "-A", "config", "worker", "-Q", "verification", "--concurrency=2", "-n", "verification@%h", "-l", "info"]
