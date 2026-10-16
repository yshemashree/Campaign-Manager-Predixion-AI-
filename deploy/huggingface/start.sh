#!/bin/sh
# Prepares a fresh database and secrets on every start (Space storage is not kept),
# then hands over to supervisord.
set -e
export PGDATA=/data/pg
PGBIN=$(ls -d /usr/lib/postgresql/*/bin | tail -1)

if [ ! -s "$PGDATA/PG_VERSION" ]; then
  "$PGBIN/initdb" -D "$PGDATA" -U campaign --auth=trust >/dev/null
fi
"$PGBIN/pg_ctl" -D "$PGDATA" -o "-k /tmp -c listen_addresses=127.0.0.1" -w start >/dev/null
psql -h 127.0.0.1 -U campaign -d postgres -tc "SELECT 1 FROM pg_database WHERE datname='campaign_manager'" | grep -q 1 \
  || createdb -h 127.0.0.1 -U campaign campaign_manager

secret() { python -c "import secrets; print(secrets.token_hex(32))"; }
export APP_ENV=production LOG_JSON=true
export DATABASE_URL=postgresql+asyncpg://campaign@127.0.0.1:5432/campaign_manager
export REDIS_URL=redis://127.0.0.1:6379/0
export SARVAM_BASE_URL=http://127.0.0.1:9000
export PUBLIC_BASE_URL=http://127.0.0.1:8000
export JWT_SECRET=${JWT_SECRET:-$(secret)}
export WEBHOOK_SIGNING_SECRET=${WEBHOOK_SIGNING_SECRET:-$(secret)}
export ENCRYPTION_KEY=${ENCRYPTION_KEY:-$(python -c "import base64,os; print(base64.b64encode(os.urandom(32)).decode())")}
export MOCK_SPEED=${MOCK_SPEED:-10}
export WEBHOOK_TIMEOUT_S=${WEBHOOK_TIMEOUT_S:-300}

cd /app/backend
alembic upgrade head
python -m app.seed
"$PGBIN/pg_ctl" -D "$PGDATA" -m fast -w stop >/dev/null

export PGBIN
exec supervisord -n -c /app/supervisord.conf
