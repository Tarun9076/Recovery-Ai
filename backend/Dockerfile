# Build context is the repo root (see docker-compose.yml) so this image can
# also carry scripts/ for `docker compose exec backend python scripts/seed_database.py`.
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/app ./backend/app
COPY scripts ./scripts

ENV PYTHONPATH=/app/backend

WORKDIR /app/backend

EXPOSE 8000

# Shell form (not exec-form CMD) so ${PORT} expands -- platforms like
# Railway assign a dynamic port via that env var; it defaults to 8000
# (unchanged) for plain `docker run`/docker-compose where PORT is unset.
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
