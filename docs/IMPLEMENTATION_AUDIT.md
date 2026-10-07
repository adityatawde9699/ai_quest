# Implementation audit — 2026-10-01

## Scope and architecture

Inspected both READMEs, every Python module, all four templates, both JavaScript files,
the stylesheet, requirements, environment example, ignore rules, three migrations,
and the existing unittest suite. No project AGENTS.md exists. The checkout was clean.

The existing Flask application factory registers seven blueprints. SQLAlchemy models
live in `swayambhu/models/__init__.py`; Flask-Login distinguishes admin/team identities.
Flask-WTF protects forms and JSON mutations. Socket.IO uses threading and authenticated
rooms. PostgreSQL/psycopg is configured through DATABASE_URL. Bootstrap currently uses
create_all; Alembic has three revisions. The admin dashboard uses plain JavaScript and
Jinja, which are suitable for this event. Keep this stack and existing tables.

## Requirement mapping at audit time

| Area | Existing | Missing or unsafe |
|---|---|---|
| Authentication | Hashed admin passwords/PINs, role guards, CSRF | Login throttling, team login/logout audit, session revocation |
| Teams | CRUD, PIN reset, normalized members, search/timeline | Allows zero members; physical deletion destroys history; ID allocation race |
| Round control | Global start/pause/end, per-team sessions | Pause means READY; ending round completes unfinished teams; participant complete endpoint bypasses all challenges |
| Round 1 | Random opaque token, PNG, single successful scan, clue/answer | Requires digital riddle answers contrary to physical hunt; no envelope QR assignment; no rejected scan history/IP/UA |
| QR administration | Generate, activate/deactivate, download, scan list | Edit, rotate token, archive, bulk download, print sheet, title/clue/destination |
| Round 2 | Question bank, timed sequential answers, ORM scoring | No quiz entity, fixed ten-question attempt, draft saving/final submission; API/HTML/dashboard/Socket.IO leak correctness and scores |
| Round 3 | Manual pen-and-paper score entry | Desktops, persistent sessions, password hashing/three-attempt cap, final bank/random fixed assignment/answers all absent |
| Scores/results | Ledger, ranking/ties, generation/lock, super-admin unlock | Publication gate, configurable bonus/penalty, unlock reason, global serialization of score/result mutations |
| Audit/live | Admin activity table and sockets | Rejected actions, participant actions, complete scan history, structured operational logging, reconnect handling |
| Operations | PostgreSQL env validation, health endpoint, CLI bootstrap | Exports, test-only reset, complete runbook/backup docs, readiness validation |
| Tests | Eight isolated SQLite unit tests | Required participant flows, CSRF/leak/race checks, migrations and 10/25/50/100-team simulations |

## Critical findings

1. `/api/team/rounds/<id>/complete` grants progression with no proof of completion.
2. `/api/leaderboard`, team dashboard payloads, quiz submit responses and participant
   Socket.IO rooms expose hidden scores/correctness. Publication must gate every path.
3. Global end marks all active team sessions completed, granting unearned progression.
4. Quiz submission and score accumulation lack serialization; simultaneous requests
   can score twice. Desktops/password caps need transactional guards from inception.
5. ScanLog's unique successful-scan constraint cannot represent repeated/rejected
   scans. Add a separate append-only scan event table and preserve old scan records.
6. Automatic create_all can silently create schema outside reviewed migrations.
7. Team deletion cascades remove judging evidence; archive instead.
8. No dependencies are installed in the current shell; baseline tests need an isolated
   virtual environment. No PostgreSQL service/credentials were supplied for validation.

## Implementation sequence

1. Preserve existing entities; add event configuration, team state/QR assignment,
   complete scan events, quiz attempts/drafts, desktops/password attempts, final
   assignments/answers, score adjustments and audit metadata. Review a migration.
2. Centralize transactions/state checks; close legacy bypass/leak endpoints. Distinguish
   global round states from team progress. Record rejected scans and immutable attempts.
3. Implement participant APIs and UI with confirmed draft saving and persistent resume.
4. Extend existing admin UI for content, assignments, stations, exports and publication.
5. Add critical-flow/security tests and migration checks; simulate 10/25/50/100 teams.
6. Document assumptions, deployment, schema, APIs, testing, and event-day operations.

## Acceptance limits

SQLite tests establish functional behavior only. PostgreSQL locking and concurrent load
must be tested against an isolated PostgreSQL database before claiming event readiness.
Do not migrate or reset a live database during development. Track actual validation in
TESTING.md and remaining operational gates in EVENT_DAY_RUNBOOK.md.

## Implemented outcome

The Flask application and original database entities were extended in place. The new
reviewed revision adds persistent challenge records; services enforce progress and
authenticated ownership; legacy completion/paper scoring bypasses are closed. Admin tools
now configure quizzes, stations, final judging, audited adjustments, archives, exports,
roles, result publication and test-only resets. Participant pages resume saved work and
show confirmed submissions without disclosing keys/correctness/hidden scores. Socket
reconnect/polling and locally served browser libraries reduce event-network dependencies.

Validation: 32 unit/security/migration/race cases, PostgreSQL race checks, full Chromium
flow with CSRF/offline draft recovery, and 10/25/50/100-team simulations on both database
backends passed. See TESTING.md and machine-readable simulation evidence for limits.
Real content, physical devices, HTTPS hosting and verified backups remain organizer
readiness gates; this development session does not deploy or migrate production.

## Local login repair — 2026-10-01

The existing local `instance/swayambhu.db` had legacy tables but no Alembic history.
An existing admin cookie reproduced `OperationalError: no such column: admin.active`.
Its tables, column definitions and indexes matched a temporary database migrated to
`c49d61f0d62a`. A SQLite backup was saved before stamping that verified baseline,
applying `66d5f8c67ffe`, and seeding event/round configuration. Existing record counts,
including the administrator, were preserved. Admin login with the old cookie and team
login both returned HTTP 200 with HTML forms after migration. No production database
was changed.

The final schema check also identified two `scan_log` foreign key delete actions from
the old `create_all` schema. An explicit Alembic batch alteration aligned these with
the reviewed migration schema, preserving rows. `flask db check` then reported no
new upgrade operations.
