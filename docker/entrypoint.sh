#!/bin/sh
set -e
python manage.py wait_for_db --timeout 60
if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
  # In production prefer a one-off migration task/Job before rolling out,
  # so N replicas don't race to migrate.
  python manage.py migrate --noinput
fi
exec "$@"
