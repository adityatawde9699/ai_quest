"""Operational administration, judging, exports and test-only reset."""
import csv
from io import StringIO, BytesIO
from zipfile import ZipFile
from flask import Blueprint, current_app, jsonify, request, Response, send_file, render_template
from flask_login import current_user
from extensions import db
from models import (ActivityLog, Admin, Answer, Batch, Desktop, DesktopSession, FinalAnswer,
                    FinalAssignment, FinalResult, PasswordAttempt, QRChallenge, QRScanEvent,
                    Question, Quiz, QuizAttempt, QuizQuestion, Round, RoundSession, ScanLog,
                    Score, Team, TeamMember, utcnow)
from routes.common import admin_required, super_admin_required, audit, iso_utc, emit_activity
from services.event import EventError, event_config, set_score
from utils.qr_generator import render_qr, scan_url
from utils.security import new_qr_token

operations_bp = Blueprint("operations", __name__)
KINDS = {"MCQ", "TRUE/FALSE", "SHORT ANSWER", "NUMERICAL", "LOGICAL", "CODE OUTPUT", "AI/TECHNICAL"}


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
            if FinalAssignment.query.first():
                raise EventError("Question count cannot change after assignments exist.")
            event.final_question_count = integer(values["final_question_count"], 1, 100)
        if "round_1_points" in values:
            if ScanLog.query.first():
                raise EventError("Round 1 marks cannot change after scans exist.")
            event.round_1_points = integer(values["round_1_points"])
        if "round_3_destination" in values:
            event.round_3_destination = str(values["round_3_destination"])[:300]
        audit("ADMIN_ACTION", "Event configuration", {"fields": list(values)})
        db.session.commit()
    return jsonify(name=event.name, mode=event.mode, active=event.active,
                   final_question_count=event.final_question_count, round_1_points=event.round_1_points,
                   round_3_destination=event.round_3_destination, results_locked=event.results_locked,
                   results_published=event.results_published, leaderboard_visible=event.leaderboard_visible)


def configure_quiz(quiz, ids):
    if not isinstance(ids, list) or len(ids) != 10 or len({str(i) for i in ids}) != 10 or any(isinstance(i, (dict,list)) for i in ids):
        raise EventError("Select exactly ten different questions in order.", 400)
    questions = [db.session.get(Question, integer(pk, 1)) for pk in ids]
    if any(not q or q.round.number != 2 or not q.active for q in questions):
        raise EventError("Use ten active Round 2 questions.", 400)
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


@operations_bp.route("/api/admin/desktops", methods=["GET", "POST"])
@admin_required
def desktops():
    if request.method == "POST":
        values = data()
        name, password, clue = str(values.get("name", "")).strip(), str(values.get("password", "")), str(values.get("clue", "")).strip()
        if not name or len(name)>80 or not password or len(password)>300 or not clue or len(clue)>2000:
            raise EventError("Enter a station name, riddle, and password within the field limits.", 400)
        if Desktop.query.filter_by(name=name).first():
            raise EventError("Desktop name already exists.")
        qr = None
        if values.get("qr_id"):
            qr = db.session.get(QRChallenge, integer(values["qr_id"], 1))
            if not qr or qr.round.number != 3 or qr.status == "ARCHIVED" or Desktop.query.filter_by(qr_id=qr.id).first():
                raise EventError("Select an available Round 3 QR.", 400)
            if qr.scans:
                raise EventError("A scanned QR cannot be assigned to a new desktop.")
            qr.room = name
            qr.status = "ACTIVE"
        else:
            qr = QRChallenge(qr_id="DESKTOP-"+new_qr_token()[:12], secure_token=new_qr_token(),
                             round_id=Round.query.filter_by(number=3).one().id,
                             title=name, clue=clue, room=name, status="ACTIVE")
            db.session.add(qr)
        db.session.flush()
        desktop = Desktop(name=name, qr_id=qr.id)
        desktop.set_password(password)
        db.session.add(desktop)
        audit("DESKTOP_CREATED", name)
        db.session.commit()
        return jsonify(id=desktop.id, qr_id=qr.id), 201
    rows = []
    for desktop in Desktop.query.order_by(Desktop.name):
        session = DesktopSession.query.filter_by(desktop_id=desktop.id, completed_at=None).first()
        rows.append({"id": desktop.id, "name": desktop.name, "active": desktop.active, "qr_id": desktop.qr_id,
                     "clue": desktop.qr.clue, "team": session.team.team_id if session else None,
                     "attempts": session.password_attempts if session else 0,
                     "status": "Final Challenge" if session and session.final_challenge_unlocked else "Password Challenge" if session else "Available"})
    return jsonify(rows)


@operations_bp.patch("/api/admin/desktops/<int:desktop_id>")
@admin_required
def edit_desktop(desktop_id):
    desktop = db.get_or_404(Desktop, desktop_id)
    values = data()
    if DesktopSession.query.filter_by(desktop_id=desktop_id, completed_at=None).first():
        raise EventError("Do not modify an occupied desktop.")
    if "active" in values:
        if not isinstance(values["active"], bool):
            raise EventError("Use a boolean value.", 400)
        desktop.active = values["active"]
        desktop.qr.status = "ACTIVE" if desktop.active else "INACTIVE"
    if "password" in values:
        password = str(values["password"])
        if not password or len(password)>300:
            raise EventError("Enter a password of 1–300 characters.", 400)
        desktop.set_password(password)
    if "clue" in values:
        desktop.qr.clue = str(values["clue"])[:2000]
    audit("DESKTOP_UPDATED", desktop.name, {"fields": list(values)})
    db.session.commit()
    return jsonify(ok=True)


@operations_bp.get("/api/admin/assignments")
@admin_required
def assignments():
    rows = []
    for assignment in FinalAssignment.query.order_by(FinalAssignment.id):
        answers = {a.question_id: a for a in FinalAnswer.query.filter_by(assignment_id=assignment.id)}
        rows.append({"id": assignment.id, "team": db.session.get(Team,assignment.team_id).team_id,
                     "submitted_at": iso_utc(assignment.submitted_at), "reviewed": assignment.reviewed,
                     "questions": [{**q, "answer": answers[q["id"]].answer if q["id"] in answers else "",
                                    "awarded": answers[q["id"]].points if q["id"] in answers else None} for q in assignment.questions]})
    return jsonify(rows)


@operations_bp.post("/api/admin/assignments/<int:assignment_id>/review")
@admin_required
def review_final(assignment_id):
    unlocked()
    assignment = db.get_or_404(FinalAssignment, assignment_id)
    if not assignment.submitted_at:
        raise EventError("Wait for final submission before judging.")
    points = data().get("points", {})
    answers = {a.question_id: a for a in FinalAnswer.query.filter_by(assignment_id=assignment.id)}
    before = {str(pk): a.points for pk,a in answers.items()}
    for q in assignment.questions:
        if str(q["id"]) in points:
            answers[q["id"]].points = integer(points[str(q["id"])],0,q["points"])
        if answers[q["id"]].points is None:
            raise EventError("Enter marks for every answer requiring review.",400)
    assignment.reviewed = True
    set_score(assignment.team_id,Round.query.filter_by(number=3).one().id,sum(a.points for a in answers.values()))
    audit("SCORE_UPDATED",db.session.get(Team,assignment.team_id).team_id,
          {"before":before,"after":{str(pk):a.points for pk,a in answers.items()}})
    db.session.commit()
    return jsonify(ok=True)


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
    for model in (PasswordAttempt,FinalAnswer,FinalAssignment,DesktopSession,QuizAttempt,Answer,ScanLog,
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
