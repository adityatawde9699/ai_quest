"""Operational administration, judging, exports and test-only reset."""
import csv
from io import StringIO, BytesIO
from zipfile import ZipFile
from flask import Blueprint, current_app, jsonify, request, Response, send_file, render_template
from flask_login import current_user
from extensions import db
from models import (OfflineRound3, ActivityLog, Admin, Answer, Batch, Desktop, DesktopSession, FinalAnswer,
                    FinalAssignment, FinalResult, PasswordAttempt, QRChallenge, QRScanEvent,
                    Question, Quiz, QuizAttempt, QuizQuestion, Round, RoundSession, ScanLog,
                    Score, Team, TeamMember, utcnow)
from routes.common import admin_required, super_admin_required, audit, iso_utc, emit_activity
from services.event import EventError, event_config, set_score
from utils.qr_generator import render_qr, scan_url

operations_bp = Blueprint("operations", __name__)
KINDS = {"MCQ", "MISSING WORDS", "FILL IN THE BLANK", "TRUE/FALSE", "SHORT ANSWER", "NUMERICAL", "LOGICAL", "CODE OUTPUT", "AI/TECHNICAL"}
ROUND2_KINDS = {"MCQ", "MISSING WORDS", "FILL IN THE BLANK", "TRUE/FALSE"}


def data():
    value = request.get_json(silent=True) or {}
    if not isinstance(value, dict):
        raise EventError("Expected a JSON object.", 400)
    return value


def integer(value, low=0, high=100000):
    try:
        result = int(value)
    except (TypeError, ValueError):
        raise EventError("Enter a whole number.", 400)
    if not low <= result <= high:
        raise EventError(f"Value must be between {low} and {high}.", 400)
    return result


def unlocked():
    if event_config().results_locked:
        raise EventError("Results are locked. A super-admin must unlock with a reason.")


@operations_bp.route("/api/admin/event", methods=["GET", "PATCH"])
@admin_required
def event_settings():
    event = event_config()
    if request.method == "PATCH":
        if current_user.role != "super-admin":
            raise EventError("Super-admin access required.", 403)
        unlocked()
        values = data()
        for key in ("active", "leaderboard_visible"):
            if key in values:
                if not isinstance(values[key], bool):
                    raise EventError("Use a boolean value.", 400)
                setattr(event, key, values[key])
        if "final_question_count" in values:
            raise EventError("Round 3 questions are provided on paper; online question count is retired.", 400)
        if "round_1_points" in values:
            if ScanLog.query.first():
                raise EventError("Round 1 marks cannot change after scans exist.")
            event.round_1_points = integer(values["round_1_points"])
        if "round_3_destination" in values:
            event.round_3_destination = str(values["round_3_destination"])[:300]
        audit("ADMIN_ACTION", "Event configuration", {"fields": list(values)})
        db.session.commit()
    return jsonify(name=event.name, mode=event.mode, active=event.active,
                   round_1_points=event.round_1_points,
                   round_3_destination=event.round_3_destination, results_locked=event.results_locked,
                   results_published=event.results_published, leaderboard_visible=event.leaderboard_visible)


def configure_quiz(quiz, ids):
    if not isinstance(ids, list) or len(ids) != 10 or len({str(i) for i in ids}) != 10 or any(isinstance(i, (dict,list)) for i in ids):
        raise EventError("Select exactly ten different questions in order.", 400)
    questions = [db.session.get(Question, integer(pk, 1)) for pk in ids]
    if any(not q or q.round.number != 2 or not q.active or q.kind not in ROUND2_KINDS for q in questions):
        raise EventError("Use ten active Round 2 questions in a supported quiz format.", 400)
    QuizQuestion.query.filter_by(quiz_id=quiz.id).delete()
    db.session.flush()
    for position, question in enumerate(questions, 1):
        db.session.add(QuizQuestion(quiz_id=quiz.id, question_id=question.id, position=position))


@operations_bp.route("/api/admin/quizzes", methods=["GET", "POST"])
@admin_required
def quizzes():
    if request.method == "POST":
        values = data()
        title = str(values.get("title", "")).strip()
        if not title or len(title) > 120:
            raise EventError("Quiz title is required (120 characters maximum).", 400)
        quiz = Quiz(title=title)
        db.session.add(quiz)
        db.session.flush()
        configure_quiz(quiz, values.get("question_ids", []))
        audit("QUIZ_CREATED", title)
        db.session.commit()
        return jsonify(id=quiz.id), 201
    return jsonify([{"id": q.id, "title": q.title, "active": q.active,
                     "question_ids": [link.question_id for link in q.questions]} for q in Quiz.query.order_by(Quiz.id)])


