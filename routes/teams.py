from datetime import timezone

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func
from sqlalchemy.orm import selectinload

from extensions import db
from models import (Answer, Batch, DesktopSession, FinalAssignment, FinalResult,
                    QRScanEvent, QuizAttempt, Round, RoundSession, ScanLog, Score,
                    Team, TeamMember, utcnow)
from routes.common import admin_required, audit, emit_activity, emit_leaderboard, iso_utc, team_required
from utils.security import new_team_pin

teams_bp = Blueprint("teams", __name__)
TEAM_STATUSES = {"READY", "ACTIVE", "COMPLETED", "DISQUALIFIED", "DISABLED"}


def _batch_position(values):
    value = values.get("batch_position")
    if value in (None, ""):
        return None
    if isinstance(value, bool) or not str(value).isdigit() or int(value) < 1:
        from services.event import EventError
        raise EventError("Batch position must be a positive whole number.", 400)
    return int(value)


def _team_payload(team):
    return {
        "id": team.id,
        "team_id": team.team_id,
        "team_name": team.team_name,
        "member_1": team.member_1,
        "member_2": team.member_2,
        "member_3": team.member_3,
        "status": team.status,
        "batch_id": team.batch_id,
        "batch_number": team.batch.number if team.batch else None,
        "batch_status": team.batch.status if team.batch else "UNASSIGNED",
        "batch_position": team.batch_position,
        "created_at": iso_utc(team.created_at),
        "state": team.state,
        "assigned_qr_id": team.assigned_qr_id,
        "bonus": team.bonus, "penalty": team.penalty,
        "score": sum(score.points for score in team.scores) + team.bonus - team.penalty,
    }


def _next_team_id():
    teams = Team.query.order_by(Team.id.desc()).all()
    used = {team.team_id for team in teams}
    number = 1
    while f"AIQ-{number:03d}" in used:
        number += 1
    return f"AIQ-{number:03d}"


@teams_bp.get("/team")
@login_required
def team_dashboard():
    if getattr(current_user, "role", "") != "team":
        return redirect(url_for("admin.dashboard"))
    return render_template("team_dashboard.html")


@teams_bp.get("/scan/<token>")
def open_scanned_qr(token):
    if getattr(current_user, "role", "") == "team":
        return redirect(url_for("teams.team_dashboard", scan=token))
    from models import QRChallenge
    from routes.quest import record_scan
    record_scan(QRChallenge.query.filter_by(secure_token=token).first(), None, "UNAUTHORIZED")
    db.session.commit()
    return redirect(url_for("auth.team_login", scan=token))


@teams_bp.get("/api/teams")
@admin_required
def list_teams():
    term = request.args.get("q", "").strip()
    query = Team.query
    if term:
        like = f"%{term}%"
        query = query.filter(db.or_(Team.team_id.ilike(like), Team.team_name.ilike(like)))
    teams = query.options(selectinload(Team.batch), selectinload(Team.scores)).order_by(Team.id).all()
    return jsonify([_team_payload(team) for team in teams])


@teams_bp.post("/api/teams")
@admin_required
def create_team():
    data = request.get_json(silent=True) or request.form
    name = str(data.get("team_name", "")).strip()
    if not name or len(name) > 120:
        return jsonify(error="Team name is required (120 characters maximum)."), 400
    pin = str(data.get("login_pin", "")).strip() or new_team_pin()
    if not pin.isdigit() or not 4 <= len(pin) <= 12:
        return jsonify(error="PIN must contain 4 to 12 digits."), 400
    team = Team(
        team_id=_next_team_id(),
        team_name=name,
        member_1=str(data.get("member_1", "")).strip()[:100],
        member_2=str(data.get("member_2", "")).strip()[:100],
        member_3=str(data.get("member_3", "")).strip()[:100],
    )
    if not team.member_1:
        return jsonify(error="Enter one to three members, starting with Member 1."), 400
    if data.get("assigned_qr_id"):
        from models import QRChallenge
        from routes.operations import integer
        qr = db.session.get(QRChallenge, integer(data["assigned_qr_id"], 1))
        if not qr or qr.round.number != 1:
            return jsonify(error="Assign a valid Round 1 QR."), 400
        team.assigned_qr_id = qr.id
    team.set_pin(pin)
    team.members = [
        TeamMember(name=value, position=position)
        for position, value in enumerate((team.member_1, team.member_2, team.member_3), start=1)
        if value
    ]
    db.session.add(team)
    db.session.flush()
    from services.batches import assign
    batch = db.session.get(Batch, int(data["batch_id"])) if data.get("batch_id") else None
    if data.get("batch_id") and not batch:
        return jsonify(error="Batch not found."), 404
    assign(team, batch, _batch_position(data))
    audit("Team created", team.team_id)
    db.session.commit()
    emit_activity(f"{team.team_id} team created", "team")
    emit_leaderboard()
    return jsonify(team=_team_payload(team), login_pin=pin), 201


