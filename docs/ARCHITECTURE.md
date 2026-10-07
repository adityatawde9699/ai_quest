# Architecture

The existing Flask factory, SQLAlchemy ORM, Alembic migrations, Flask-Login,
Flask-WTF, Socket.IO threading mode, Jinja templates and plain JavaScript are retained.
No external queue, Redis, SPA or microservice was added.

## Layers

- `app.py`: factory, extension wiring, CLI, authenticated socket rooms, request guards,
  safe errors and response security headers.
- `models/__init__.py`: existing normalized tables plus event configuration, quiz
  snapshots, append-only scan/password records and final assignments.
- `services/event.py`: round guards, progress transitions, score writes, snapshots,
  password enforcement and automatic grading.
- `routes/quest.py`: participant scans, saved answers, submissions and desktop access.
- Existing admin/team/QR/round/score/result blueprints: preserved and hardened.
- `routes/operations.py`: quiz and station configuration, judging, exports, roles and reset.
- Templates/static JS: mobile participant interface, desktop station interface and
  existing admin console extended with Event Operations.

## Transaction model

Every mutating HTTP request acquires an UPDATE lock on the singleton Event row before
loading participant state. The lock remains until commit or request teardown rollback.
This deliberately serializes event writes, including admin score/result operations.
For 100 physical teams this is simpler than several partially coordinated locks and
prevents quiz double submissions, fourth password attempts, conflicting desktop claims
and score changes racing result finalization. SQL uniqueness/check constraints provide
additional protection. Read requests run concurrently. SQLite uses its writer lock with
30-second development timeout; production requires PostgreSQL.

Keep mutation paths free of intermediate commits except the explicit login throttle and
rejected-scan transaction. New business logic must use the same guard. Do not write the
production DB from ad-hoc scripts during the event. External administrative SQL is outside
application locking guarantees.

## Real-time and resilience

Admin sockets must authenticate and join the `admins` room. Score broadcasts go only to
this room; participant APIs apply publication checks. Admins rejoin on socket reconnect;
15-second polling remains as fallback. Participant dashboards poll every 20 seconds.
Forms persist answers server-side. Pending edits use sessionStorage only as an unsaved
network-recovery draft; saved state, grading, attempt caps and progress use the database.
Submission confirmations are displayed only after a successful server response.

Deploy one Gunicorn worker with threads for the existing in-process Socket.IO rooms.
Multiple workers need coordinated socket messaging; this project deliberately avoids
adding that infrastructure until demonstrated necessary. Database transaction locks still
protect writes across processes.

## Interface styling

The original Jinja pages and JavaScript are retained. `static/css/dashboard.css`
is the stable entry point importing `base.css` for layout and `ui.css` for the Swayambhu visual refinements
and responsive rules. Development enables template auto-reload; production requires
a server restart when templates change. `static/js/ux.js` shares credential visibility and mobile
navigation behavior. The organizer-supplied poster is served locally from
`static/images/swayambhu-2026-poster.png`. Typography uses system fonts, with no
external font request. Participant instructions derive from server state and do not
grant round access. Answer progress counts are display-only; submission and scoring
remain server-controlled.