@operations_bp.route("/api/admin/quizzes/<int:quiz_id>", methods=["PATCH", "DELETE"])
@admin_required
def edit_quiz(quiz_id):
    quiz = db.get_or_404(Quiz, quiz_id)
    if QuizAttempt.query.filter_by(quiz_id=quiz_id).first():
        raise EventError("A quiz with attempts cannot change.")
    if request.method == "DELETE":
        if QRChallenge.query.filter_by(quiz_id=quiz_id).first():
            raise EventError("Delete linked QR codes before deleting this question set.")
        audit("QUIZ_DELETED", quiz_id)
        db.session.delete(quiz)
        db.session.commit()
        return jsonify(ok=True)
    values = data()
    if "title" in values:
        title = str(values["title"]).strip()
        if not title or len(title) > 120:
            raise EventError("Question set title is required (120 characters maximum).", 400)
        quiz.title = title
    if "active" in values:
        if not isinstance(values["active"], bool):
            raise EventError("Use a boolean value.", 400)
        quiz.active = values["active"]
    if "question_ids" in values:
        configure_quiz(quiz, values["question_ids"])
    audit("QUIZ_UPDATED", quiz_id)
    db.session.commit()
    return jsonify(ok=True)


@operations_bp.route("/api/admin/round3", methods=["GET", "POST"])
@admin_required
def offline_round3():
    if request.method == "POST":
        unlocked()
        values = data()
        team = db.get_or_404(Team, integer(values.get("team_id"), 1))
        if values.get("password_qr_id") in (None, ""):
            raise EventError("Select a Round 3 QR to assign to this team.", 400)
        from routes.teams import _qr_batch_conflict, _set_round3_qr
        _set_round3_qr(team, values.get("password_qr_id"), values.get("max_points", 100))
        if _qr_batch_conflict(team, team.batch_id):
            raise EventError("This batch already has a team assigned that Round 3 QR.", 409)
        config = OfflineRound3.query.filter_by(team_id=team.id).first()
        if not config:
            raise EventError("Select a Round 3 QR to assign to this team.", 400)
        audit("OFFLINE_ROUND3_QR_ASSIGNED", team.team_id, {"qr_id": config.password_qr.qr_id})
        db.session.commit()
        return jsonify(id=config.id, password_qr_id=config.password_qr_id), 201
    return jsonify([dict(id=c.id, team_id=c.team_id, team=c.team.team_id,
                         password_qr_id=c.password_qr_id,
                         password_qr=c.password_qr.qr_id,
                         password_clue=c.password_qr.clue,
                         room=c.password_qr.room, max_points=c.max_points,
                         password_status=c.password_qr.status,
                         password_attempts=c.password_attempts, password_solved=c.password_solved,
                         started_at=iso_utc(c.started_at), sheet_path=c.sheet_path,
                         completed_at=next((iso_utc(s.ended_at) for s in c.team.round_sessions if s.round.number == 3 and s.status == "COMPLETED"), None),
                         sheet_received_at=iso_utc(c.sheet_received_at), submitted_at=iso_utc(c.submitted_at),
                         reviewed_at=iso_utc(c.reviewed_at), points=c.points, judging_reason=c.judging_reason)
                    for c in OfflineRound3.query.order_by(OfflineRound3.id)])


@operations_bp.patch("/api/admin/round3/<int:config_id>")
@admin_required
def edit_offline_round3(config_id):
    unlocked()
    config = db.get_or_404(OfflineRound3, config_id)
    if config.started_at or config.password_qr.scans:
        raise EventError("Riddles, password, room, and maximum marks cannot change after Round 3 entry.")
    values = data()
    for field, qr in (("password_clue", config.password_qr),):
        if field in values:
            value = str(values[field]).strip()
            if not value or len(value) > 2000:
                raise EventError("Enter a riddle of 1–2,000 characters.", 400)
            qr.clue = value
    if "password" in values:
        value = str(values["password"])
        if not value or len(value) > 300:
            raise EventError("Enter a password of 1–300 characters.", 400)
        config.password_qr.set_password(value)
        for linked_config in OfflineRound3.query.filter_by(password_qr_id=config.password_qr_id):
            linked_config.set_password(value)
    if "room" in values:
        room = str(values["room"]).strip()
        if len(room) > 120:
            raise EventError("Room must be 120 characters or fewer.", 400)
        config.password_qr.room = room
    if "max_points" in values:
        config.max_points = integer(values["max_points"])
    audit("OFFLINE_ROUND3_UPDATED", config.team.team_id, {"fields": list(values)})
    db.session.commit()
    return jsonify(ok=True)


