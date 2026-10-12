# API reference

Authentication uses signed same-origin session cookies. HTML login/logout forms include
CSRF tokens. JSON mutations send `X-CSRFToken` from the page's csrf-token meta element.
Errors return `{"error":"safe message"}` with 400/403/404/409 as appropriate. Participant
identity is always taken from the authenticated session, never the request body.

## Participant

| Method/path | Behavior |
|---|---|
| POST /team/login | Team ID/PIN form; preserves scanned token through login |
| POST /logout | Clears session, records audit |
| GET /api/team/dashboard | Team/status/next round, saved clue/destination and offline Round 3 status; score null before publication |
| GET /api/team/rounds | Global controls |
| POST /api/team/rounds/1/start | Start assigned Round 1; later rounds require a scan |
| GET /scan/:token | Resolve team login/dashboard; never embed grading keys |
| POST /api/team/scan | `{token}`; records complete scan event and valid progress |
| GET /api/team/quiz | Assigned ten-question quiz and saved drafts only |
| PUT /api/team/quiz/answers/:question_id | `{answer: "A"}` draft |
| POST /api/team/quiz/submit | Require all answers; freeze and score once |
| GET /api/team/round3 | Scanned riddles, attempts remaining, verified password and paper status; no marks or password hash |
| POST /api/team/round3/password | `{password}` after scanning the assigned password QR; three attempts, no sheet access on failures |
| POST /api/team/round3/complete | After verified password and finishing paper answers, save server finish time and complete the quest; repeated completion is rejected |
| GET /api/leaderboard | Admin live data; participant [] unless published and visibility enabled |

Legacy round-complete and paper-score endpoints reject manual bypasses. Old timed question
submission and QR-answer endpoints are removed.

## Administration

- `/api/overview`, `/api/admin/monitoring`, `/api/admin/activity`, `/api/admin/scores`: GET.
- `/api/teams`: GET search `?q=...`, POST name/member_1..3/login_pin/assigned_qr_id/assigned_round2_qr_id/round3_qr_id/round3_max_points.
- `/api/teams/:id`: PUT edits team details, Round 1, Round 2 and Round 3 QR assignments, maximum Round 3 marks and status; DELETE archives.
- `/api/teams/:id/reset-pin`: POST, shown once; previous sessions revoked.
- `/api/teams/:id/timeline`: GET team members, progress, scores and complete activity.
- `/api/rounds`: GET; `/api/rounds/:id/{unlock,start,pause,resume,end}`: POST.
- `/api/qrs`: GET, POST round_id/qr_number/title/clue/room/question_id/quiz_id/expires_at. Round 3 additionally requires qr_number and password; assignment happens in Team Management. The password hash is never returned.
- `/api/qrs/:id`: PATCH before use; `/{activate,deactivate,regenerate,archive}`: POST.
- `/api/qrs/:id/image`: GET PNG; `/api/qrs/download`: GET ZIP; `/admin/qrs/print`: GET.
- `/api/admin/scans`: GET complete scan events (latest 1000, optional team_id);
  export scans CSV for unlimited history.
- `/api/admin/questions`: GET/POST bank; `/:id`: PATCH/DELETE unused content.
  kind/position/prompt/options/correct_answer/points are server-controlled.
- `/api/admin/quizzes`: GET/POST `{title, question_ids:[ten ordered ids]}`;
  `/:id`: PATCH active/question_ids before attempts.
- `/api/admin/round3`: GET progress; POST `{team_id,password_qr_id,max_points}` assigns an existing Round 3 QR to a team, subject to the one-assignment-per-batch rule.
- `/api/admin/round3/:id`: PATCH riddles/password/room/max_points before entry.
- `/api/admin/round3/:id/{activate,deactivate}`: POST `{}` controls the password QR.
- `/api/admin/round3/:id/sheet`: POST `{}` confirms organizer sheet handover after a verified password.
- `/api/admin/round3/:id/submit`: POST `{}` records returned paper and completes the round.
- `/api/admin/round3/:id/review`: POST `{points,reason}` records human evaluation or correction.
  Marks must be between zero and max_points; returned paper is required.
- Old station/desktop/final/assignment endpoints return 410. Stored legacy records are preserved.
- `/api/admin/teams/:id/score`: POST round_id/points/bonus/penalty/reason (round score adjustments only for Rounds 1–2).
- `/api/results`: GET; `/api/results/{generate,lock,publish}`: POST.
- `/api/results/unlock`: POST `{reason}` (SUPER_ADMIN only).
- `/api/admin/event`: GET; PATCH active/leaderboard_visible/
  round_1_points/round_3_destination (SUPER_ADMIN only).
- `/api/admin/accounts`: GET/POST username/password/role; `/:id`: PATCH
  password/role/active (SUPER_ADMIN only; another super-admin must edit your own account).
- `/api/admin/teams/:id/advance`: POST `{round:1|2,reason}` (SUPER_ADMIN only).
- `/api/admin/test-reset`: POST `{confirmation:"RESET TEST PROGRESS"}` (SUPER_ADMIN,
  inactive TEST database only; production is blocked).
- `/api/admin/export/:kind.csv`: GET teams/scans/quiz-responses/quiz-results/round3-sheets/
  scores/leaderboard/logs. Spreadsheet formula characters are escaped.
