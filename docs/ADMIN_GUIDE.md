# Administrator guide

Create the initial super-admin through the interactive `create-admin` CLI. ADMIN users
manage teams/content/rounds, monitor progress and judge scores. SUPER_ADMIN additionally
controls event configuration, accounts, result unlocking, test reset and progression
exceptions. Keep at least two trusted super-admins for recovery; each should have a private
password. Account changes and PIN resets revoke existing affected sessions.

The existing console includes Teams, QR Management, Questions, Round Control, Live Monitor,
Scores, Leaderboard, Results and Audit Logs. **Event Operations** adds quizzes, Round 3 password QRs,
offline sheet judging, score adjustments, exports, QR editing/token rotation and critical controls.

Event Operations groups tools into Challenges, Round 3 · offline, Judging & scores, QR tools,
Results & exports, and Configuration. The quiz builder uses checkboxes and shows how
many of the required ten questions are selected. Navigation preserves the current
section in the URL. On mobile, open navigation with the menu button; Escape closes it.
Dialogs support Escape, keyboard focus containment and return focus to their opener.
The header reports the live connection separately from the event's active/paused state.

1. Create 1–3 named members per team. Generated PINs are displayed once. Save/share them
   privately; never place the credential list on a public noticeboard.
2. Add Round 1 riddles as QR clue text. Generate named QR codes, preview their PNGs and
   assign each team's Round 1 QR database ID in the team editor. The label goes on the
   envelope. Match Round 1 destination and Round 2 room strings exactly.
3. Create Round 2 MCQs with all four options and correct keys. Select exactly ten in the
   quiz builder. Questions appear by configured order; selected IDs define quiz order.
   API clients can specify a different explicit ordering. Attach quiz ID to destination QR.
4. In QR Management → Create QR, select Round 3 and configure each team's password riddle, secret password,
   room, and maximum paper marks. Event Operations → Challenges provides the same setup. This creates one inactive QR per team. Download/print
   it from Round 3 · offline. Prepare physical question/answer sheets to hand out after
   the team enters the correct password on its frontend. Each team has three attempts.
5. Activate printed QR codes, unlock/start rounds. Global rounds may overlap. Pause
   preserves all individual data; resume reopens actions. Ending a round blocks remaining
   actions without granting completion.
6. Find teams by name/ID. Timeline shows members, state, per-round scores, successful and
   rejected scans, logins and submissions. View Round 3 QR status, password attempts, and paper progress in Operations.
7. In Round 3 · offline, confirm sheet handover only after a verified
   password. Teams tap Complete Round 3 after finishing and returning their sheet to save their
   own finish time. Record the returned answer sheet afterward; this preserves the team's
   saved time, or completes the round if the team has not used its button. In Judging & scores, enter its human-evaluated total
   and a judging note. Use this same form for corrections; use score adjustments for Rounds
   1–2 or bonus/penalty. Changes are audited and blocked after result locking.
8. End all rounds, resolve missing submissions or disqualify ineligible teams, then generate,
   lock and publish results. Enable participant leaderboard visibility if desired before
   locking. Scores remain hidden until publish.
9. Export every required CSV, back up the database, and retain evidence securely.

Archive teams and QR codes instead of deleting evidence. A regenerated QR invalidates its
old token and must be reprinted. Do not regenerate Round 3 tokens after the team enters the round.
Questions already used by a quiz are frozen to keep grading consistent.

A super-admin progression override is for documented coordinator exceptions in Rounds 1–2;
it is logged and does not award marks or bypass Round 3's attempt rules. Stop TEST mode
before using the explicitly confirmed reset. Reset removes test teams/attempts/scan/audit
history, preserves content and records a new TEST_RESET log. There is no production reset.

Apply migration `b723a91e40cd` with `flask --app app db upgrade` before running this version.
The migration preserves legacy desktop/final records for historical reference; those
routes return 410 and are no longer used. Configure new password QRs explicitly; old stations
are not automatically converted into team-specific riddles. TEST reset removes team password-QR
assignments while retaining QR content; create fresh password QRs for the next rehearsal.
