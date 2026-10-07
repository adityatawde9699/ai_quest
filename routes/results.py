from datetime import timezone

from flask import Blueprint, jsonify, request

from extensions import db
from models import FinalResult, Round, RoundSession, Score, Team, utcnow
from routes.common import admin_required, audit, emit_activity, iso_utc
from utils.scoring import leaderboard_rows

results_bp = Blueprint("results", __name__)


def _completed_at(team):
    sessions = [session for session in team.round_sessions if session.ended_at]
    values = [
        session.ended_at.replace(tzinfo=timezone.utc)
        if session.ended_at.tzinfo is None
        else session.ended_at.astimezone(timezone.utc)
        for session in sessions
    ]
    return max(values, default=None)


@results_bp.get("/api/results")
@admin_required
def get_results():
    return jsonify([
        {"rank": result.rank, "team_id": result.team.team_id,
         "team_name": result.team.team_name, "score": result.total_score,
         "time": result.total_time,
         "completed_at": iso_utc(result.completed_at),
         "locked": result.locked}
        for result in FinalResult.query.order_by(FinalResult.rank)
    ])


@results_bp.post("/api/results/generate")
@admin_required
def generate_results():
    from services.event import event_config
    from models import FinalAssignment
    event = event_config()
    if event.results_locked:
        return jsonify(error="Results are locked."), 409
    if FinalAssignment.query.filter_by(reviewed=False).first():
        return jsonify(error="Review all final assignments before generating results."), 409
    locked = FinalResult.query.filter_by(locked=True).first()
    if locked:
        return jsonify(error="Final results are locked and cannot be regenerated."), 409
    rounds = Round.query.order_by(Round.number).all()
    if len(rounds) != 3 or any(event_round.status != "ENDED" for event_round in rounds):
        return jsonify(error="All three rounds must be completed before generating results."), 409
    eligible_teams = Team.query.filter(
        Team.status.notin_(("DISQUALIFIED", "DISABLED"))
    ).all()
    final_round = Round.query.filter_by(number=3).first()
    if any(team.status != "COMPLETED" for team in eligible_teams):
        return jsonify(error="Every eligible team must be completed before generating results."), 409
    if any(
        not Score.query.filter_by(team_id=team.id, round_id=final_round.id).first()
        for team in eligible_teams
    ):
        return jsonify(error="Every eligible team needs a verified Round 3 score."), 409
    if any(
        not RoundSession.query.filter_by(
            team_id=team.id, round_id=event_round.id, status="COMPLETED"
        ).first()
        for team in eligible_teams
        for event_round in rounds
    ):
        return jsonify(error="Every eligible team must have completed all three round sessions."), 409
    results = []
    for row in leaderboard_rows():
        team = Team.query.filter_by(team_id=row["team_id"]).first()
        results.append((team, row["score"], row["time"], _completed_at(team)))
    results.sort(
        key=lambda item: (
            -item[1],
            item[2],
            item[3] or datetime_max(),
            item[0].team_id,
        )
    )
    event.results_published = False
    FinalResult.query.delete()
    generated_at = utcnow()
    for rank, (team, score, duration, completed_at) in enumerate(results, start=1):
        db.session.add(
            FinalResult(
                team_id=team.id,
                rank=rank,
                total_score=score,
                total_time=duration,
                completed_at=completed_at,
                generated_at=generated_at,
            )
        )
    audit("Final result generated", f"{len(results)} teams")
    db.session.commit()
    emit_activity("Final results generated", "results")
    return jsonify(get_result_rows()), 201


def datetime_max():
    from datetime import datetime, timezone

    return datetime.max.replace(tzinfo=timezone.utc)


def get_result_rows():
    return [
        {"rank": result.rank, "team_id": result.team.team_id,
         "team_name": result.team.team_name, "score": result.total_score,
         "time": result.total_time,
         "completed_at": iso_utc(result.completed_at),
         "locked": result.locked}
        for result in FinalResult.query.order_by(FinalResult.rank)
    ]


@results_bp.post("/api/results/lock")
@admin_required
def lock_results():
    results = FinalResult.query.order_by(FinalResult.rank).all()
    if not results:
        return jsonify(error="Generate results before locking them."), 409
    from services.event import event_config
    live = {r["team_id"]: r for r in leaderboard_rows()}
    if len(live) != len(results) or any(r.team.team_id not in live or (live[r.team.team_id]["score"] != r.total_score or live[r.team.team_id]["time"] != r.total_time or live[r.team.team_id]["rank"] != r.rank or live[r.team.team_id]["status"] != "COMPLETED") for r in results):
        return jsonify(error="Scores changed. Regenerate results before locking."), 409
    event_config().results_locked = True
    for result in results:
        result.locked = True
    audit("Final result locked", f"{len(results)} teams")
    db.session.commit()
    emit_activity("Final results locked", "results")
    return jsonify(ok=True)


@results_bp.post("/api/results/unlock")
@admin_required
def unlock_results():
    from flask_login import current_user

    if current_user.role != "super-admin":
        return jsonify(error="Only a super-admin can unlock final results."), 403
    from services.event import event_config
    reason = str((request.get_json(silent=True) or {}).get("reason", "")).strip()
    if not reason:
        return jsonify(error="Explain why results must be unlocked."), 400
    previous = get_result_rows()
    event = event_config()
    event.results_locked = False
    event.results_published = False
    results = FinalResult.query.filter_by(locked=True).all()
    for result in results:
        result.locked = False
    audit("RESULTS_UNLOCKED", f"{len(results)} teams", {"reason": reason[:1000], "before": previous})
    db.session.commit()
    return jsonify(ok=True)