@teams_bp.route("/api/teams/<int:team_pk>", methods=["PUT", "DELETE"])
@admin_required
def update_or_delete_team(team_pk):
    team = db.session.get(Team, team_pk)
    if not team:
        return jsonify(error="Team not found."), 404
    from services.event import event_config
    if event_config().results_locked:
        return jsonify(error="Results are locked."), 409
    if request.method == "DELETE":
        if request.args.get("permanent", "").lower() == "true":
            if current_user.role != "super-admin":
                return jsonify(error="Super-admin access is required to permanently delete a team."), 403
            progress_models = (RoundSession, ScanLog, QRScanEvent, Answer, QuizAttempt,
                               DesktopSession, FinalAssignment, Score, FinalResult)
            if any(model.query.filter_by(team_id=team.id).first() for model in progress_models):
                return jsonify(error="This team has recorded activity or results. Archive it to preserve its history."), 409
            audit("TEAM_PERMANENTLY_DELETED", team.team_id)
            db.session.delete(team)
            db.session.commit()
            emit_activity(f"{team.team_id} permanently deleted", "team")
            emit_leaderboard()
            return jsonify(ok=True, deleted=True)
        if FinalResult.query.filter_by(team_id=team.id).first():
            return jsonify(error="Teams included in generated results cannot be deleted."), 409
        audit("TEAM_DISABLED", team.team_id, {"reason": "archived"})
        team.status = "DISABLED"
        from services.batches import mark_completed
        mark_completed(team)
        db.session.commit()
        emit_leaderboard()
        return jsonify(ok=True)
    data = request.get_json(silent=True) or {}
    if any(result.locked for result in FinalResult.query.filter_by(team_id=team.id).all()):
        return jsonify(error="A team in locked results cannot be edited."), 409
    if "team_name" in data:
        name = str(data["team_name"]).strip()
        if not name or len(name) > 120:
            return jsonify(error="Team name is required (120 characters maximum)."), 400
        team.team_name = name
    for field in ("member_1", "member_2", "member_3"):
        if field in data:
            setattr(team, field, str(data[field]).strip()[:100])
    if not team.member_1:
        return jsonify(error="At least Member 1 is required."), 400
    TeamMember.query.filter_by(team_id=team.id).delete(synchronize_session=False)
    db.session.flush()
    for position, value in enumerate((team.member_1, team.member_2, team.member_3), 1):
        if value:
            db.session.add(TeamMember(team_id=team.id, name=value, position=position))
    if "assigned_qr_id" in data:
        from models import QRChallenge
        qr = db.session.get(QRChallenge, data["assigned_qr_id"])
        if not qr or qr.round.number != 1 or team.round_sessions:
            return jsonify(error="Assign a Round 1 QR before the team starts."), 409
        team.assigned_qr_id = qr.id
    if "status" in data:
        status = str(data["status"]).upper()
        if status not in TEAM_STATUSES:
            return jsonify(error="Invalid team status."), 400
        if status in ("ACTIVE", "COMPLETED") and status != team.status:
            return jsonify(error="Progress is derived from challenge records. Use audited advance for exceptions."), 409
        if status == "READY" and team.status in ("DISABLED", "DISQUALIFIED") and team.batch:
            from services.batches import active_count
            if team.batch.status == "COMPLETED":
                return jsonify(error="A completed batch cannot be reopened through team editing."), 409
            if active_count(team.batch, exclude=team.id) >= team.batch.capacity:
                if data.get("batch_override") is not True:
                    return jsonify(error="Batch is full. Reassign this team or request a super-admin override."), 409
                if current_user.role != "super-admin":
                    return jsonify(error="Super-admin override required."), 403
                audit("BATCH_CAPACITY_OVERRIDDEN", team.team_id, {"batch": team.batch.number})
        team.status = status
        if status == "DISQUALIFIED":
            team.state = "DISQUALIFIED"
        elif status == "READY" and team.state == "DISQUALIFIED" and not team.round_sessions:
            team.state = "REGISTERED"
    if "batch_id" in data or "batch_position" in data:
        from services.batches import assign
        batch = db.session.get(Batch, int(data["batch_id"])) if data.get("batch_id") else team.batch
        if not batch:
            return jsonify(error="Batch not found."), 404
        assign(team, batch, _batch_position(data))
    audit("Team edited", team.team_id)
    from services.batches import mark_completed
    mark_completed(team)
    if team.batch:
        from services.batches import release_if_predecessor_triggered
        release_if_predecessor_triggered(team.batch)
    db.session.commit()
    emit_leaderboard()
    return jsonify(team=_team_payload(team))


@teams_bp.post("/api/teams/<int:team_pk>/reset-pin")
@admin_required
def reset_pin(team_pk):
    team = db.session.get(Team, team_pk)
    if not team:
        return jsonify(error="Team not found."), 404
    pin = new_team_pin()
    team.set_pin(pin)
    audit("Team PIN reset", team.team_id)
    db.session.commit()
    return jsonify(team_id=team.team_id, login_pin=pin)


