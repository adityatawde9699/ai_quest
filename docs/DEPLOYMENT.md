# Deployment and backups

Use PostgreSQL, a stable host on the campus network, HTTPS and one Gunicorn worker with
threads. Python 3.11+ is suitable; automated validation used Python 3.14. All state is in
PostgreSQL; restarting the web server preserves attempts and assignments.

## Configuration

Create an ignored `.env` in `swayambhu/`. Never commit it. Generate a private random
SECRET_KEY (`python -c "import secrets; print(secrets.token_urlsafe(48))"`) and use a
restricted PostgreSQL application account. Set:

```dotenv
APP_ENV=production
EVENT_MODE=PRODUCTION
COOKIE_SECURE=true
AUTO_INIT_DB=false
PUBLIC_BASE_URL=https://quest.your-college.example
TRUSTED_PROXY_COUNT=1
SECRET_KEY=<private-random-value-at-least-32-characters>
DATABASE_URL=postgresql://<user>:<password>@<host>:5432/<production-database>
```

Use a separate role/database/SECRET_KEY for rehearsals with EVENT_MODE=TEST. Production
startup rejects missing/short secrets, insecure cookies and non-PostgreSQL databases.
URL-encode special characters in database passwords. Keep .env readable only by the
service account. Do not run with debug enabled.

## Install and migrate

```bash
cd swayambhu
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
# Back up before changing an existing database.
flask --app app db upgrade
flask --app app init-db
flask --app app create-admin --role super-admin
flask --app app db check
# One worker keeps the existing Socket.IO rooms in one process.
gunicorn --workers 1 --threads 20 --timeout 60 --bind 127.0.0.1:8000 app:app
```

Do not run create_all against production. For future model changes: `flask --app app db
migrate -m "description"`, inspect defaults/data migrations/foreign keys, rehearse against
a restored backup and then apply upgrade during a maintenance window. Existing legacy
quiz progress requires organizer review; the old timed attempts are retained as evidence.

### Legacy local database without migration history

An older database created with `create_all` may contain tables but no `alembic_version`.
An old login cookie can then trigger a 500 on `/admin/login` because newer model columns
(for example `admin.active`) are absent. Clearing the cookie does not upgrade the schema.

Back up the database first and compare its tables, columns, indexes and constraints
against a temporary database migrated to the suspected legacy revision. Only after
confirming the schema matches that revision, stamp that specific revision and run
`db upgrade` followed by `init-db`. Never stamp `head` to bypass missing schema changes
and never delete the database to fix a login error.

## HTTPS reverse proxy

Example Nginx location under a TLS-enabled virtual host:

```nginx
location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_read_timeout 75s;
}
```

Set TRUSTED_PROXY_COUNT=1 only for the illustrated single trusted proxy, with direct
backend access restricted to that proxy. The default is zero (no forwarding-header trust).
Use the actual trusted hop count for another topology; never trust arbitrary client headers. Prefer `PUBLIC_BASE_URL` for QR generation so printed
QRs always target the canonical HTTPS domain. Ensure phones and desktops resolve that
same domain. Restrict direct access to the application port. Camera scanning needs HTTPS.
No database credentials or tracebacks appear in participant error responses.

## PostgreSQL backups

Use `PGSERVICE`/`.pgpass` or an interactive password prompt; avoid putting secrets in
shell history. Replace `quest-production` with a local pg_service.conf service entry.

```bash
pg_dump --dbname='service=quest-production' --format=custom --file=before-event.dump
pg_restore --list before-event.dump > before-event.contents.txt
# AFTER event:
pg_dump --dbname='service=quest-production' --format=custom --file=after-event.dump
```

Restore into a **new empty verification database**, never over the production database by
default. Verify record counts and rehearse a login on an isolated host before declaring a
backup usable. Restoring production requires organizer authorization and downtime.

```bash
createdb --maintenance-db='service=quest-maintenance' quest_restore_verification
pg_restore --dbname='service=quest-restore-verification' --no-owner before-event.dump
```

Store encrypted/off-host copies, record times and checksums, restrict participant CSVs,
and agree retention with the organizers. Do not use DROP DATABASE, --clean or test reset
as routine deployment/backup steps.
