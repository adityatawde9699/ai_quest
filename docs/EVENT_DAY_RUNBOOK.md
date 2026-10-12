# Event-day runbook

## Before the event

- [ ] Assign a primary operator, a backup super-admin and room coordinators.
- [ ] Confirm the deployment is PRODUCTION and rehearsals use another database/secret.
- [ ] Back up PostgreSQL; verify restoration into a new isolated database.
- [ ] Verify server health, HTTPS certificate, stable domain, DNS and campus Wi-Fi coverage.
- [ ] Install reviewed migrations and seed three rounds. Disable debug/automatic schema creation.
- [ ] Verify admin roles, private passwords, login throttling and locked-score behavior.
- [ ] Create teams with 1–3 members; privately distribute IDs/PINs; assign envelope QRs.
- [ ] Create every Round 1 clue/destination and every destination quiz with exactly ten MCQs.
- [ ] Ensure destination room labels match; verify question keys/marks and quiz order.
- [ ] Create Round 3 password QRs in QR Management with QR number, title, riddle, and password.
- [ ] Assign the appropriate Round 3 QR and maximum paper marks to each team in Team Management; use a QR no more than once per batch.
- [ ] Print the assigned password QRs and prepare physical question/answer sheets for organizer handover.
- [ ] Generate QR PNGs against the canonical HTTPS host, print and physically place them.
- [ ] Scan **every printed code** on actual phones; verify inactive/incorrect codes are rejected.
- [ ] Test phone QR scanning, password entry, and organizer collection/submission/judging controls.
- [ ] Run full rehearsal: R1 scan → quiz autosave/refresh/submit → R3 password success (maximum three attempts) → physical paper → human evaluation.
- [ ] Disconnect/reconnect Wi-Fi; verify unsaved indicators and confirmed submissions.
- [ ] Verify the exported logs and scores match rehearsal answers; record readiness sign-off.
- [ ] Make a fresh backup; stop TEST deployment and confirm PRODUCTION team/content counts.

## Start and operate

- [ ] Activate intended QR codes and event; unlock/start Round 1.
- [ ] Unlock/start Rounds 2 and 3 when rooms are staffed. Global rounds may overlap.
- [ ] Keep Dashboard, Live Monitor and Event Operations Round 3 paper monitor available.
- [ ] Observe round populations, team timelines, rejected scans and password attempts.
- [ ] On socket disconnect, use polling and reload; progress survives server restart.
- [ ] If a phone loses connectivity, keep the answer page open. Confirm saved status before submission.
- [ ] For lost credentials, reset PIN privately (other sessions revoke). Do not reset attempts.
- [ ] For wrong/inactive QR, inspect assigned envelope/destination and scan audit before changing state.
- [ ] Pause the affected round if coordinated repair is needed, then resume. Ending cannot be undone
      through normal controls; it does not finish incomplete teams.
- [ ] Record coordinator exceptions with reason; super-admin advance covers only Rounds 1–2.
- [ ] Never edit live database rows directly or regenerate Round 3 QR tokens after team entry.
- [ ] Monitor application errors, PostgreSQL connections, CPU/disk, Wi-Fi and backup availability.

## Finish and publish

- [ ] Confirm all eligible teams have submitted; resolve incomplete teams or documented disqualifications.
- [ ] End all three global rounds.
- [ ] Evaluate every physical Round 3 answer sheet and enter total marks; verify Round 1/2/3, bonus and penalty ledger.
- [ ] Export teams, scans, quiz responses/results, Round 3 sheet evaluations, scores, leaderboard and complete logs.
- [ ] Generate results and independently check top rankings/tie breaks with judges.
- [ ] Configure participant leaderboard visibility, then lock results and explicitly publish.
- [ ] If correction is needed: super-admin unlock with reason → withdraw publication → correct →
      regenerate → re-lock → republish. Retain both before/after evidence.
- [ ] Back up PostgreSQL and verify off-host copy/checksum.
- [ ] Retain results/evidence securely, stop external access as agreed.
- [ ] Archive the deployment/database; never run a test reset on event data.

## Recovery notes

A web-server restart does not reset saved quiz answers, riddles, or password attempts.
An organizer must confirm sheet collection and returned paper in the app. Keep physical
sheets labeled with Team ID, and record return promptly so judging time does not affect
tie breaks. During a server/database outage, pause participation until state is verified.
Do not hand out a password-path sheet based only on a participant claim; check the admin
monitor for the team's verified password.