@operations_bp.post("/api/admin/round3/<int:config_id>/<action>")
@admin_required
def offline_round3_action(config_id, action):
    from services.event import require_session, finish_round
    unlocked()
    config = db.get_or_404(OfflineRound3, config_id)
    team, values = config.team, data()
    if team.status in ("DISABLED", "DISQUALIFIED"):
        raise EventError("This team is not eligible.")
    if action in ("activate", "deactivate"):
        if action == "activate" and config.password_qr.round.status not in ("READY", "ACTIVE"):
            raise EventError("Open Round 3 before activating its QRs.")
        for qr in (config.password_qr,):
            qr.status = "ACTIVE" if action == "activate" else "INACTIVE"
            if action == "activate":
                qr.activated_at, qr.deactivated_at = utcnow(), None
            else:
                qr.deactivated_at = utcnow()
    elif action == "sheet":
        session = RoundSession.query.filter_by(team_id=team.id, round_id=config.password_qr.round_id).first()
        if not session or session.status != "COMPLETED":
            require_session(team, 3)
        if config.sheet_received_at:
            raise EventError("Sheet collection has already been recorded.")
        if values.get("path", "PASSWORD") != "PASSWORD":
            raise EventError("Sheets are handed out only after the correct password.", 400)
        if not config.password_solved:
            raise EventError("The team must solve the password before receiving a sheet.")
        config.sheet_path, config.sheet_received_at = "PASSWORD", utcnow()
    elif action == "submit":
        if not config.sheet_received_at or config.submitted_at:
            raise EventError("Record sheet collection first; submission can only be recorded once.")
        config.submitted_at = utcnow()
        session = RoundSession.query.filter_by(team_id=team.id, round_id=config.password_qr.round_id).first()
        if not session or session.status != "COMPLETED":
            finish_round(team, 3)
        from services.batches import mark_completed
        mark_completed(team)
    elif action == "review":
        if not config.submitted_at:
            raise EventError("Collect the completed answer sheet before judging.")
        reason = str(values.get("reason", "")).strip()
        if not reason or len(reason) > 1000:
            raise EventError("Enter a judging note of 1–1,000 characters.", 400)
        points = integer(values.get("points"), 0, config.max_points)
        audit("SCORE_UPDATED", team.team_id, {"round": 3, "before": config.points, "after": points, "reason": reason})
        config.points, config.judging_reason, config.reviewed_at = points, reason, utcnow()
        set_score(team.id, config.password_qr.round_id, points)
    else:
        raise EventError("Unknown Round 3 action.", 404)
    audit("OFFLINE_ROUND3_"+action.upper(), team.team_id, {"path": config.sheet_path})
    db.session.commit()
    emit_activity(f"{team.team_id} Round 3: {action}", "round")
    return jsonify(ok=True)


@operations_bp.route("/api/admin/desktops", methods=["GET", "POST"])
@operations_bp.patch("/api/admin/desktops/<int:desktop_id>")
@operations_bp.get("/api/admin/assignments")
@operations_bp.post("/api/admin/assignments/<int:assignment_id>/review")
@admin_required
def retired_desktops(**kwargs):
    raise EventError("Use offline Round 3 configuration and sheet judging.", 410)


@operations_bp.post("/api/admin/teams/<int:team_id>/score")
@admin_required
def manual_score(team_id):
    unlocked()
    team, values = db.get_or_404(Team,team_id), data()
    reason = str(values.get("reason", "")).strip()
    if not reason:
        raise EventError("A judging reason is required.",400)
    before = {"bonus":team.bonus,"penalty":team.penalty,"rounds":{str(s.round_id):s.points for s in team.scores}}
    if "bonus" in values:
        team.bonus = integer(values["bonus"])
    if "penalty" in values:
        team.penalty = integer(values["penalty"])
    if "round_id" in values:
        row = db.get_or_404(Round,integer(values["round_id"],1))
        if row.number == 3:
            raise EventError("Enter Round 3 marks through offline sheet review.")
        set_score(team.id,row.id,integer(values.get("points")))
    audit("SCORE_UPDATED",team.team_id,{"reason":reason[:1000],"before":before,"after":{k:v for k,v in values.items() if k in ("round_id","points","bonus","penalty")}})
    db.session.commit()
    return jsonify(ok=True)


