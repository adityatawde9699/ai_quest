from datetime import datetime, timedelta, timezone

from flask import Blueprint, jsonify, request, send_file
from flask_login import current_user
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from extensions import db
from models import Answer, Desktop, Question, QRChallenge, QRScanEvent, Round, RoundSession, ScanLog, Score, Team, utcnow
from routes.common import admin_required, audit, emit_activity, emit_leaderboard, iso_utc, super_admin_required, team_required
from utils.qr_generator import render_qr, scan_url
from utils.security import new_qr_token

qr_bp = Blueprint("qr", __name__)


def _qr_payload(challenge):
    return {
        "id": challenge.id,
        "qr_id": challenge.qr_id,
        "round_id": challenge.round_id,
        "round": challenge.round.number,
        "round_name": challenge.round.name,
        "question_id": challenge.question_id,
        "room": challenge.room,
        "title": challenge.title, "clue": challenge.clue, "quiz_id": challenge.quiz_id,
        "status": challenge.status,
        "created_at": iso_utc(challenge.created_at),
        "updated_at": iso_utc(challenge.updated_at),
        "activated_at": iso_utc(challenge.activated_at),
        "deactivated_at": iso_utc(challenge.deactivated_at),
        "expires_at": iso_utc(challenge.expires_at),
        "scans": len(challenge.scans),
    }


def _add_points(team_id, round_id, points):
    row = Score.query.filter_by(team_id=team_id, round_id=round_id).first()
    if not row:
        row = Score(team_id=team_id, round_id=round_id, points=0)
        db.session.add(row)
    row.points += points
    row.updated_at = utcnow()


@qr_bp.get("/api/qrs")
@admin_required
def list_qrs():
    return jsonify([_qr_payload(qr) for qr in QRChallenge.query.order_by(QRChallenge.id.desc())])


@qr_bp.post("/api/qrs")
@admin_required
def create_qr():
    data = request.get_json(silent=True) or {}
    event_round = db.session.get(Round, data.get("round_id"))
    if not event_round:
        return jsonify(error="Select a valid round."), 400
    room = str(data.get("room", "")).strip()
    if len(room) > 120:
        return jsonify(error="Room must be 120 characters or fewer."), 400
    question = None
    if data.get("question_id"):
        question = db.session.get(Question, data["question_id"])
        if not question or question.round_id != event_round.id:
            return jsonify(error="The clue must belong to the selected round."), 400
    from models import Quiz
    quiz_id = data.get("quiz_id")
    quiz = db.session.get(Quiz, quiz_id) if quiz_id else None
    if event_round.number == 2 and (not quiz or not quiz.active or len(quiz.questions) != 10):
        return jsonify(error="Select a configured quiz for a Round 2 QR."), 400
    try:
        count = int(data.get("count", 1))
    except (TypeError, ValueError):
        return jsonify(error="Number of QR codes must be a whole number."), 400
    if count < 1 or count > 100 or (event_round.number != 1 and count != 1):
        return jsonify(error="Generate 1 to 100 QR codes for Round 1, or one for another round."), 400
    expires_at = None
    if data.get("expires_at"):
        try:
            expires_at = datetime.fromisoformat(str(data["expires_at"]).replace("Z", "+00:00"))
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            expires_at = expires_at.astimezone(timezone.utc)
        except ValueError:
            return jsonify(error="Expiration must be a valid date and time."), 400
    prefix = f"QR-R{event_round.number}-"
    numbers = [
        int(challenge.qr_id.rsplit("-", 1)[1])
        for challenge in QRChallenge.query.filter_by(round_id=event_round.id).all()
        if challenge.qr_id.startswith(prefix) and challenge.qr_id.rsplit("-", 1)[1].isdigit()
    ]
    number = max(numbers, default=0) + 1
    custom_label = str(data.get("qr_number") or "").strip()
    if custom_label and count != 1:
        return jsonify(error="A custom QR number can only be used for one QR."), 400
    if custom_label and (len(custom_label) > 30 or not all(c.isalnum() or c == "-" for c in custom_label)):
        return jsonify(error="QR number must use letters, numbers or hyphens (30 characters maximum)."), 400
    if custom_label and QRChallenge.query.filter_by(qr_id=custom_label).first():
        return jsonify(error="QR number already exists."), 409
    title = str(data.get("title", "")).strip()
    clue = str(data.get("clue", "")).strip()
    if len(title) > 120 or len(clue) > 2000:
        return jsonify(error="Title or clue is too long."), 400
    challenges = []
    for offset in range(count):
        label = custom_label or f"{prefix}{number + offset:03d}"
        challenge = QRChallenge(qr_id=label, secure_token=new_qr_token(), round_id=event_round.id,
                                question_id=question.id if question else None, room=room,
                                quiz_id=quiz.id if event_round.number == 2 else None,
                                title=title, clue=clue, expires_at=expires_at)
        db.session.add(challenge)
        challenges.append(challenge)
    db.session.flush()
    audit("QR generated", challenges[0].qr_id, {"round": event_round.number, "count": count})
    db.session.commit()
    return jsonify(qr=_qr_payload(challenges[0]), qrs=[_qr_payload(q) for q in challenges]), 201


