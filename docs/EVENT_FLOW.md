# Event flow and documented assumptions

## Team progression

REGISTERED → ROUND_1_ACTIVE → ROUND_1_COMPLETED → ROUND_2_ACTIVE →
ROUND_2_COMPLETED → ROUND_3_ACTIVE → PASSWORD_CHALLENGE → FINAL_CHALLENGE → COMPLETED.
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

Staff open `/station/<id>` on each college desktop to display its QR. A logged-in team
scans the QR on its phone, occupying that available station. The team then logs in on the
desktop and opens its assigned desktop challenge from the team dashboard. A station serves
one active team at a time, and a team has one fixed desktop session. Completed stations
become available to another team. Overrides do not reset password attempts.

The password is a **web application challenge**, not an operating-system account unlock.
OS-level authentication cannot safely implement the rule that three failures unlock the
final web challenge; organizers should keep the browser accessible in a station account.
The attempt limit applies to the authenticated team across all browsers/devices, not to
physical hardware attestation. A correct password **or three failures** unlocks the final.

The server assigns `final_question_count` questions (default ten) using secure random
sampling and persists complete snapshots. Enough active bank questions must exist before
consuming a password attempt. Assignment refresh cannot reroll questions. Uniqueness
between all teams is not guaranteed; different sequences are expected but collisions are
possible and fair. The bank should be materially larger than the assignment count.

MCQ, true/false, numerical and code-output keys are graded exactly after trimming/case
normalization; numerical grading compares finite decimals exactly. SHORT ANSWER, LOGICAL
and AI/TECHNICAL responses need human marks. These assumptions are deliberately simple;
use a manual audited score adjustment for organizer-approved exceptions.

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