@operations_bp.post("/api/admin/teams/<int:team_id>/advance")
@super_admin_required
def advance_team(team_id):
    unlocked()
    team, values = db.get_or_404(Team,team_id), data()
    number, reason = integer(values.get("round"),1,2), str(values.get("reason", "")).strip()
    if not reason:
        raise EventError("Explain the coordinator override.",400)
    if any(session.round.number > number for session in team.round_sessions):
        raise EventError("This team has already progressed beyond that round.")
    before = team.state
    for n in range(1,number+1):
        row = Round.query.filter_by(number=n).one()
        session = RoundSession.query.filter_by(team_id=team.id,round_id=row.id).first()
        if not session:
            session = RoundSession(team_id=team.id,round_id=row.id)
            db.session.add(session)
        session.status, session.ended_at = "COMPLETED",utcnow()
    team.state,team.status = f"ROUND_{number}_COMPLETED","ACTIVE"
    audit("ADMIN_ACTION",team.team_id,{"advance":number,"before":before,"reason":reason[:1000]})
    db.session.commit()
    return jsonify(ok=True)


@operations_bp.post("/api/results/publish")
@admin_required
def publish_results():
    event = event_config()
    if not event.results_locked or not FinalResult.query.first():
        raise EventError("Review, generate, and lock results before publication.")
    event.results_published = True
    audit("RESULTS_PUBLISHED",event.name)
    db.session.commit()
    emit_activity("Results published","results")
    return jsonify(ok=True)


@operations_bp.get("/api/admin/scans")
@admin_required
def scan_events():
    query = QRScanEvent.query
    if request.args.get("team_id"):
        query = query.filter_by(team_id=integer(request.args["team_id"],1))
    return jsonify([{"team":r.team.team_id if r.team else None,"qr":r.qr.qr_id if r.qr else None,
                     "status":r.status,"timestamp":iso_utc(r.timestamp),"ip_address":r.ip_address,
                     "user_agent":r.user_agent} for r in query.order_by(QRScanEvent.id.desc()).limit(1000)])


@operations_bp.get("/api/qrs/download")
@admin_required
def bulk_qr():
    output = BytesIO()
    with ZipFile(output,"w") as archive:
        for qr in QRChallenge.query.filter(QRChallenge.status!="ARCHIVED").order_by(QRChallenge.id):
            archive.writestr(f"{qr.qr_id}.png",render_qr(scan_url(qr.secure_token)).getvalue())
    output.seek(0)
    return send_file(output,mimetype="application/zip",download_name="quest-qrs.zip",as_attachment=True)


@operations_bp.get("/admin/qrs/print")
@admin_required
def print_qrs():
    return render_template("qr_sheet.html",qrs=QRChallenge.query.filter(QRChallenge.status!="ARCHIVED").order_by(QRChallenge.id))


def export_rows(kind):
    if kind=="teams":
        return [dict(team_id=t.team_id,name=t.team_name,batch=t.batch.number if t.batch else "",batch_status=t.batch.status if t.batch else "UNASSIGNED",members="; ".join(m.name for m in t.members),status=t.status,state=t.state) for t in Team.query.order_by(Team.id)]
    if kind=="scans":
        return [dict(team=r.team.team_id if r.team else "",qr=r.qr.qr_id if r.qr else "",round_id=r.round_id,timestamp=iso_utc(r.timestamp),status=r.status,ip=r.ip_address,user_agent=r.user_agent) for r in QRScanEvent.query.order_by(QRScanEvent.id)]
    if kind=="quiz-responses":
        return [dict(team=a.team.team_id,question=a.question_id,selected=a.selected_answer,timestamp=iso_utc(a.answer_time),points=a.points) for a in Answer.query.order_by(Answer.id)]
    if kind=="quiz-results":
        return [dict(team=db.session.get(Team,a.team_id).team_id,quiz=a.quiz_id,submitted_at=iso_utc(a.submitted_at),score=a.score) for a in QuizAttempt.query.order_by(QuizAttempt.id)]
    if kind=="round3-sheets":
        return [dict(team=c.team.team_id, path=c.sheet_path, received_at=iso_utc(c.sheet_received_at),
                     submitted_at=iso_utc(c.submitted_at), reviewed_at=iso_utc(c.reviewed_at),
                     points=c.points, maximum=c.max_points, judging_reason=c.judging_reason)
                for c in OfflineRound3.query.order_by(OfflineRound3.id)]
    if kind=="final-answers":
        return [dict(team=db.session.get(Team,db.session.get(FinalAssignment,a.assignment_id).team_id).team_id,question=a.question_id,answer=a.answer,timestamp=iso_utc(a.timestamp),points=a.points) for a in FinalAnswer.query.order_by(FinalAnswer.id)]
    if kind in ("scores","leaderboard"):
        from utils.scoring import leaderboard_rows
        teams = {team.team_id: team for team in Team.query}
        return [{**row, "batch": teams[row["team_id"]].batch.number if teams[row["team_id"]].batch else ""}
                for row in leaderboard_rows()]
    if kind=="logs":
        return [dict(id=r.id,admin_id=r.admin_id,team_id=r.team_id,action=r.action,target=r.target,timestamp=iso_utc(r.timestamp),metadata=r.metadata_json,request_id=r.request_id) for r in ActivityLog.query.order_by(ActivityLog.id)]
    raise EventError("Unknown export.",404)


