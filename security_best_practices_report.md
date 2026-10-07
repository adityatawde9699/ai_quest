# Security review — 2026-10-03

## Executive summary

The application already uses CSRF protection, hashed credentials, role checks, secure production cookie requirements, opaque QR tokens, generic 500 responses and database constraints. Two meaningful gaps were fixed in this audit. An anonymous scan logging path and absent application CSP remain for follow-up. No committed `.env`, credential, private key or database file was found in the tracked-file scan. A local ignored `.env` exists; its values are intentionally omitted here.

## High severity

### S1 — Production Host validation (fixed)

- Rule ID: FLASK-HOST-001. Location: `app.py:25-27`, `config.py:45-48`.
- Evidence: Production now sets `TRUSTED_HOSTS` from the HTTPS `PUBLIC_BASE_URL` hostname. Before this change, no host allowlist existed.
- Impact: An attacker-controlled Host could influence request URL handling or links if the app was directly reachable. The exact exploitability depends on reverse-proxy configuration.
- Fix: Canonical Host is accepted and other hosts receive 400 in a regression test.
- Mitigation: Keep the backend bound to the trusted reverse proxy and preserve its canonical Host header.
- False-positive notes: An upstream proxy may already reject unknown hosts; that configuration was not verified here.

### S2 — Login source limit bypass by varying identity (fixed)

- Rule ID: FLASK-AUTH-THROTTLE. Location: `routes/auth.py:85-107`.
- Evidence: The original bucket key included the supplied identity and source address, with a limit of ten per minute. A changed identity created a fresh bucket.
- Impact: An attacker could bypass the source-wide guessing cap and create many persistent bucket rows.
- Fix: A second bucket now caps each source at 30 attempts per minute per login type. The ten-attempt identity limit remains. A test exercises changed identities.
- Mitigation: Apply edge rate limits for distributed attempts, and monitor bucket-table growth.
- False-positive notes: NAT users share a source IP; the limit should be evaluated against event-day traffic.

## Medium severity

### S3 — Anonymous scan logging is unbounded (open)

- Rule ID: FLASK-AVAIL-ANON-WRITE. Location: `routes/teams.py:64-71`.
- Evidence: `GET /scan/<token>` calls `record_scan(...)` and commits even for an unauthenticated or unknown token.
- Impact: Repeated public GET requests can fill `QRScanEvent` and `ActivityLog` and consume the global write lock.
- Fix: Bound anonymous logging and retention after organizers confirm the required audit trail; also add reverse-proxy rate limiting.
- Mitigation: Restrict request rates at the edge now and watch database growth during rehearsal.
- False-positive notes: This may be an intentional event audit requirement, so removing these records without a retention decision could lose useful evidence.

### S4 — No application CSP (open)

- Rule ID: FLASK-HEADERS-001 / JS-CSP-001. Location: `app.py:175-184`, templates with inline scripts/styles.
- Evidence: Central response headers include content-type, referrer and frame policies, but no `Content-Security-Policy` header.
- Impact: A future HTML insertion flaw would have fewer browser-side restrictions.
- Fix: Inventory inline code, add a compatible policy, and verify all pages and camera/socket flows in a browser.
- Mitigation: Keep Jinja escaping and JavaScript `esc()`/`textContent` use; avoid new dynamic HTML sinks.
- False-positive notes: A proxy may provide CSP; no deployed proxy response was inspected.

## Verified controls and limits

Flask-WTF globally protects mutating requests (`app.py:40`); login and logout forms use CSRF tokens. Session cookies are HTTP-only and SameSite Lax, with Secure required in production (`config.py:20-29`, `config.py:49-50`). Passwords and PINs use Werkzeug hashes (`models/__init__.py`). Admin/team access checks are centralized in `routes/common.py`; result publication gates participant access in `routes/scores.py`. No SQL string interpolation, shell execution, user-file upload, dynamic template rendering or outbound HTTP request path was found in the application code. An installed-package compatibility check passed, but a vulnerability advisory scan was not available, so dependency CVE status is unknown.
