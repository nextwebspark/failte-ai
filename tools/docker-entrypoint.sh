#!/bin/sh
# Apply this service's migrations (schema fallcha_tools only), then start.
set -e
if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
    alembic upgrade head
fi
exec "$@"
