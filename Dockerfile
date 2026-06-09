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

CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]