@teams_bp.get("/api/teams/<int:team_pk>/timeline")
@admin_required
def team_timeline(team_pk):
    team = db.session.get(Team, team_pk)
    if not team:
        return jsonify(error="Team not found."), 404
    events = []
    if team.batch and team.batch.released_at:
        events.append({"at": team.batch.released_at, "label": f"Batch {team.batch.number} released"})
    if team.batch and team.batch.triggered_at:
        events.append({"at": team.batch.triggered_at, "label": f"Batch {team.batch.number} triggered next release"})
    for session in RoundSession.query.filter_by(team_id=team.id).all():
        events.append({"at": session.started_at, "label": f"Round {session.round.number} started"})
        if session.ended_at:
            events.append({"at": session.ended_at, "label": f"Round {session.round.number} completed"})
    for scan in ScanLog.query.filter_by(team_id=team.id).all():
        events.append({"at": scan.scan_time, "label": f"{scan.challenge.qr_id} scanned"})
        if scan.answer_time:
            events.append({"at": scan.answer_time, "label": f"{scan.answer_status.title()} answer · {scan.points} pts"})
    for answer in Answer.query.filter_by(team_id=team.id).all():
        if answer.answer_time:
            events.append({"at": answer.answer_time, "label": f"Round {answer.question.round.number} quiz answer · {answer.points} pts"})
    from models import ActivityLog, QRScanEvent
    for entry in ActivityLog.query.filter(db.or_(ActivityLog.team_id == team.id, ActivityLog.target == team.team_id)):
        events.append({"at": entry.timestamp, "label": entry.action})
    for entry in QRScanEvent.query.filter_by(team_id=team.id):
        events.append({"at": entry.timestamp, "label": f"{entry.qr.qr_id if entry.qr else 'Unknown QR'} — {entry.status}"})
    events.sort(key=lambda event: iso_utc(event["at"]))
    return jsonify(team=_team_payload(team),
        rounds=[{"number": s.round.number, "status": s.status, "started_at": iso_utc(s.started_at), "ended_at": iso_utc(s.ended_at)} for s in team.round_sessions],
        scores={str(s.round.number): s.points for s in team.scores}, timeline=[
        {"at": (event["at"].replace(tzinfo=timezone.utc) if event["at"].tzinfo is None else event["at"].astimezone(timezone.utc)).isoformat(), "label": event["label"]}
        for event in events
    ])


@teams_bp.get("/api/team/dashboard")
@team_required
def team_summary():
    from services.event import event_config
    from models import DesktopSession, QRChallenge
    team = current_user
    event = event_config()
    sessions = team.round_sessions
    session = next((s for s in sessions if s.status == "ACTIVE"), None)
    next_number = max((s.round.number for s in sessions if s.status == "COMPLETED"), default=0) + 1
    event_round = session.round if session else Round.query.filter_by(number=next_number).first()
    payload = _team_payload(team)
    for key in ("score", "bonus", "penalty"):
        payload.pop(key, None)
    scans = ScanLog.query.filter_by(team_id=team.id).order_by(ScanLog.scan_time).all()
    desktop = DesktopSession.query.filter_by(team_id=team.id).first()
    return jsonify(team=payload, current_round=event_round.name if event_round else "Quest complete",
        round_id=event_round.id if event_round else None, round_number=event_round.number if event_round else None,
        round_status=event_round.status if event_round and event.active else "LOCKED",
        round_started_at=iso_utc(session.started_at) if session else None, session_active=bool(session),
        score=sum(s.points for s in team.scores)+team.bonus-team.penalty if event.results_published else None,
        results_published=event.results_published,
        clue=next((s.challenge.clue or (s.challenge.question.prompt if s.challenge.question else "") for s in scans if s.challenge.round.number == 1), None),
        destination=event.round_3_destination if team.state in ("ROUND_2_COMPLETED", "ROUND_3_ACTIVE", "PASSWORD_CHALLENGE", "FINAL_CHALLENGE") else None,
        desktop_id=desktop.desktop_id if desktop else None)


@teams_bp.get("/api/team/rounds")
@team_required
def team_rounds():
    return jsonify([
        {"number": event_round.number, "name": event_round.name, "status": event_round.status}
        for event_round in Round.query.order_by(Round.number)
    ])


@teams_bp.post("/api/team/rounds/<int:round_id>/start")
@team_required
def start_team_round(round_id):
    from services.event import start_round
    event_round = db.session.get(Round, round_id)
    if not event_round or event_round.number != 1:
        return jsonify(error="Scan the destination or desktop QR to start this round."), 409
    session = start_round(current_user, 1)
    db.session.commit()
    emit_activity(f"{current_user.team_id} started Round 1", "round")
    return jsonify(started_at=iso_utc(session.started_at))
