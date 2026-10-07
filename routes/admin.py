from datetime import timezone

from flask import Blueprint, abort, jsonify, render_template
from flask_login import current_user, login_required
from sqlalchemy import func

from extensions import db
from models import ActivityLog, Answer, Batch, QRChallenge, Round, RoundSession, ScanLog, Score, Team
from routes.common import admin_required, iso_utc
from utils.scoring import leaderboard_rows

admin_bp = Blueprint("admin", __name__)


@admin_bp.route("/admin")
@login_required
def dashboard():
    if getattr(current_user, "role", "") not in ("admin", "super-admin"):
        return abort(403)
    return render_template("admin_dashboard.html", admin=current_user)


def iso(value):
    return iso_utc(value)


@admin_bp.get("/api/overview")
@admin_required
def overview():
    active_round = Round.query.filter_by(status="ACTIVE").first()
    return jsonify(
        total_teams=Team.query.count(),
        batches=[{"number": b.number, "status": b.status, "triggered": bool(b.triggered_at)} for b in Batch.query.order_by(Batch.number)],
        active_teams=Team.query.filter_by(status="ACTIVE").count(),
        completed_teams=Team.query.filter_by(status="COMPLETED").count(),
        current_round=active_round.name if active_round else "Not started",
        total_scans=ScanLog.query.count(),
        teams_by_round={str(n): RoundSession.query.join(Round).filter(Round.number==n, RoundSession.status=="ACTIVE").count() for n in (1,2,3)},
        completed_rounds=Round.query.filter_by(status="ENDED").count(),
        round_scores={
            str(round_number): int(points or 0)
            for round_number, points in db.session.query(
                Round.number, func.coalesce(func.sum(Score.points), 0)
            ).outerjoin(Score, Score.round_id == Round.id).group_by(Round.id).all()
        },
        leaderboard=leaderboard_rows()[:10],
        rounds=[{"id": r.id, "number": r.number, "name": r.name, "status": r.status} for r in Round.query.order_by(Round.number)],
        activity=[
            {"action": log.action, "target": log.target, "timestamp": iso(log.timestamp)}
            for log in ActivityLog.query.order_by(ActivityLog.timestamp.desc()).limit(12)
        ],
    )


@admin_bp.get("/api/admin/profile")
@admin_required
def profile():
    return jsonify(username=current_user.username, role=current_user.role)
