# Event flow and documented assumptions

## Team progression

REGISTERED → ROUND_1_ACTIVE → ROUND_1_COMPLETED → ROUND_2_ACTIVE →
ROUND_2_COMPLETED → ROUND_3_ACTIVE → COMPLETED.
DISABLED/DISQUALIFIED blocks all participant actions. Global round states are LOCKED,
READY, ACTIVE, PAUSED and ENDED. Ending a global round never awards individual completion.
Several global rounds may be ACTIVE concurrently so teams can physically progress at
individual speeds. Admin pause blocks writes and preserves existing assignments/answers.
Read-only saved clues and drafts remain accessible while paused.

## Round 1

Staff assign each team a specific initial QR before the event and write its number on
an envelope. The team starts Round 1 and scans that exact code. A valid scan completes
Round 1 and saves the clue; teams solve it physically. There is **no digital answer
submission**. Round 1 marks default to zero and are configurable before the first scan.
QR `room` is the destination. A Round 2 QR must use that same room string to be accepted;
keep destination labels consistent (including capitalization). Blank legacy destinations
must be repaired before printing. The riddle answer is never embedded in the QR URL.

## Round 2

A destination QR references a named quiz containing exactly ten active MCQs. Scanning
starts and fixes the team's quiz assignment. Responses save individually; refresh reloads
them. All ten must be answered before final submission. The new quiz has no per-question
countdown: the specification did not require one, and the old countdown conflicted with
a single saved ten-question submission. Server scoring uses the saved snapshot marks/keys.
Participants see only confirmation and configured Round 3 instructions, never correctness
or score before publication. Multiple destination quizzes are supported.

## Round 3

Every team has one assigned password-riddle QR code, configured in Event Operations.
Scanning it reveals a riddle on the team's phone. The team enters the answer as a password
in its dashboard. A correct password qualifies the team to collect a question sheet from
an organizer. There is no hidden-sheet location QR.

Only the assigned team can use its QR, and Round 2 must be complete. The first successful
Round 3 scan starts its round session and triggers the next batch release, once per batch.
The riddle remains visible on the dashboard after refresh; before scanning it stays hidden.

The password is hashed and checked server-side. Each team has exactly three attempts,
persisted across devices and logins. Three failures do not qualify the team for a sheet;
the team must contact the organizer. Attempts cannot be reset through administration.
No desktop station, online questions, automatic grading, or final question bank is required.

An admin confirms handing over the physical sheet only after the app verifies the correct
password. After the team writes answers on paper and returns it, the admin records
submission. Teams can tap Complete Round 3 after finishing their paper answers and
returning the sheet. The app immediately saves the server finish time and stops the clock.
Later admin paper receipt and human judging preserve that finish time. Admin submission
can still record completion if the team has not tapped the button.

A judge enters total paper marks within the configured maximum and a judging note.
Corrections are audited. Results cannot be generated until every eligible team's paper
has been evaluated, and result locks prevent mark changes. Participants see confirmation
and submission status; marks remain hidden until publication.

## Scoring/results

Total = Round 1 + Round 2 + Round 3 + bonus − penalty. Question marks, Round 1 marks,
bonus and penalty are configurable; no hidden speed bonus is imposed. Ranking breaks
score ties by completed session duration, completion time, then Team ID (retained policy).
Teams with unreviewed final answers cannot enter finalized results. End global rounds,
review every answer, generate result snapshots, lock and explicitly publish them. Participant
leaderboard visibility is a separate switch and still requires result publication.
Unlocking requires a super-admin and reason, withdraws publication and records the previous
results. Re-review, regenerate, lock and publish after any correction.

One event per database is the safe default. There is no automatic production reset or
multi-event tenancy. TEST reset removes test teams/progress/evidence while retaining
question/quiz/station/QR/admin configuration. Separate databases avoid production loss.
