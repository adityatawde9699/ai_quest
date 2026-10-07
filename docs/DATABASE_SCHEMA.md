# Database schema

One event occupies one database. Separate TEST and PRODUCTION databases are required.
Exactly three Round records are seeded; global status and Team.state are independent.

| Table | Purpose and invariants |
|---|---|
| admin | Unique username, hashed password, role, active flag; disabling/resetting revokes sessions |
| team / team_member | Unique Team ID, hashed PIN, independent eligibility/status and state, assigned initial QR; 1–3 members validated by administration |
| event | Singleton configuration, active flag, marks/count/destination, result lock/publication and write serialization version |
| round / round_session | Global round status; unique team/round session with authoritative start/completion timestamps |
| question | Reused bank for clues, Round 2 MCQs and typed Round 3 questions; ordering, active flag, key and marks |
| qr_challenge | Existing QR table retained; unique opaque token and label, round, quiz, clue/title/destination and active/archive status |
| scan_log | Existing unique successful team/QR record retained |
| qr_scan_event | Every recognized/unrecognized, anonymous, repeated or rejected scan, nullable team/QR, timestamp/status/IP/UA |
| quiz / quiz_question | Named ordered ten-question quiz; unique quiz/position and quiz/question |
| quiz_attempt / answer | Unique attempt per team; immutable server-only snapshots and persistent per-question answers; submitted_at freezes attempt |
| desktop / desktop_session | Unique station identity/QR, hashed challenge password; one persistent session per team; occupancy protected transactionally |
| password_attempt | Immutable number/correctness/timestamp; unique session/number; DB check limits number and session counter to 1–3 and 0–3 respectively |
| final_assignment / final_answer | One random fixed snapshot set per team; unique assignment/question saved response and reviewed marks |
| score | Existing unique team/round ledger; adjustments live in team.bonus/team.penalty |
| final_result | Unique team snapshot with rank/score/time and lock flag |
| activity_log | Existing audit history extended with participant identity/request ID/metadata |
| rate_bucket | Hashed login throttle identity and shared minute-window count |

Foreign keys and indexes cover team/round/QR lookups, scan timestamps/statuses and audit
queries. Team and QR deletion is archival through application APIs to preserve evidence.
Legacy member columns remain as compatibility fields; administration synchronizes their
normalized TeamMember rows. Challenge snapshots contain grading keys only on the server;
participant serializers strip keys and marks.

Migration `66d5f8c67ffe` extends the existing three-revision chain, fills defaults on
populated tables, seeds Event, renames the paper round and imports successful old scans
into complete scan history. No production migration is performed automatically. Review
legacy progress before using it for a new event; an old timed quiz is not equivalent to a
new complete ten-question QuizAttempt.
