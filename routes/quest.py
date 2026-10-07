"""Participant challenge routes; all progress is derived from committed records."""
from datetime import timezone

from flask import Blueprint, jsonify, request, render_template
from flask_login import current_user

from extensions import db
from models import (Answer, Desktop, DesktopSession, FinalAnswer, QRChallenge, QRScanEvent,
                    QuizAttempt, ScanLog, Round, RoundSession, utcnow)
from routes.common import audit, emit_activity, iso_utc, team_required
from services.event import (EventError, active_round, event_config, final_assignment,
                            finish_round, password_attempt, public_questions,
                            require_session, set_score, snapshot, start_round,
                            automatic_points)

quest_bp = Blueprint("quest", __name__)


def record_scan(challenge, team, status):
    db.session.add(QRScanEvent(team_id=team.id if team else None,
                              qr_id=challenge.id if challenge else None,
                              round_id=challenge.round_id if challenge else None,
                              status=status, ip_address=request.remote_addr or "",
                              user_agent=request.headers.get("User-Agent", "")[:300]))
    audit("QR_SCANNED" if status == "VALID" else "QR_REJECTED",
          team.team_id if team else "unauthenticated", {"status": status, "qr": challenge.qr_id if challenge else None})


@quest_bp.post("/api/team/scan")
def scan_qr():
    token = str((request.get_json(silent=True) or {}).get("token", ""))[:200]
    challenge = QRChallenge.query.filter_by(secure_token=token).first()
    team = current_user if current_user.is_authenticated and getattr(current_user, "role", "") == "team" else None
    status, message = "VALID", "QR scan recorded."
    if not team or team.status in ("DISABLED", "DISQUALIFIED"):
        status, message = "UNAUTHORIZED", "Team login required."
    elif not challenge:
        status, message = "INVALID", "This QR code is not recognized. Contact a coordinator."
    elif challenge.expires_at and utcnow() > challenge.expires_at.replace(tzinfo=timezone.utc):
        status, message = "EXPIRED", "QR EXPIRED — This challenge is no longer available."
    elif challenge.status != "ACTIVE":
        status, message = "INACTIVE", "This QR code is not active. Contact a coordinator."
    elif ScanLog.query.filter_by(team_id=team.id, qr_id=challenge.id).first():
        status, message = "ALREADY_SCANNED", "Your team already scanned this QR. Your progress is saved on the dashboard."
    else:
        number = challenge.round.number
        try:
            if number == 1:
                require_session(team, 1)
                if team.assigned_qr_id != challenge.id:
                    raise EventError("Scan the QR number on your assigned envelope.")
            elif number == 2:
                active_round(2)
                if team.state not in ("ROUND_1_COMPLETED", "ROUND_2_ACTIVE"):
                    raise EventError("Complete Round 1 first.")
                initial = ScanLog.query.join(QRChallenge).join(Round).filter(ScanLog.team_id == team.id, Round.number == 1).first()
                if initial and initial.challenge.room and challenge.room != initial.challenge.room:
                    raise EventError("This is not your Round 2 destination QR.")
                if not challenge.quiz_id:
                    # Round 2 QR selects a quiz through its linked question.
                    raise EventError("This quiz QR is not configured. Contact the coordinator.")
            else:
                active_round(3)
                if team.state not in ("ROUND_2_COMPLETED", "ROUND_3_ACTIVE", "PASSWORD_CHALLENGE", "FINAL_CHALLENGE"):
                    raise EventError("Complete Round 2 first.")
                if not Desktop.query.filter_by(qr_id=challenge.id, active=True).first():
                    raise EventError("This desktop is not available.")
        except EventError as error:
            status, message = "WRONG_ROUND", error.message
    record_scan(challenge, team, status)
    if status != "VALID":
        db.session.commit()
        return jsonify(error=message, status=status), 403 if status == "UNAUTHORIZED" else 409 if challenge else 404
    number = challenge.round.number
    released_batch = None
    try:
        if number == 2:
            begin_quiz(team, challenge)
        elif number == 3:
            released_batch = attach_desktop(team, Desktop.query.filter_by(qr_id=challenge.id, active=True).one())
    except EventError as error:
        db.session.rollback()
        from sqlalchemy import update
        from models import Event
        db.session.execute(update(Event).where(Event.id == 1).values(version=Event.version + 1))
        record_scan(challenge, team, "INVALID")
        db.session.commit()
        return jsonify(error=error.message, status="INVALID"), error.status
    scan = ScanLog(team_id=team.id, qr_id=challenge.id, round_id=challenge.round_id,
                   answer_status="VALID", points=event_config().round_1_points if number == 1 else 0)
    db.session.add(scan)
    if number == 1:
        finish_round(team, 1)
        set_score(team.id, challenge.round_id, event_config().round_1_points)
    db.session.commit()
    if released_batch:
        emit_activity(f"Batch {released_batch.number} released after {team.team_id} entered Round 3", "batch")
    emit_activity(f"{team.team_id} scanned {challenge.qr_id}", "scan")
    return jsonify(scan_id=scan.id, qr_id=challenge.qr_id, round=number,
                   prompt=challenge.clue or (challenge.question.prompt if number == 1 and challenge.question else ""),
                   requires_answer=False, message=message)