@qr_bp.get("/api/qrs/<int:qr_pk>/image")
@admin_required
def qr_image(qr_pk):
    challenge = db.session.get(QRChallenge, qr_pk)
    if not challenge:
        return jsonify(error="QR not found."), 404
    payload = scan_url(challenge.secure_token)
    return send_file(render_qr(payload), mimetype="image/png", download_name=f"{challenge.qr_id}.png")


@qr_bp.delete("/api/qrs/<int:qr_pk>")
@super_admin_required
def permanently_delete_qr(qr_pk):
    challenge = db.session.get(QRChallenge, qr_pk)
    if not challenge:
        return jsonify(error="QR not found."), 404
    from services.event import event_config
    if event_config().results_locked:
        return jsonify(error="Results are locked."), 409
    scan_events = QRScanEvent.query.filter_by(qr_id=challenge.id).all()
    if (ScanLog.query.filter_by(qr_id=challenge.id).first()
            or any(row.status == "VALID" for row in scan_events)
            or Team.query.filter_by(assigned_qr_id=challenge.id).first()
            or Desktop.query.filter_by(qr_id=challenge.id).first()):
        return jsonify(error="This QR has scan, team, or desktop history. Archive it to preserve its records."), 409
    label = challenge.qr_id
    audit("QR_PERMANENTLY_DELETED", label)
    # Keep failed or unauthenticated scan attempts while removing their FK to this QR.
    for scan_event in scan_events:
        scan_event.qr_id = None
    db.session.flush()
    db.session.delete(challenge)
    db.session.commit()
    emit_activity(f"{label} permanently deleted", "qr")
    return jsonify(ok=True, deleted=True)


@qr_bp.post("/api/qrs/<int:qr_pk>/<action>")
@admin_required
def manage_qr(qr_pk, action):
    challenge = db.session.get(QRChallenge, qr_pk)
    if not challenge:
        return jsonify(error="QR not found."), 404
    from models import Desktop
    desktop = Desktop.query.filter_by(qr_id=challenge.id).first()
    if desktop and action == "regenerate":
        from models import DesktopSession
        if DesktopSession.query.filter_by(desktop_id=desktop.id, completed_at=None).first():
            return jsonify(error="Do not regenerate an occupied desktop QR."), 409
    if desktop and action in ("deactivate", "delete", "archive", "physical-delete"):
        return jsonify(error="Manage desktop availability from Event Operations."), 409
    if action == "activate":
        if challenge.round.status not in ("READY", "ACTIVE"):
            return jsonify(error="Unlock the QR's round before activation."), 409
        challenge.status = "ACTIVE"
        challenge.activated_at = utcnow()
        challenge.deactivated_at = None
        audit("QR activated", challenge.qr_id)
    elif action == "deactivate":
        challenge.status = "INACTIVE"
        challenge.deactivated_at = utcnow()
        audit("QR deactivated", challenge.qr_id)
    elif action == "regenerate":
        challenge.secure_token = new_qr_token()
        audit("QR_TOKEN_REGENERATED", challenge.qr_id)
    elif action in ("delete", "archive"):
        challenge.status = "ARCHIVED"
        audit("QR_ARCHIVED", challenge.qr_id)
    elif action == "physical-delete":
        return jsonify(error="Archive QR codes to preserve history."), 409
    else:
        return jsonify(error="Unknown QR action."), 404
    db.session.commit()
    emit_activity(f"{challenge.qr_id} {action}d", "qr")
    return jsonify(qr=_qr_payload(challenge))


