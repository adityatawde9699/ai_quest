# 1,000-participant local load test — 8 October 2026

## Scope

This test used a **new temporary SQLite database** with 1,000 distinct authenticated
team sessions. No production or existing event database was used. The application ran
through Gunicorn with one `gthread` worker, 20 threads, a 60-second worker timeout,
and a 2,048-connection backlog on localhost. The client released 1,000 connections
at once for each large burst. CSRF was disabled for the isolated fixture; sessions
were preauthenticated so login rate limiting did not affect the measured requests.

| Workload | Successful / total | Wall time | Throughput | Median | p95 | p99 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Dashboard warmup, 100 requests | 100 / 100 | 0.29 s | 347.2 req/s | 166 ms | 281 ms | 285 ms |
| Dashboard burst, 1,000 requests | 1,000 / 1,000 | 2.58 s | 388.3 req/s | 1.31 s | 2.44 s | 2.54 s |
| Round 1 QR scan burst, 1,000 writes | 1,000 / 1,000 | 5.53 s | 181.0 req/s | 2.71 s | 5.10 s | 5.31 s |
| Participant page + dashboard + rounds + leaderboard, 1,000 flows / 4,000 requests | 1,000 / 1,000 flows | 6.76 s | 592 req/s | 6.20 s per flow | 6.68 s | 6.73 s |

After the scan burst, the isolated database contained 1,000 valid scan logs,
1,000 scan events, 1,000 completed Round 1 sessions, 1,000 scores, and 1,000 teams
in the `ROUND_1_COMPLETED` state. There were no HTTP errors or client timeouts in
these measured phases.

## Interpretation and limits

The app handled these 1,000 simultaneous authenticated HTTP clients in this local
test. This does **not** establish production capacity or a latency guarantee. The
test used SQLite instead of the required production PostgreSQL database, localhost
instead of a real network and TLS proxy, preauthenticated sessions instead of
1,000 simultaneous logins, and HTTP requests instead of full browsers. It did not
exercise camera hardware, static asset downloads, WebSocket connections, or the
complete quiz and final-challenge write flow.

Every mutating request updates the shared `Event` row in `app.py`, which serializes
writes at the database. This is a capacity risk under a real database and should be
measured on a staging copy of the intended PostgreSQL and HTTPS deployment before
claiming event-day readiness. Set an acceptable p95 latency target and rerun the
same 1,000-user scenario on that stack.