def begin_quiz(team, qr):
    from models import Quiz, QuizQuestion
    attempt = QuizAttempt.query.filter_by(team_id=team.id).first()
    if attempt:
        return attempt
    quiz = db.session.get(Quiz, qr.quiz_id)
    if not quiz or not quiz.active:
        raise EventError("The destination QR must identify an active quiz.")
    questions = [link.question for link in quiz.questions]
    if len(questions) != 10 or any(not q.active or q.round.number != 2 for q in questions):
        raise EventError("Quiz requires exactly ten active Round 2 questions.")
    start_round(team, 2)
    attempt = QuizAttempt(team_id=team.id, quiz_id=quiz.id, assignments=[snapshot(q) for q in questions])
    db.session.add(attempt)
    for q in questions:
        db.session.add(Answer(team_id=team.id, question_id=q.id, round_id=q.round_id))
    audit("QUIZ_STARTED", team.team_id, {"quiz_id": quiz.id})
    db.session.flush()
    return attempt


@quest_bp.get("/api/team/quiz")
@team_required
def get_quiz():
    attempt = QuizAttempt.query.filter_by(team_id=current_user.id).first()
    if not attempt:
        raise EventError("Scan your destination QR to open the quiz.")
    answers = Answer.query.filter_by(team_id=current_user.id, round_id=Round.query.filter_by(number=2).one().id).all()
    return jsonify(questions=public_questions(attempt.assignments),
                   answers={str(a.question_id): a.selected_answer for a in answers},
                   submitted_at=iso_utc(attempt.submitted_at),
                   destination=event_config().round_3_destination if attempt.submitted_at else None)


@quest_bp.put("/api/team/quiz/answers/<int:question_id>")
@team_required
def save_quiz_answer(question_id):
    require_session(current_user, 2)
    attempt = QuizAttempt.query.filter_by(team_id=current_user.id).first()
    if not attempt or attempt.submitted_at:
        raise EventError("Quiz is unavailable or already submitted.")
    if question_id not in [q["id"] for q in attempt.assignments]:
        raise EventError("Question not assigned to your team.", 404)
    value = str((request.get_json(silent=True) or {}).get("answer", "")).upper()
    if value not in "ABCD" or len(value) != 1:
        raise EventError("Select A, B, C, or D.", 400)
    answer = Answer.query.filter_by(team_id=current_user.id, question_id=question_id).one()
    answer.selected_answer, answer.answer_time = value, utcnow()
    audit("QUESTION_ANSWERED", current_user.team_id, {"question_id": question_id})
    db.session.commit()
    return jsonify(saved=True)


@quest_bp.post("/api/team/quiz/submit")
@team_required
def submit_quiz():
    require_session(current_user, 2)
    attempt = QuizAttempt.query.filter_by(team_id=current_user.id).first()
    if not attempt or attempt.submitted_at:
        raise EventError("Quiz is unavailable or already submitted.")
    answers = {a.question_id: a for a in Answer.query.filter_by(team_id=current_user.id, round_id=Round.query.filter_by(number=2).one().id)}
    if any(not answers[q["id"]].selected_answer for q in attempt.assignments):
        raise EventError("Answer all ten questions before submitting.", 400)
    total = 0
    for q in attempt.assignments:
        answer = answers[q["id"]]
        answer.correct = answer.selected_answer == q["correct_answer"].upper()
        answer.points = q["points"] if answer.correct else 0
        total += answer.points
    attempt.score, attempt.submitted_at = total, utcnow()
    set_score(current_user.id, require_session(current_user, 2).round_id, total)
    finish_round(current_user, 2)
    audit("QUIZ_SUBMITTED", current_user.team_id)
    db.session.commit()
    emit_activity(f"{current_user.team_id} submitted quiz", "quiz")
    return jsonify(message="Quiz submitted successfully. Your responses have been recorded. Results will be announced later.", destination=event_config().round_3_destination)


def attach_desktop(team, desktop):
    existing = DesktopSession.query.filter_by(team_id=team.id).first()
    if existing:
        if existing.desktop_id != desktop.id:
            raise EventError("Your team is already assigned to another desktop.")
        return existing
    if DesktopSession.query.filter_by(desktop_id=desktop.id, completed_at=None).first():
        raise EventError("This desktop is occupied. Contact the coordinator.")
    start_round(team, 3)
    session = DesktopSession(team_id=team.id, desktop_id=desktop.id)
    db.session.add(session)
    team.state = "PASSWORD_CHALLENGE"
    audit("DESKTOP_ASSIGNED", team.team_id, {"desktop": desktop.name})
    db.session.flush()
    from services.batches import on_round_3_entry
    return on_round_3_entry(team)


