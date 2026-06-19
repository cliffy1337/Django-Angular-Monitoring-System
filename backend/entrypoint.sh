#!/bin/sh
set -e

# Wait for PostgreSQL only when DB_HOST is configured (skips in SQLite dev mode)
if [ -n "${DB_HOST}" ]; then
    echo "[entrypoint] Waiting for PostgreSQL at ${DB_HOST}:${DB_PORT:-5432}..."
    until pg_isready -h "${DB_HOST}" -p "${DB_PORT:-5432}" -U "${DB_USER}"; do
        sleep 1
    done
    echo "[entrypoint] PostgreSQL is ready."
fi

# Run web-server setup only for gunicorn; workers skip this once backend is healthy
if [ "$1" = "gunicorn" ]; then
    echo "[entrypoint] Running database migrations..."
    python manage.py migrate --noinput

    echo "[entrypoint] Collecting static files..."
    python manage.py collectstatic --noinput
fi

echo "[entrypoint] Starting: $*"
exec "$@"
