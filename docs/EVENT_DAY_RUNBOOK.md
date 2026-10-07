# Event-day runbook

## Before the event

- [ ] Assign a primary operator, a backup super-admin and station coordinators.
- [ ] Confirm the deployment is PRODUCTION and rehearsals use another database/secret.
- [ ] Back up PostgreSQL; verify restoration into a new isolated database.
- [ ] Verify server health, HTTPS certificate, stable domain, DNS and campus Wi-Fi coverage.
- [ ] Install reviewed migrations and seed three rounds. Disable debug/automatic schema creation.
- [ ] Verify admin roles, private passwords, login throttling and locked-score behavior.
- [ ] Create teams with 1–3 members; privately distribute IDs/PINs; assign envelope QRs.
- [ ] Create every Round 1 clue/destination and every destination quiz with exactly ten MCQs.
- [ ] Ensure destination room labels match; verify question keys/marks and quiz order.
- [ ] Create a sufficiently large Round 3 bank; configure assignment count and manual judging rubric.
- [ ] Configure every desktop's identity/riddle/password; open its station QR display.
- [ ] Generate QR PNGs against the canonical HTTPS host, print and physically place them.
- [ ] Scan **every printed code** on actual phones; verify inactive/incorrect codes are rejected.
- [ ] Test actual desktop browsers and camera permissions; use a browser-accessible station account.
- [ ] Run full rehearsal: R1 scan → quiz autosave/refresh/submit → R3 success or three failures → final.
- [ ] Disconnect/reconnect Wi-Fi; verify unsaved indicators and confirmed submissions.
- [ ] Verify the exported logs and scores match rehearsal answers; record readiness sign-off.
- [ ] Make a fresh backup; stop TEST deployment and confirm PRODUCTION team/content counts.

## Start and operate

- [ ] Activate intended QR codes and event; unlock/start Round 1.
- [ ] Unlock/start Rounds 2 and 3 when stations are staffed. Global rounds may overlap.
- [ ] Keep Dashboard, Live Monitor and Event Operations desktop monitor available.
- [ ] Observe round populations, team timelines, rejected scans and password attempts.
- [ ] On socket disconnect, use polling and reload; assignments survive server restart.
- [ ] If a phone loses connectivity, keep the answer page open. Confirm saved status before submission.
- [ ] For lost credentials, reset PIN privately (other sessions revoke). Do not reset attempts.
- [ ] For wrong/inactive QR, inspect assigned envelope/destination and scan audit before changing state.
- [ ] Pause the affected round if coordinated repair is needed, then resume. Ending cannot be undone
      through normal controls; it does not finish incomplete teams.
- [ ] Record coordinator exceptions with reason; super-admin advance covers only Rounds 1–2.
- [ ] Never edit live database rows directly or regenerate occupied station QR tokens.
- [ ] Monitor application errors, PostgreSQL connections, CPU/disk, Wi-Fi and backup availability.

## Finish and publish

- [ ] Confirm all eligible teams have submitted; resolve incomplete teams or documented disqualifications.
- [ ] End all three global rounds.
- [ ] Review every manually graded final answer; verify Round 1/2/3, bonus and penalty ledger.
- [ ] Export teams, scans, quiz responses/results, final answers, scores, leaderboard and complete logs.
- [ ] Generate results and independently check top rankings/tie breaks with judges.
- [ ] Configure participant leaderboard visibility, then lock results and explicitly publish.
- [ ] If correction is needed: super-admin unlock with reason → withdraw publication → correct →
      regenerate → re-lock → republish. Retain both before/after evidence.
- [ ] Back up PostgreSQL and verify off-host copy/checksum.
- [ ] Log teams out of shared desktops, retain results/evidence securely, stop external access as agreed.
- [ ] Archive the deployment/database; never run a test reset on event data.

## Recovery notes

A web-server restart does not reset saved answers or attempts. A station may be used by
the next team only after the previous team's final submission completes; log out the
previous team first. If an incomplete station needs relocation, pause Round 3 and involve
a super-admin; arbitrary participant station switching is intentionally blocked. For a
server/database outage, pause physical participation until service and state are verified.
Do not announce successful submissions based solely on a browser click or coordinator guess.