@quest_bp.get("/desktop/<int:desktop_id>")
@team_required
def desktop_page(desktop_id):
    session = DesktopSession.query.filter_by(team_id=current_user.id, desktop_id=desktop_id).first()
    if not session:
        raise EventError("Scan the station QR using your team login first.", 403)
    return render_template("desktop.html", desktop=session.desktop)


@quest_bp.get("/api/team/desktop")
@team_required
def desktop_status():
    session = DesktopSession.query.filter_by(team_id=current_user.id).first()
    if not session:
        raise EventError("Scan the QR at your desktop station first.")
    return jsonify(desktop_id=session.desktop_id, name=session.desktop.name,
                   attempts_remaining=3-session.password_attempts,
                   unlocked=session.final_challenge_unlocked, completed=bool(session.completed_at))


@quest_bp.post("/api/team/desktop/password")
@team_required
def submit_password():
    value = str((request.get_json(silent=True) or {}).get("password", ""))
    if not value or len(value) > 300:
        raise EventError("Enter a password of 1–300 characters.", 400)
    session = password_attempt(current_user, value)
    db.session.commit()
    emit_activity(f"{current_user.team_id} password attempt #{session.password_attempts}", "password")
    return jsonify(attempts_remaining=3-session.password_attempts, unlocked=session.final_challenge_unlocked,
                   message="Password accepted. Final Challenge unlocked." if session.password_solved else "Password challenge failed. Final Challenge unlocked." if session.final_challenge_unlocked else "Incorrect password.")


@quest_bp.get("/api/team/final")
@team_required
def get_final():
    assignment = final_assignment(current_user)
    answers = FinalAnswer.query.filter_by(assignment_id=assignment.id).all()
    return jsonify(questions=public_questions(assignment.questions), submitted_at=iso_utc(assignment.submitted_at),
                   answers={str(a.question_id): a.answer for a in answers})


@quest_bp.put("/api/team/final/answers/<int:question_id>")
@team_required
def save_final_answer(question_id):
    require_session(current_user, 3)
    assignment = final_assignment(current_user)
    if assignment.submitted_at:
        raise EventError("Final challenge already submitted.")
    if question_id not in [q["id"] for q in assignment.questions]:
        raise EventError("Question not assigned to your team.", 404)
    value = str((request.get_json(silent=True) or {}).get("answer", "")).strip()
    if not value or len(value) > 4000:
        raise EventError("Enter an answer of 1–4,000 characters.", 400)
    answer = FinalAnswer.query.filter_by(assignment_id=assignment.id, question_id=question_id).first()
    if not answer:
        answer = FinalAnswer(assignment_id=assignment.id, question_id=question_id)
        db.session.add(answer)
    answer.answer, answer.timestamp = value, utcnow()
    audit("FINAL_QUESTION_ANSWERED", current_user.team_id, {"question_id": question_id})
    db.session.commit()
    return jsonify(saved=True)


@quest_bp.post("/api/team/final/submit")
@team_required
def submit_final():
    require_session(current_user, 3)
    assignment = final_assignment(current_user)
    if assignment.submitted_at:
        raise EventError("Final challenge already submitted.")
    answers = {a.question_id: a for a in FinalAnswer.query.filter_by(assignment_id=assignment.id)}
    if any(q["id"] not in answers for q in assignment.questions):
        raise EventError("Answer all assigned questions before submitting.", 400)
    for q in assignment.questions:
        answers[q["id"]].points = automatic_points(q, answers[q["id"]].answer)
    assignment.submitted_at = utcnow()
    assignment.reviewed = all(a.points is not None for a in answers.values())
    set_score(current_user.id, require_session(current_user, 3).round_id, sum(a.points or 0 for a in answers.values()))
    DesktopSession.query.filter_by(team_id=current_user.id).one().completed_at = utcnow()
    finish_round(current_user, 3)
    from services.batches import mark_completed
    mark_completed(current_user)
    audit("FINAL_SUBMITTED", current_user.team_id)
    db.session.commit()
    emit_activity(f"{current_user.team_id} completed final challenge", "final")
    return jsonify(message="Submission confirmed. Your answers have been recorded. Results will be announced later.")


@quest_bp.get("/station/<int:desktop_id>")
def station_screen(desktop_id):
    desktop = db.get_or_404(Desktop, desktop_id)
    if not desktop.active:
        raise EventError("This station is not active.")
    return render_template("station.html", desktop=desktop)


@quest_bp.get("/station/<int:desktop_id>/qr.png")
def station_qr(desktop_id):
    from flask import send_file
    from utils.qr_generator import render_qr, scan_url
    desktop = db.get_or_404(Desktop, desktop_id)
    if not desktop.active:
        raise EventError("This station is not active.")
    return send_file(render_qr(scan_url(desktop.qr.secure_token)), mimetype="image/png")