@qr_bp.get("/api/qrs/<int:qr_pk>/scans")
@admin_required
def qr_scans(qr_pk):
    challenge = db.session.get(QRChallenge, qr_pk)
    if not challenge:
        return jsonify(error="QR not found."), 404
    from models import QRScanEvent
    return jsonify([
        {"team_id": row.team.team_id if row.team else "Unauthenticated",
         "team_name": row.team.team_name if row.team else "",
         "scan_time": iso_utc(row.timestamp), "answer_status": row.status,
         "ip_address": row.ip_address, "user_agent": row.user_agent}
        for row in QRScanEvent.query.filter_by(qr_id=challenge.id).order_by(QRScanEvent.id.desc())
    ])


@qr_bp.post("/api/admin/questions")
@admin_required
def add_question():
    data = request.get_json(silent=True) or {}
    event_round = db.session.get(Round, data.get("round_id"))
    prompt = str(data.get("prompt", "")).strip()
    answer = str(data.get("correct_answer", "")).strip()
    if not event_round or not prompt or len(prompt) > 2000:
        return jsonify(error="Select a round and enter a question (2,000 characters maximum)."), 400
    if not answer or len(answer) > 300:
        return jsonify(error="Enter a correct answer of 1 to 300 characters."), 400
    if event_round.number == 2 and answer.upper() not in {"A", "B", "C", "D"}:
        return jsonify(error="Quiz correct answer must be A, B, C, or D."), 400
    try:
        points = int(data.get("points", 10))
        time_limit = int(data.get("time_limit", 60))
    except (TypeError, ValueError):
        return jsonify(error="Points and time limit must be whole numbers."), 400
    if not 0 <= points <= 10000 or not 5 <= time_limit <= 3600:
        return jsonify(error="Points must be 0-10,000 and time limit 5-3,600 seconds."), 400
    from routes.operations import KINDS, integer
    position = integer(data.get("position", 0))
    kind = str(data.get("kind", "MCQ")).upper()
    if kind not in KINDS or (event_round.number == 2 and kind != "MCQ"):
        return jsonify(error="Select a supported question type; Round 2 requires MCQ."), 400
    if kind == "MCQ" and event_round.number in (2, 3) and any(not str(data.get("option_"+key, "")).strip() for key in "abcd"):
        return jsonify(error="All four MCQ options are required."), 400
    if kind == "MCQ" and event_round.number == 3 and answer.upper() not in {"A", "B", "C", "D"}:
        return jsonify(error="MCQ answer must be A, B, C, or D."), 400
    if kind == "TRUE/FALSE" and answer.upper() not in ("TRUE", "FALSE"):
        return jsonify(error="True/False key must be TRUE or FALSE."), 400
    question = Question(
        round_id=event_round.id,
        kind=kind,
        position=position,
        prompt=prompt,
        option_a=str(data.get("option_a", ""))[:300],
        option_b=str(data.get("option_b", ""))[:300],
        option_c=str(data.get("option_c", ""))[:300],
        option_d=str(data.get("option_d", ""))[:300],
        correct_answer=answer.upper() if event_round.number == 2 else answer,
        points=points,
        time_limit=time_limit,
    )
    validate_question(question, event_round.number)
    db.session.add(question)
    audit("Question created", f"Round {event_round.number}")
    db.session.commit()
    return jsonify(id=question.id), 201


@qr_bp.get("/api/admin/questions")
@admin_required
def list_questions():
    return jsonify([
        {"id": q.id, "round_id": q.round_id, "round": q.round.number, "prompt": q.prompt,
         "options": [q.option_a, q.option_b, q.option_c, q.option_d],
         "option_a": q.option_a, "option_b": q.option_b, "option_c": q.option_c,
         "option_d": q.option_d, "correct_answer": q.correct_answer, "points": q.points,
         "time_limit": q.time_limit, "active": q.active, "kind": q.kind, "position": q.position}
        for q in Question.query.order_by(Question.round_id, Question.position, Question.id)
    ])


