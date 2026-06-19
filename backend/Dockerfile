FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# system deps: postgresql-client for pg_isready, curl for health checks
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    postgresql-client \
    curl \
    && rm -rf /var/lib/apt/lists/*

# dependency layer (CACHE CRITICAL)
COPY requirements/base.txt /app/requirements.txt
RUN pip install --upgrade pip && pip install -r requirements.txt

# application layer (changes frequently)
COPY . .

# runtime dirs
RUN mkdir -p /app/logs /app/staticfiles \
    && chmod +x /app/entrypoint.sh

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "2", \
     "--timeout", "120", \
     "--access-logfile", "-"]