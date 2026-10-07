# Rolling team batches

## Event day setup

1. Back up the production database and confirm the backup can be restored before applying `flask --app app db upgrade`. Run the upgrade from `swayambhu`, then run `flask --app app init-db` if the event row and rounds have not been seeded.
2. Enter teams and assign each a Round 1 QR. New teams fill batches in team creation order, five eligible teams per batch by default. Batch 1 is released automatically. The final batch may contain one to four teams.
3. Open **Batches** in the admin dashboard and verify team order, membership and the waiting status of later batches. Team editing can move a team to another batch before it starts a round. A super-admin may use the batch assignment API with `override: true` to exceed capacity, with an audit entry.
4. In **Round Control**, choose **Open all rounds** once the questions, QR codes and stations are ready. This activates the event and Rounds 1–3 together. Keep the global rounds open until every eligible batch has finished. The server rejects ending a round while an eligible team is unfinished.
5. Only teams in released or active batches can start Round 1. A waiting team sees its batch number and a waiting message. Each team still completes the previous round before progressing.

If rounds from an earlier rehearsal show as ended in a TEST database, a super-admin can choose **Reopen test rounds** in Round Control. The server permits this only when no team progress or results have been recorded. It clears old end times and opens all three rounds together; it does not delete teams or content. Production events cannot use this recovery action.

## Automatic release

The first successful Round 3 desktop attachment in a batch releases the next waiting batch with eligible teams in the same transaction. Other teams in the earlier batch continue independently. Later Round 3 entries do not release another batch. An empty next batch stays waiting and is released when its first eligible team is assigned after the predecessor has triggered.

Batch states are `WAITING`, `RELEASED`, `IN_PROGRESS`, `PAUSED`, and `COMPLETED`. The `PAUSED` state blocks new Round 1 starts; teams already in a round can finish it. A batch is completed when all its assigned teams are completed, disabled, or disqualified. Disabled and disqualified teams cannot log in and do not count toward active capacity. Re-enabling one in a full batch requires a super-admin `batch_override: true` on the team edit API and creates an audit entry. A team that has started a round cannot be reassigned.

## Coordinator controls

The Batches screen displays release and trigger times, team positions and progress. A super-admin can release a waiting batch early, pause it, or resume it, with a required reason. These actions and automatic transitions appear in Activity Logs. The team roster, monitoring view, team timeline and teams CSV include batch information. Ranking remains based on scores and existing tie-break rules.

Administrators can open a team directly from its batch card to edit member details, its Round 1 QR or its batch assignment before it starts. The team editor lists QR labels and batch numbers so staff do not have to enter database IDs. QR Management supports creation, editing before recorded scans, activation/deactivation and archival. Super-admins can permanently delete unused QRs and teams; records with event activity must be archived to preserve history. Super-admins can delete any empty batch; move all teams out first. Questions supports creation, editing, activation/deactivation and deletion before the question is used. A super-admin can add staff assistants with ADMIN access in Settings and disable their access later.

If a released batch has no team able to reach Round 3, a super-admin must release the next batch manually. A waiting batch with no eligible teams stays waiting until an eligible team is assigned.

For a rehearsal, use a separate TEST database with at least six teams. Confirm that team 6 cannot start Round 1, then take a team from Batch 1 through the desktop QR and confirm that team 6 can start. Repeat with two Round 3 entries close together to verify that only one `BATCH_RELEASED` audit entry is recorded.

The isolated load simulation also runs rolling waves: `venv/bin/python scripts/simulate_event.py --teams 6 10`. It creates a temporary database, verifies all batches finish, and leaves event data untouched.

## API

- `GET /api/admin/batches`: batch configuration, states and teams.
- `POST /api/admin/batches`: add a batch; optional `capacity`. Capacity above the event default requires super-admin access.
- `PATCH /api/admin/batches/config`: set `batch_size` for future batches (super-admin).
- `POST /api/admin/batches/<id>/teams`: assign an unstarted team with `team_id`, optional `position`, and optional super-admin `override`.
- `POST /api/admin/batches/<id>/reorder`: provide every assigned team ID in the desired `team_ids` order.
- `POST /api/admin/batches/<id>/release|pause|resume`: super-admin action with `reason`.
- `POST /api/rounds/start-all`: open all three global rounds together; batch status remains the Round 1 entry gate.

The migration assigns existing teams by database ID in groups of five. Any group containing an already-started team, and every preceding group, is released so that current progress remains accessible. Review those assignments before resuming the event.