@qr_bp.route("/api/admin/questions/<int:question_id>", methods=["PATCH", "DELETE"])
@admin_required
def edit_question(question_id):
    question = db.session.get(Question, question_id)
    if not question:
        return jsonify(error="Question not found."), 404
    from models import QuizQuestion, QuizAttempt, FinalAssignment
    assigned = QuizQuestion.query.filter_by(question_id=question.id).first() or (question.round.number == 3 and FinalAssignment.query.first())
    if request.method == "DELETE":
        if assigned or question.answers or QRChallenge.query.filter_by(question_id=question.id).first():
            return jsonify(error="Questions used by attempts or QR challenges cannot be deleted."), 409
        audit("Question deleted", question.id)
        db.session.delete(question)
        db.session.commit()
        return jsonify(ok=True)
    data = request.get_json(silent=True) or {}
    editable = {
        "prompt", "option_a", "option_b", "option_c", "option_d",
        "correct_answer", "points", "time_limit", "kind", "position",
    }
    quiz_attempt = db.session.query(QuizAttempt.id).join(QuizQuestion, QuizQuestion.quiz_id == QuizAttempt.quiz_id).filter(QuizQuestion.question_id == question.id).first()
    if editable.intersection(data) and (
        quiz_attempt or (question.round.number == 3 and assigned) or Answer.query.filter_by(question_id=question.id).first()
        or QRChallenge.query.filter_by(question_id=question.id).join(ScanLog).first()
    ):
        return jsonify(error="A question with recorded attempts cannot be edited."), 409
    if "prompt" in data:
        prompt = str(data["prompt"]).strip()
        if not prompt or len(prompt) > 2000:
            return jsonify(error="Question is required (2,000 characters maximum)."), 400
        question.prompt = prompt
    for field in ("option_a", "option_b", "option_c", "option_d"):
        if field in data:
            setattr(question, field, str(data[field])[:300])
    if "correct_answer" in data:
        answer = str(data["correct_answer"]).strip()
        if not answer or len(answer) > 300:
            return jsonify(error="Enter a correct answer of 1 to 300 characters."), 400
        if question.round.number == 2 and answer.upper() not in {"A", "B", "C", "D"}:
            return jsonify(error="Quiz correct answer must be A, B, C, or D."), 400
        question.correct_answer = answer.upper() if question.round.number == 2 else answer
    try:
        points = int(data.get("points", question.points))
        time_limit = int(data.get("time_limit", question.time_limit))
    except (TypeError, ValueError):
        return jsonify(error="Points and time limit must be whole numbers."), 400
    if not 0 <= points <= 10000 or not 5 <= time_limit <= 3600:
        return jsonify(error="Points must be 0-10,000 and time limit 5-3,600 seconds."), 400
    question.points = points
    question.time_limit = time_limit
    if "active" in data:
        if not isinstance(data["active"], bool):
            return jsonify(error="Use a boolean value."), 400
        question.active = data["active"]
    if "position" in data:
        from routes.operations import integer
        question.position = integer(data["position"])
    if "kind" in data:
        from routes.operations import KINDS
        if data["kind"] not in KINDS or (question.round.number == 2 and data["kind"] != "MCQ"):
            return jsonify(error="Invalid question type."), 400
        question.kind = data["kind"]
    validate_question(question, question.round.number)
    audit("Question updated", question.id, {"active": question.active})
    db.session.commit()
    return jsonify(id=question.id, active=question.active)


@qr_bp.post("/api/admin/round-three/score")
@admin_required
def judge_round_three():
    return jsonify(error="Use Final Assignments for question review or the audited team score adjustment."), 409


@qr_bp.get("/api/admin/monitoring")
@admin_required
def monitoring():
    result = []
    for team in Team.query.order_by(Team.team_id):
        latest = ScanLog.query.filter_by(team_id=team.id).order_by(ScanLog.scan_time.desc()).first()
        session = RoundSession.query.filter_by(team_id=team.id, status="ACTIVE").first()
        activity_times = [
            value for value in [
                latest.scan_time if latest else None,
                session.ended_at if session else None,
                session.started_at if session else None,
            ] if value
        ]
        last_activity = max(activity_times, default=None)
        result.append({
            **{"team_id": team.team_id, "team_name": team.team_name, "status": team.status,
               "batch_number": team.batch.number if team.batch else None,
               "batch_status": team.batch.status if team.batch else "UNASSIGNED"},
            "round": session.round.number if session else (latest.challenge.round.number if latest else 0),
            "current_qr": latest.challenge.qr_id if latest else "-",
            "last_scan": iso_utc(latest.scan_time) if latest else None,
            "score": sum(row.points for row in team.scores),
            "round_start": iso_utc(session.started_at) if session else None,
            "last_activity": iso_utc(last_activity),
        })
    return jsonify(result)


