"""Participant challenge routes; all progress is derived from committed records."""
from datetime import timezone

from flask import Blueprint, jsonify, request
from flask_login import current_user

from extensions import db
from models import (Answer, QRChallenge, QRScanEvent, QuizAttempt, ScanLog,
                    Round, OfflineRound3, utcnow)
from routes.common import audit, emit_activity, iso_utc, team_required
from services.event import (EventError, active_round, event_config,
                            finish_round, public_questions,
                            require_session, set_score, snapshot, start_round)

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
                config = OfflineRound3.query.filter_by(team_id=team.id).first()
                if not config or challenge.id != config.password_qr_id:
                    raise EventError("Scan your team's assigned Round 3 password QR.")
                if config.sheet_received_at:
                    raise EventError("Your team already has its question sheet.")
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
            config = OfflineRound3.query.filter_by(team_id=team.id).one()
            start_round(team, 3)
            team.state = "ROUND_3_ACTIVE"
            if not config.started_at:
                config.started_at = utcnow()
                from services.batches import on_round_3_entry
                released_batch = on_round_3_entry(team)
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



@quest_bp.get("/api/team/round3")
@team_required
def round3_status():
    from services.offline_round3 import participant_status
    return jsonify(participant_status(current_user))


@quest_bp.post("/api/team/round3/password")
@team_required
def round3_password():
    from werkzeug.security import check_password_hash
    from services.offline_round3 import participant_status
    require_session(current_user, 3)
    config = OfflineRound3.query.filter_by(team_id=current_user.id).first()
    if not config or not ScanLog.query.filter_by(team_id=current_user.id, qr_id=config.password_qr_id).first():
        raise EventError("Scan your password QR first.")
    qr = config.password_qr
    if qr.status != "ACTIVE" or (qr.expires_at and utcnow() > qr.expires_at.replace(tzinfo=timezone.utc)):
        raise EventError("The password QR is inactive or expired. Contact the coordinator.")
    if config.sheet_received_at or config.password_solved:
        raise EventError("Password path complete. Ask the organizer for your sheet.")
    if config.password_attempts >= 3:
        raise EventError("No password attempts remain. Contact the organizer.")
    value = str((request.get_json(silent=True) or {}).get("password", ""))
    if not value or len(value) > 300:
        raise EventError("Enter a password of 1–300 characters.", 400)
    config.password_attempts += 1
    config.password_solved = check_password_hash(config.password_hash, value)
    audit("OFFLINE_PASSWORD_ATTEMPT", current_user.team_id,
          {"number": config.password_attempts, "correct": config.password_solved})
    db.session.commit()
    return jsonify(**participant_status(current_user), message=
                   "Password accepted. Show this confirmation to the organizer to collect your question sheet."
                   if config.password_solved else "Incorrect password. Please try again if attempts remain.")


@quest_bp.post("/api/team/round3/complete")
@team_required
def complete_offline_round3():
    require_session(current_user, 3)
    config = OfflineRound3.query.filter_by(team_id=current_user.id).first()
    if not config or not config.password_solved:
        raise EventError("Solve your Round 3 password riddle before completing the round.")
    finish_round(current_user, 3)
    from services.batches import mark_completed
    mark_completed(current_user)
    audit("TEAM_OFFLINE_ROUND3_COMPLETED", current_user.team_id)
    db.session.commit()
    emit_activity(f"{current_user.team_id} completed Round 3; finish time recorded", "round")
    return jsonify(message="Quest complete. Your finish time is saved. Return your answer sheet to the organizer for evaluation.")


@quest_bp.get("/desktop/<int:desktop_id>")
@quest_bp.get("/station/<int:desktop_id>")
@quest_bp.get("/station/<int:desktop_id>/qr.png")
@quest_bp.get("/api/team/desktop")
@quest_bp.post("/api/team/desktop/password")
@quest_bp.get("/api/team/final")
@quest_bp.put("/api/team/final/answers/<int:question_id>")
@quest_bp.post("/api/team/final/submit")
def retired_round3(**kwargs):
    raise EventError("Round 3 uses offline question sheets. Open your team dashboard.", 410)
