from flask import Blueprint, jsonify, request
from flask_login import current_user

from extensions import db
from models import Batch, Team, utcnow
from routes.common import admin_required, super_admin_required, audit, emit_activity
from services.batches import assign, release, serialize
from services.event import EventError, event_config

batches_bp = Blueprint("batches", __name__)


@batches_bp.get("/api/admin/batches")
@admin_required
def list_batches():
    return jsonify(batch_size=event_config().batch_size,
                   batches=[serialize(b) for b in Batch.query.order_by(Batch.number)])


@batches_bp.post("/api/admin/batches")
@admin_required
def create_batch():
    data = request.get_json() or {}
    event = event_config()
    if event.results_locked:
        raise EventError("Results are locked.")
    capacity = data.get("capacity", event.batch_size)
    if not isinstance(capacity, int) or isinstance(capacity, bool) or capacity < 1 or capacity > 100:
        raise EventError("Batch capacity must be between 1 and 100.", 400)
    if capacity > event.batch_size and current_user.role != "super-admin":
        raise EventError("Super-admin override required for a larger batch.", 403)
    last = Batch.query.order_by(Batch.number.desc()).first()
    batch = Batch(number=last.number + 1 if last else 1, capacity=capacity)
    if batch.number == 1:
        batch.status, batch.released_at = "RELEASED", utcnow()
    db.session.add(batch)
    audit("BATCH_CREATED", str(batch.number), {"capacity": capacity})
    if batch.status == "RELEASED":
        audit("BATCH_RELEASED", str(batch.number), {"reason": "INITIAL" if batch.number == 1 else "PREVIOUS_TRIGGERED"})
    db.session.commit()
    return jsonify(serialize(batch)), 201


@batches_bp.delete("/api/admin/batches/<int:batch_id>")
@super_admin_required
def delete_batch(batch_id):
    batch = db.get_or_404(Batch, batch_id)
    if event_config().results_locked:
        raise EventError("Results are locked.")
    if batch.teams:
        raise EventError("Move or remove every team from this batch before deleting it.", 409)
    number = batch.number
    audit("BATCH_DELETED", str(number))
    db.session.delete(batch)
    db.session.commit()
    emit_activity(f"Batch {number} deleted", "batch")
    return jsonify(ok=True, deleted=True)


@batches_bp.patch("/api/admin/batches/config")
@super_admin_required
def batch_config():
    size = (request.get_json() or {}).get("batch_size")
    if not isinstance(size, int) or isinstance(size, bool) or size < 1 or size > 100:
        raise EventError("Batch size must be between 1 and 100.", 400)
    event = event_config()
    before = event.batch_size
    event.batch_size = size
    audit("BATCH_CONFIG_UPDATED", event.name, {"before": before, "after": size})
    db.session.commit()
    return jsonify(batch_size=size)


@batches_bp.post("/api/admin/batches/<int:batch_id>/teams")
@admin_required
def assign_team(batch_id):
    batch = db.get_or_404(Batch, batch_id)
    data = request.get_json() or {}
    raw_id = data.get("team_id")
    if isinstance(raw_id, bool) or not str(raw_id).isdigit():
        raise EventError("Provide a valid team ID.", 400)
    team = db.get_or_404(Team, int(raw_id))
    position = data.get("position")
    if position is not None and (not isinstance(position, int) or isinstance(position, bool) or position < 1):
        raise EventError("Position must be a positive whole number.", 400)
    override = data.get("override") is True
    if override and current_user.role != "super-admin":
        raise EventError("Super-admin override required.", 403)
    if event_config().results_locked:
        raise EventError("Results are locked.")
    assign(team, batch, position, override)
    db.session.commit()
    return jsonify(serialize(batch))


@batches_bp.post("/api/admin/batches/<int:batch_id>/reorder")
@admin_required
def reorder_batch(batch_id):
    batch = db.get_or_404(Batch, batch_id)
    if event_config().results_locked:
        raise EventError("Results are locked.")
    ids = (request.get_json() or {}).get("team_ids")
    current = [team.id for team in batch.teams]
    if (not isinstance(ids, list) or any(not isinstance(item, int) or isinstance(item, bool) for item in ids)
            or len(ids) != len(current) or set(ids) != set(current)):
        raise EventError("Provide every team in this batch exactly once.", 400)
    before = current[:]
    for index, team in enumerate(batch.teams, 1):
        team.batch_position = -index
    db.session.flush()
    for position, team_id in enumerate(ids, 1):
        db.session.get(Team, team_id).batch_position = position
    audit("BATCH_REORDERED", str(batch.number), {"before": before, "after": ids})
    db.session.commit()
    db.session.expire(batch, ["teams"])
    return jsonify(serialize(batch))


@batches_bp.post("/api/admin/batches/<int:batch_id>/<action>")
@super_admin_required
def change_batch(batch_id, action):
    batch = db.get_or_404(Batch, batch_id)
    reason = str((request.get_json() or {}).get("reason", "")).strip()
    if not reason:
        raise EventError("Enter a reason for this batch action.", 400)
    reason = reason[:1000]
    if event_config().results_locked:
        raise EventError("Results are locked.")
    if action == "release":
        release(batch, reason)
    elif action == "pause" and batch.status in ("RELEASED", "IN_PROGRESS"):
        batch.status = "PAUSED"
        audit("BATCH_PAUSED", str(batch.number), {"reason": reason})
    elif action == "resume" and batch.status == "PAUSED":
        batch.status = "IN_PROGRESS" if any(t.round_sessions for t in batch.teams) else "RELEASED"
        audit("BATCH_RESUMED", str(batch.number), {"reason": reason})
    else:
        raise EventError("This batch action is not available.", 409)
    db.session.commit()
    emit_activity(f"Batch {batch.number} {action}d: {reason[:100]}", "batch")
    return jsonify(serialize(batch))