@operations_bp.get("/api/admin/export/<kind>.csv")
@admin_required
def export(kind):
    rows, output = export_rows(kind), StringIO()
    writer = csv.DictWriter(output,fieldnames=list(rows[0]) if rows else ["No records"])
    writer.writeheader()
    for row in rows:
        writer.writerow({k:"'"+str(v) if str(v).startswith(("=","+","-","@","\t","\r")) else v for k,v in row.items()})
    return Response(output.getvalue(),mimetype="text/csv",headers={"Content-Disposition":f'attachment; filename="{kind}.csv"'})


@operations_bp.route("/api/admin/accounts",methods=["GET","POST"])
@super_admin_required
def accounts():
    if request.method=="POST":
        values = data()
        name,password,role = str(values.get("username", "")).strip(),str(values.get("password", "")),values.get("role","admin")
        if not name or len(name)>80 or len(password)<12 or role not in ("admin","super-admin"):
            raise EventError("Enter a username, password of at least 12 characters, and valid role.",400)
        if Admin.query.filter_by(username=name).first():
            raise EventError("Username already exists.")
        admin = Admin(username=name,role=role)
        admin.set_password(password)
        db.session.add(admin)
        audit("ADMIN_CREATED",name,{"role":role})
        db.session.commit()
        return jsonify(id=admin.id),201
    return jsonify([{"id":a.id,"username":a.username,"role":a.role,"active":a.active} for a in Admin.query.order_by(Admin.id)])


@operations_bp.post("/api/admin/test-reset")
@super_admin_required
def reset_test():
    event = event_config()
    if current_app.config["APP_ENV"]=="production" or current_app.config["EVENT_MODE"]!="TEST" or event.mode!="TEST":
        raise EventError("Reset is available only in a separate TEST database.",403)
    if event.active or event.results_locked or data().get("confirmation")!="RESET TEST PROGRESS":
        raise EventError("Stop the TEST event, unlock results, and type RESET TEST PROGRESS.")
    for model in (OfflineRound3,PasswordAttempt,FinalAnswer,FinalAssignment,DesktopSession,QuizAttempt,Answer,ScanLog,
                  QRScanEvent,FinalResult,Score,RoundSession,ActivityLog,TeamMember,Team,Batch):
        model.query.delete(synchronize_session=False)
    for row in Round.query:
        row.status = "READY" if row.number==1 else "LOCKED"
        row.started_at = row.ended_at = None
    event.results_published = False
    audit("TEST_RESET",event.name)
    db.session.commit()
    return jsonify(ok=True,message="Test progress cleared; content, stations, QR codes and administrators retained.")


@operations_bp.patch("/api/admin/accounts/<int:admin_id>")
@super_admin_required
def update_account(admin_id):
    account = db.get_or_404(Admin, admin_id)
    values = data()
    if account.id == current_user.id:
        raise EventError("Use another super-admin to change your account.")
    if "role" in values:
        if values["role"] not in ("admin", "super-admin"):
            raise EventError("Invalid administrator role.", 400)
        account.role = values["role"]
    if "active" in values:
        if not isinstance(values["active"], bool):
            raise EventError("Use a boolean value.", 400)
        account.active = values["active"]
    if "password" in values:
        password = str(values["password"])
        if not 12 <= len(password) <= 300:
            raise EventError("Use a password of 12–300 characters.", 400)
        account.set_password(password)
    audit("ADMIN_UPDATED", account.username, {"fields": list(values)})
    db.session.commit()
    from extensions import socketio
    for sid, _ in list(socketio.server.manager.get_participants("/", f"admin:{account.id}")):
        socketio.server.disconnect(sid, namespace="/")
    return jsonify(ok=True)
