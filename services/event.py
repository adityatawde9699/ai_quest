"""Shared state guards and persistent challenge assignment/scoring."""
from decimal import Decimal, InvalidOperation

from extensions import db
from models import Event, Round, RoundSession, Score, utcnow
from routes.common import audit


class EventError(Exception):
    def __init__(self, message, status=409):
        self.message, self.status = message, status


def event_config():
    return db.session.get(Event, 1)


def active_round(number):
    event = event_config()
    row = Round.query.filter_by(number=number).first()
    if not event or not event.active or not row or row.status != "ACTIVE":
        raise EventError("This round is not active. Please wait for the coordinator.")
    if event.results_locked:
        raise EventError("Results are locked.")
    return row


def require_session(team, number):
    row = active_round(number)
    session = RoundSession.query.filter_by(team_id=team.id, round_id=row.id, status="ACTIVE").first()
    if not session:
        raise EventError("Start the unlocked round from your dashboard first.")
    return session


def start_round(team, number):
    row = active_round(number)
    if number == 1 and (not team.batch or team.batch.status not in ("RELEASED", "IN_PROGRESS")):
        raise EventError("Your batch is waiting for release. Please wait for the coordinator.")
    existing = RoundSession.query.filter_by(team_id=team.id, round_id=row.id).first()
    if existing:
        if existing.status == "COMPLETED":
            raise EventError("This team already completed the round.")
        return existing
    if number > 1:
        previous = Round.query.filter_by(number=number - 1).one()
        if not RoundSession.query.filter_by(team_id=team.id, round_id=previous.id, status="COMPLETED").first():
            raise EventError("Complete the previous round before starting this one.")
    if RoundSession.query.filter_by(team_id=team.id, status="ACTIVE").first():
        raise EventError("Your team already has an active round.")
    if number == 1 and not team.assigned_qr_id:
        raise EventError("Ask the coordinator to assign your envelope QR.")
    session = RoundSession(team_id=team.id, round_id=row.id)
    db.session.add(session)
    if number == 1 and team.batch.status == "RELEASED":
        team.batch.status = "IN_PROGRESS"
        audit("BATCH_IN_PROGRESS", str(team.batch.number), {"first_team": team.team_id})
    team.status = "ACTIVE"
    team.state = f"ROUND_{number}_ACTIVE"
    audit("ROUND_STARTED", team.team_id, {"round": number})
    db.session.flush()
    return session


def finish_round(team, number):
    session = require_session(team, number)
    session.status, session.ended_at = "COMPLETED", utcnow()
    team.state = "COMPLETED" if number == 3 else f"ROUND_{number}_COMPLETED"
    if number == 3:
        team.status = "COMPLETED"
    audit("ROUND_COMPLETED", team.team_id, {"round": number})


def set_score(team_id, round_id, points):
    if event_config().results_locked:
        raise EventError("Results are locked.")
    score = Score.query.filter_by(team_id=team_id, round_id=round_id).first()
    if not score:
        score = Score(team_id=team_id, round_id=round_id)
        db.session.add(score)
    score.points, score.updated_at = points, utcnow()


def snapshot(question):
    return {"id": question.id, "prompt": question.prompt, "kind": question.kind,
            "options": {key: getattr(question, f"option_{key.lower()}") for key in "ABCD"},
            "correct_answer": question.correct_answer, "points": question.points}


def public_questions(questions):
    return [{k: v for k, v in q.items() if k not in ("correct_answer", "points")} for q in questions]


def automatic_points(question, answer):
    kind = question["kind"]
    if kind in ("SHORT ANSWER", "LOGICAL", "AI/TECHNICAL"):
        return None
    if kind == "NUMERICAL":
        try:
            left, right = Decimal(answer.strip()), Decimal(question["correct_answer"].strip())
            correct = left.is_finite() and right.is_finite() and left == right
        except InvalidOperation:
            correct = False
    else:
        correct = answer.strip().casefold() == question["correct_answer"].strip().casefold()
    return question["points"] if correct else 0
