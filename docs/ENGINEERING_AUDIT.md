# Engineering audit — 2026-10-03

## System understanding

This is a single Flask application for a physical three-round event. `app.py` wires Flask-Login, Flask-WTF CSRF, SQLAlchemy, Alembic and Socket.IO. Ten blueprints expose server-rendered admin, team and station pages plus JSON APIs. Plain JavaScript calls those APIs and uses Socket.IO for admin updates. PostgreSQL is required in production; SQLite is the development and isolated-test fallback. There is no queue, object store, vector database, LLM or ML inference path. QR generation is local; the other external dependencies are the database, browser camera and reverse proxy. No Dockerfile or CI configuration is present in this repository.

The main participant path is: login → session credential-version check → batch/round guard → QR scan → saved quiz answers → quiz submission and score → desktop password (maximum three attempts) → persistent final question assignment → saved final answers → submission → admin review → generated, locked and published results. Admin writes, participant writes and result publication use the singleton `Event` row update in `app.py` to serialize transactions. Database constraints supplement this guard. The root `../docs/` directory already documents endpoint behavior, deployment and event operations; `docs/BATCHES.md` documents the current rolling-batch work.

## Prioritized findings

| Priority | Issue | Location | Impact | Recommended fix |
| --- | --- | --- | --- | --- |
| P1 | Production Host header was unrestricted | `app.py:25` | An arbitrary Host could affect request URL handling and links | **Fixed:** trust the hostname from the required canonical public URL |
| P1 | Login limit was per supplied identity only | `routes/auth.py:85` | Changing identity bypassed a source-wide guessing limit and created unbounded rate-bucket keys | **Fixed:** add a shared 30-attempt/minute source limit alongside the existing 10-attempt identity limit |
| P1 | Anonymous QR landing GET writes scan and audit rows without a request cap | `routes/teams.py:64` | Repeated unauthenticated requests can grow audit tables and consume the shared write lock | Add a bounded anonymous scan policy after deciding which rejected scans organizers need to retain; enforce a proxy rate limit in production |
| P2 | Every mutating HTTP request takes the Event write lock | `app.py:156` | Safe for event-size concurrency, but unrelated login/admin writes serialize with participant answer saves; isolated SQLite simulation p95 rose from 192 ms at six teams to 766 ms at ten teams | Measure PostgreSQL lock waits under event load before splitting lock scopes; preserve race guarantees |
| P2 | Monitoring and assignment APIs query per row | `routes/qr.py:315`, `routes/operations.py:145`, `routes/operations.py:183` | Query count grows with teams, desktops and assignments | Batch queries or eager-load associations after profiling representative event data |
| P2 | Leaderboard lazily loads `session.round` | `utils/scoring.py:50` | Extra queries on recurring leaderboard polls | Eager-load round relationships when leaderboard latency becomes material |
| P2 | Test setup inherited local event mode | `tests/test_event_flow.py:50` and other test setup methods | A local production-mode `.env` made otherwise isolated tests fail | **Fixed:** set TEST/development explicitly in test app configs |
| P2 | No CSP is set in app responses | `app.py:175` | Reduced defense if an HTML insertion bug appears | Introduce a compatible CSP after inventorying inline scripts/styles in templates; verify proxy policy first |
| P3 | Migration harness uses a deprecated Flask-SQLAlchemy API | `migrations/env.py:21` | Warning today; future library upgrade may break migrations | Use `db.engine` after checking migration behavior across supported versions |
| P3 | Root and local documentation are split | `../README.md`, `README.md`, `docs/BATCHES.md` | Setup guidance is harder to find and can drift | Keep root guide canonical; link this audit and batch guide from it when root docs are updated |

No P0 issue was confirmed. This is a repository audit, not a penetration test or a production load test. Dependency vulnerability status was not established by `pip check`, which only tests installed dependency compatibility.

## API, database and frontend review

`flask routes` enumerated 74 endpoints including the static route. Admin, team and public routes generally use explicit role decorators or publication checks; station QR display is intentionally public. Global CSRF covers mutating methods. JSON errors are mostly `{ "error": ... }` with appropriate 4xx statuses, while HTML login forms return rendered pages and flashes. Changing to `/api/v1` or replacing these responses would break existing browser clients, so no route migration was made. The central request guard validates JSON object shape and positive `_id` values; individual routes apply domain validation. Health checks expose DB availability. Unexpected exceptions are logged by type and request ID with a generic 500 response.

The schema has unique keys for team identifiers, QR tokens, attempt answers, assignments and scores; check constraints cap desktop password attempts and batch capacity. Alembic migrations include a rolling-batch backfill. Result generation and grading use persistent snapshots so later question edits do not change submitted attempts. PostgreSQL transaction behavior and restoration from backup still need rehearsal in the deployment environment.

The frontend is server-rendered Jinja with plain JavaScript, local vendor scripts and CSS. User-visible answer content is escaped or assigned as text in the reviewed flows. Answer drafts use sessionStorage for recovery; server records determine submitted state. The admin dashboard's large `dashboard.js` and `operations.js` contain many dynamic HTML templates; a CSP and focused browser tests would lower regression risk. Mobile layout and camera behavior require browser/device validation, which was outside this terminal review.

## Changes made

1. Production host allowlisting: `app.py` derives Flask `TRUSTED_HOSTS` from `PUBLIC_BASE_URL`; `config.py` rejects a production URL without an HTTPS hostname. A focused test confirms canonical Host succeeds and a different Host receives 400. Production requests on alternate hostnames now fail by design.
2. Login source throttling: `routes/auth.py` retains the ten-attempt identity bucket and adds a thirty-attempt source bucket for each login type. A test changes identity every request and confirms the next attempt receives 429. The implementation uses the existing database-backed bucket table and transaction lock.
3. Test isolation: the test app factories explicitly set `APP_ENV=development` and `EVENT_MODE=TEST`, keeping the real local `.env` from changing their behavior.

## Validation and limits

`venv/bin/python -m unittest discover -s tests -q` passed without environment overrides (39 tests). `venv/bin/python scripts/simulate_event.py --teams 6 10` passed both isolated SQLite runs: six teams/174 requests/p95 192 ms and ten teams/290 requests/p95 766 ms. `venv/bin/python -m compileall -q ...`, `node --check` for all four application JavaScript files, `venv/bin/python -m pip check`, and `git diff --check` passed. No dedicated lint, formatter, type-check or frontend build configuration was found. The race suite uses SQLite unless `RACE_DATABASE_URL` is set; PostgreSQL race validation, the full 25/50/100-team simulation and production database migration check were not run here.

Existing uncommitted application and batch changes were present before this audit and were preserved. No schema, route, or response format was changed. The host restriction is the only intentional request behavior change; it applies only when `APP_ENV=production`.
