# Testing and validation evidence — 2026-10-01

## Automated checks completed

- 32 unittest cases pass: authentication/roles/session revocation, CSRF, assigned/invalid/
  inactive/unauthorized/duplicate QR scans and audit, pause/end guards, quiz drafts and
  hidden scores, immutable submission, server scoring, station exclusivity, password
  success/three failures/persistent counters, fixed final assignments, final review,
  locked/stale/published results, exports, reset guards, account socket revocation,
  canonical QR URLs and malformed input.
- Migration test upgrades a populated legacy database, preserves its records/imported
  scan events, downgrades the new revision in an isolated database and upgrades again.
- Three independent-connection races also pass on PostgreSQL: twelve competing scans
  yield one valid scan; twelve quiz submissions yield one submission/score; twelve
  password requests consume exactly three attempts and create one final assignment.
- Chromium smoke test passes with CSRF enabled: every admin tab, mobile login/scans,
  ten-question autosave/submission, desktop three-failure unlock and final submission.
  A failed quiz-save request is simulated; unsaved feedback appears and the draft survives
  refresh before resaving. No browser JavaScript exceptions. External requests are blocked;
  Socket.IO, chart and scanner libraries load locally.
- Python compileall, three application JavaScript syntax checks and git diff --check pass.
  No pre-existing lint/type configuration was present.
- Reviewed Alembic migration applies on SQLite and PostgreSQL. Schema drift check reports
  no new upgrade operations on the final migration schema.

## Event simulations

The script sends real Flask requests over independent threads, with a separate authenticated
client per team. It uses temporary databases/schemas, reviewed migrations and test-only
content. It exercises all rounds, answer saving, refresh persistence, success/three-failure
paths, duplicate submission rejection, hidden scores and result generation/lock/publication.
No live event data is read or modified. Exact measured results are in
[SIMULATION_POSTGRESQL.json](SIMULATION_POSTGRESQL.json) and
[SIMULATION_SQLITE.json](SIMULATION_SQLITE.json).

PostgreSQL: 10/25/50/100 teams all pass; the largest run makes 2,900 participant requests
with 20 simultaneous worker threads. The measured p95 is approximately 1.3 seconds.
This is a no-think-time application/database stress check, not an HTTP capacity guarantee
for a particular host, reverse proxy, campus network or browser fleet.

SQLite initially hit its five-second default writer-lock timeout at 50 teams. The development
connection timeout was increased to 30 seconds, and all four sizes then passed. SQLite
is supported for local development/testing; production validation requires PostgreSQL.

## Reproduce

```bash
cd swayambhu
python -m unittest discover -s tests -v
python scripts/simulate_event.py --teams 10 25 50 100 --output ../docs/SIMULATION_SQLITE.json
# Use a disposable PostgreSQL database; credentials should come from a private environment.
SIMULATION_DATABASE_URL="$QUEST_TEST_DATABASE_URL" python scripts/simulate_event.py --output ../docs/SIMULATION_POSTGRESQL.json
RACE_DATABASE_URL="$QUEST_TEST_DATABASE_URL" python -m unittest discover -s tests -p test_races.py -v
python -m compileall -q .
node --check static/js/team.js
node --check static/js/dashboard.js
node --check static/js/operations.js
flask --app app db check
```

The PostgreSQL scripts create and drop only generated `aiquest_sim_*`/`aiquest_race_*`
schemas. Use a TEST account with schema creation permission. Never point fixtures or
manual schema experiments at a production database. The default unittest fixture creates
in-memory SQLite tables; scripts use migrations as an additional gate.

Optional browser driver (not an application runtime dependency):

```bash
pip install playwright
playwright install chromium
python scripts/check_browser.py
# Or set CHROMIUM_EXECUTABLE to an existing Chromium executable.
```

It creates a temporary TEST database/server and writes screenshots under /tmp. Camera
hardware and OS station setup still require real-device testing.

### UI refinement validation — 2026-10-01

The Chromium check passed with the ivory/cobalt/orange styling and supplied festival
poster. Additional assertions cover password visibility, one visible operations group,
ten-question checkbox selection, initial dialog focus, Escape and focus restoration,
mobile navigation expansion, horizontal overflow at 390px, and quiz answer progress.
The full QR/quiz/password/final flow and offline draft recovery still pass with CSRF
enabled and no browser JavaScript exceptions. Screenshot artifacts are written to
`/tmp/aiquest-login-desktop.png`, `/tmp/aiquest-admin.png`, `/tmp/aiquest-phone.png`
and `/tmp/aiquest-desktop.png`.

The follow-up browser check also simulates an older cached admin template without
the connection-status ID. The stable stylesheet entry point loads both layout and
visual refinements, selected operation buttons have the expected cobalt background,
and the connection label updates without an exception. An empty question bank shows
instructions and a link to Questions, with quiz creation disabled.

## Security review and operational gates

Reviewed role guards, CSRF mutations, signed session revocation, secret/cookie production
validation, server-only scoring/state/answer keys, locked results, opaque tokens, archived
history, spreadsheet formula escaping, safe errors and logs. Browser storage is used only
for unsaved answer recovery, never for attempt limits or scoring. Administrative account
updates disconnect affected admin sockets.

Before event readiness sign-off, organizers must still configure real content/credentials,
rehearse actual phones/desktops/Wi-Fi/HTTPS, test every printed QR, verify a restored
PostgreSQL backup and validate hosting/system supervision. The application password
challenge does not unlock an operating-system account. Single-worker Socket.IO deployment
is intentional. Application write serialization trades peak throughput for correctness;
measure on the actual event host if response times exceed the event team's tolerance.
