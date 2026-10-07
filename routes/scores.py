from flask import Blueprint, jsonify
from flask_login import current_user

from models import ActivityLog, Answer, QRChallenge, Round, RoundSession, ScanLog, Score, Team
from routes.admin import iso
from routes.common import admin_required
from utils.scoring import leaderboard_rows

scores_bp = Blueprint("scores", __name__)


@scores_bp.get("/api/leaderboard")
def live_leaderboard():
    if not current_user.is_authenticated:
        return jsonify(error="Login required."), 401
    from services.event import event_config
    if getattr(current_user, "role", "") == "team":
        event = event_config()
        if current_user.status in ("DISABLED", "DISQUALIFIED") or not event.results_published or not event.leaderboard_visible:
            return jsonify([])
        from routes.results import get_result_rows
        return jsonify(get_result_rows())
    return jsonify(leaderboard_rows())


@scores_bp.get("/api/admin/scores")
@admin_required
def score_details():
    return jsonify([
        {"team_id": row.team.team_id, "team_name": row.team.team_name,
         "round": row.round.number, "points": row.points, "updated_at": iso(row.updated_at)}
        for row in Score.query.join(Team).order_by(Team.team_id, Score.round_id)
    ])


@scores_bp.get("/api/admin/activity")
@admin_required
def activity_log():
    return jsonify([
        {"action": row.action, "target": row.target, "timestamp": iso(row.timestamp),
         "metadata": row.metadata_json}
        for row in ActivityLog.query.order_by(ActivityLog.timestamp.desc()).limit(300)
    ])
