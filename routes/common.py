from functools import wraps
from datetime import timezone

from flask import jsonify, g, current_app
from flask_login import current_user

from extensions import db, socketio
from models import ActivityLog, utcnow


def iso_utc(value):
    if not value:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def admin_required(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated or getattr(current_user, "role", "") not in (
            "admin", "super-admin"
        ):
            return jsonify(error="Administrator access required."), 403
        return function(*args, **kwargs)

    return wrapped


def team_required(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated or getattr(current_user, "role", "") != "team":
            return jsonify(error="Team login required."), 403
        if current_user.status in ("DISABLED", "DISQUALIFIED"):
            return jsonify(error="This team is not allowed to continue."), 403
        return function(*args, **kwargs)

    return wrapped


def audit(action, target="", metadata=None):
    import json
    action = action.upper().replace(" ", "_")
    current_app.logger.info(json.dumps({"event": action, "request_id": getattr(g, "request_id", None), "timestamp": utcnow().isoformat(), "round": (metadata or {}).get("round"), "team_id": current_user.team_id if current_user.is_authenticated and getattr(current_user, "role", "") == "team" else None}))
    admin_id = current_user.id if current_user.is_authenticated and getattr(
        current_user, "role", ""
    ) in ("admin", "super-admin") else None
    db.session.add(
        ActivityLog(
            admin_id=admin_id,
            team_id=current_user.id if current_user.is_authenticated and getattr(current_user, "role", "") == "team" else None,
            request_id=getattr(g, "request_id", None),
            action=action,
            target=str(target),
            metadata_json=metadata or {},
        )
    )


def emit_activity(message, category="event"):
    socketio.emit("activity", {"message": message, "category": category}, room="admins")


def emit_leaderboard():
    # Admin clients fetch current standings when this notification arrives.
    socketio.emit("leaderboard_update", room="admins")

def super_admin_required(function):
    @wraps(function)
    @admin_required
    def wrapped(*args, **kwargs):
        if current_user.role != "super-admin":
            return jsonify(error="Super-admin access required."), 403
        return function(*args, **kwargs)
    return wrapped