@qr_bp.patch("/api/qrs/<int:qr_pk>")
@admin_required
def edit_qr(qr_pk):
    from models import Quiz
    challenge = db.get_or_404(QRChallenge, qr_pk)
    data = request.get_json(silent=True) or {}
    if challenge.scans:
        return jsonify(error="Archive and replace a QR already used by teams."), 409
    from services.event import event_config
    if event_config().results_locked:
        return jsonify(error="Results are locked."), 409
    event_round = challenge.round
    if "round_id" in data:
        event_round = db.session.get(Round, data["round_id"])
        if not event_round:
            return jsonify(error="Select a valid round."), 400
    from models import Desktop
    linked = (Team.query.filter_by(assigned_qr_id=challenge.id).first()
              or Desktop.query.filter_by(qr_id=challenge.id).first())
    def changed_id(key, current):
        if key not in data:
            return False
        raw = data[key]
        value = None if raw in (None, "") else int(raw)
        return value != current

    identity_changed = (
        ("qr_id" in data and str(data["qr_id"]).strip() != challenge.qr_id)
        or changed_id("round_id", challenge.round_id)
        or changed_id("question_id", challenge.question_id)
        or changed_id("quiz_id", challenge.quiz_id)
    )
    if linked and identity_changed:
        return jsonify(error="Round, QR number, question, and quiz cannot change while assigned to a team or desktop."), 409
    if "qr_id" in data:
        label = str(data["qr_id"]).strip()
        if not label or len(label) > 30 or not all(c.isalnum() or c == "-" for c in label):
            return jsonify(error="QR number must use letters, numbers or hyphens (30 characters maximum)."), 400
        existing = QRChallenge.query.filter(QRChallenge.qr_id == label, QRChallenge.id != challenge.id).first()
        if existing:
            return jsonify(error="QR number already exists."), 409
        challenge.qr_id = label
    question = None
    if "question_id" in data and data["question_id"] not in (None, ""):
        question = db.session.get(Question, data["question_id"])
        if not question or question.round_id != event_round.id:
            return jsonify(error="Select a clue or question from the chosen round."), 400
    if "question_id" in data:
        challenge.question_id = question.id if question else None
    if "round_id" in data:
        challenge.round = event_round
    if event_round.number == 2:
        quiz_id = data.get("quiz_id", challenge.quiz_id)
        quiz = db.session.get(Quiz, quiz_id) if quiz_id not in (None, "") else None
        if not quiz:
            return jsonify(error="Select a configured quiz for a Round 2 QR."), 400
        challenge.quiz_id = quiz.id
    elif "round_id" in data or "quiz_id" in data:
        if data.get("quiz_id") not in (None, ""):
            return jsonify(error="Only Round 2 QRs can be linked to a quiz."), 400
        challenge.quiz_id = None
    for key, limit in (("title", 120), ("room", 120), ("clue", 2000)):
        if key in data:
            value = str(data[key]).strip()
            if len(value) > limit:
                return jsonify(error=f"{key} is too long."), 400
            setattr(challenge, key, value)
    if "expires_at" in data:
        value = data["expires_at"]
        if value in (None, ""):
            challenge.expires_at = None
        else:
            try:
                expires_at = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=timezone.utc)
                challenge.expires_at = expires_at.astimezone(timezone.utc)
            except ValueError:
                return jsonify(error="Expiration must be a valid date and time."), 400
    if "status" in data:
        new_status = str(data["status"]).upper()
        if new_status not in ("ACTIVE", "INACTIVE", "ARCHIVED"):
            return jsonify(error="Status must be ACTIVE, INACTIVE, or ARCHIVED."), 400
        if new_status == "ACTIVE" and event_round.status not in ("READY", "ACTIVE"):
            return jsonify(error="The selected round is not open for QR activation."), 409
        if challenge.status == "ACTIVE" and new_status != "ACTIVE":
            challenge.deactivated_at = utcnow()
        elif new_status == "ACTIVE" and challenge.status != "ACTIVE":
            challenge.activated_at = utcnow()
            challenge.deactivated_at = None
        challenge.status = new_status
    audit("QR_UPDATED", challenge.qr_id, {"fields": sorted(data.keys())})
    db.session.commit()
    return jsonify(qr=_qr_payload(challenge))


def validate_question(question, number):
    from services.event import EventError
    if question.kind == "MCQ" and number in (2, 3):
        if question.correct_answer.upper() not in "ABCD" or len(question.correct_answer) != 1 or any(not getattr(question, "option_"+key).strip() for key in "abcd"):
            raise EventError("MCQs require four nonempty options and a key A–D.", 400)
    if question.kind == "TRUE/FALSE" and question.correct_answer.upper() not in ("TRUE", "FALSE"):
        raise EventError("True/False key must be TRUE or FALSE.", 400)
    if question.kind == "NUMERICAL":
        from decimal import Decimal, InvalidOperation
        try:
            valid = Decimal(question.correct_answer).is_finite()
        except InvalidOperation:
            valid = False
        if not valid:
            raise EventError("Numerical questions require a finite numeric key.", 400)
