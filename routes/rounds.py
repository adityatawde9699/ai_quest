from flask import Blueprint, current_app, jsonify
from flask_login import current_user

from extensions import db
from models import (Answer, DesktopSession, FinalAnswer, FinalAssignment, FinalResult,
                    QRScan, QuizAttempt, Round, RoundSession, Score,
                    Team, utcnow)
from routes.common import admin_required, audit, emit_activity, emit_leaderboard, iso_utc, team_required

rounds_bp = Blueprint("rounds", __name__)


@rounds_bp.post("/api/rounds/start-all")
@admin_required
def start_all_rounds():
    """Open the global challenges together; batch release still gates Round 1."""
    from services.event import event_config

    event = event_config()
    if event.results_locked:
        return jsonify(error="Results are locked."), 409
    rounds = Round.query.order_by(Round.number).all()
    if [row.number for row in rounds] != [1, 2, 3]:
        return jsonify(error="Configure all three rounds before opening the event."), 409
    reopening = any(row.status == "ENDED" for row in rounds)
    if reopening:
        if current_user.role != "super-admin":
            return jsonify(error="Super-admin access is required to reopen test rounds."), 403
        if (current_app.config["APP_ENV"] == "production"
                or current_app.config["EVENT_MODE"] != "TEST"
                or event.mode != "TEST"):
            return jsonify(error="Ended rounds cannot be reopened outside TEST mode."), 409
        progress_models = (RoundSession, QRScan, Answer, QuizAttempt,
                           DesktopSession, FinalAssignment, FinalAnswer, Score, FinalResult)
        if event.results_published or any(model.query.first() for model in progress_models):
            return jsonify(error="Recorded test progress or published results prevent reopening rounds."), 409
    changed = any(row.status != "ACTIVE" for row in rounds) or not event.active
    event.active = True
    started_at = utcnow()
    for row in rounds:
        row.status = "ACTIVE"
        row.started_at = started_at if reopening else row.started_at or started_at
        if reopening:
            row.ended_at = None
    if changed:
        audit("TEST_ROUNDS_REOPENED" if reopening else "ROUNDS_OPENED_TOGETHER", event.name)
    db.session.commit()
    if changed:
        emit_activity("All three rounds opened; batch release controls Round 1 entry", "round")
    return jsonify(rounds=[{"id": row.id, "number": row.number, "status": row.status} for row in rounds])


@rounds_bp.get("/api/rounds")
@admin_required
def list_rounds():
    return jsonify([
        {"id": item.id, "number": item.number, "name": item.name, "status": item.status,
         "started_at": iso_utc(item.started_at), "ended_at": iso_utc(item.ended_at)}
        for item in Round.query.order_by(Round.number)
    ])


@rounds_bp.post("/api/rounds/<int:round_id>/<action>")
@admin_required
def control_round(round_id, action):
    event_round = db.session.get(Round, round_id)
    if not event_round:
        return jsonify(error="Round not found."), 404
    from services.event import event_config
    event = event_config()
    if event.results_locked:
        return jsonify(error="Results are locked."), 409
    if action == "start" and event_round.status == "READY":
        return start_all_rounds()
    if action in ("start", "resume"):
        if event_round.status not in ("READY", "ACTIVE", "PAUSED"):
            return jsonify(error="Unlock this round before starting it."), 409
        was_paused = event_round.status == "PAUSED"
        event.active = True
        event_round.status = "ACTIVE"
        event_round.started_at = event_round.started_at or utcnow()
        label = "resumed" if action == "resume" or was_paused else "started"
    elif action == "pause":
        if event_round.status != "ACTIVE":
            return jsonify(error="Only an active round can be paused."), 409
        event_round.status = "PAUSED"
        label = "paused"
    elif action == "end":
        if event_round.status not in ("ACTIVE", "PAUSED"):
            return jsonify(error="Only an active or paused round can be ended."), 409
        if Team.query.filter(Team.status.notin_(("COMPLETED", "DISABLED", "DISQUALIFIED"))).first():
            return jsonify(error="Complete or disqualify every eligible team before ending a global round."), 409
        event_round.status = "ENDED"
        event_round.ended_at = utcnow()
        label = "ended"
    elif action == "unlock":
        return jsonify(error="Use Open all rounds to start the event."), 409
    else:
        return jsonify(error="Unknown round action."), 404
    audit(f"Round {label}", f"Round {event_round.number}")
    db.session.commit()
    emit_activity(f"Round {event_round.number} {label}", "round")
    emit_leaderboard()
    return jsonify(status=event_round.status)


@rounds_bp.post("/api/team/rounds/<int:round_id>/complete")
@team_required
def complete_team_round(round_id):
    return jsonify(error="Round completion is recorded automatically after the challenge."), 409
