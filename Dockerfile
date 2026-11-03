FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv/app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini .
COPY scripts ./scripts

RUN useradd --create-home appuser && mkdir -p data backups && chown -R appuser data backups
USER appuser

# Migrations run automatically on startup. One worker: background AI jobs run in-process.
CMD ["uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000", "--proxy-headers", "--workers", "1"]
