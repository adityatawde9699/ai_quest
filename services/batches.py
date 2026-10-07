"""Batch assignment and release rules. Mutations run under the Event request lock."""
from extensions import db
from models import Batch, Team, utcnow
from routes.common import audit
from services.event import EventError, event_config


ELIGIBLE = ("READY", "ACTIVE", "COMPLETED")


def serialize(batch):
    return {"id": batch.id, "number": batch.number, "capacity": batch.capacity,
            "status": batch.status, "released_at": batch.released_at.isoformat() if batch.released_at else None,
            "triggered_at": batch.triggered_at.isoformat() if batch.triggered_at else None,
            "completed_at": batch.completed_at.isoformat() if batch.completed_at else None,
            "teams": [{"id": t.id, "team_id": t.team_id, "name": t.team_name,
                       "position": t.batch_position, "status": t.status, "state": t.state}
                      for t in batch.teams]}


def assign(team, batch=None, position=None, override=False):
    if team.round_sessions:
        raise EventError("A team that started a round cannot change batches.")
    if batch is None:
        batches = Batch.query.order_by(Batch.number).all()
        batch = next((item for item in batches if item.status in ("WAITING", "RELEASED", "IN_PROGRESS")
                      and not item.triggered_at and active_count(item) < item.capacity), None)
        if batch is None:
            previous = batches[-1] if batches else None
            batch = Batch(number=(previous.number + 1 if previous else 1), capacity=event_config().batch_size)
            if batch.number == 1 or (previous and previous.triggered_at):
                batch.status, batch.released_at = "RELEASED", utcnow()
            db.session.add(batch)
            db.session.flush()
            audit("BATCH_CREATED", str(batch.number), {"capacity": batch.capacity})
            if batch.status == "RELEASED":
                audit("BATCH_RELEASED", str(batch.number), {"reason": "INITIAL" if batch.number == 1 else "PREVIOUS_TRIGGERED"})
    if batch.status in ("COMPLETED", "PAUSED"):
        raise EventError("This batch cannot accept teams.")
    if team.status in ELIGIBLE and active_count(batch, exclude=team.id) >= batch.capacity and not override:
        raise EventError("Batch is full. A super-admin override is required.")
    occupied = {t.batch_position for t in batch.teams if t.id != team.id}
    if position is None:
        position = next(n for n in range(1, len(occupied) + 2) if n not in occupied)
    if position < 1 or position in occupied:
        raise EventError("Choose an unused positive batch position.", 400)
    old = team.batch.number if team.batch else None
    team.batch = batch
    team.batch_position = position
    audit("BATCH_ASSIGNED", team.team_id, {"from": old, "to": batch.number, "position": position, "override": override})
    db.session.flush()
    release_if_predecessor_triggered(batch)
    return batch


def active_count(batch, exclude=None):
    return sum(t.status in ELIGIBLE and t.id != exclude for t in batch.teams)


def release_if_predecessor_triggered(batch):
    previous = Batch.query.filter(Batch.number < batch.number).order_by(Batch.number.desc()).first()
    if batch.status == "WAITING" and previous and previous.triggered_at and active_count(batch):
        release(batch, "PREVIOUS_TRIGGERED")


def release(batch, reason, team=None):
    if batch.status != "WAITING":
        raise EventError("Only a waiting batch can be released.")
    if not active_count(batch):
        raise EventError("Assign an eligible team before releasing this batch.")
    batch.status, batch.released_at = "RELEASED", utcnow()
    audit("BATCH_RELEASED", str(batch.number), {"reason": reason, "triggering_team": team.team_id if team else None})


def on_round_3_entry(team):
    batch = team.batch
    if not batch or batch.triggered_at:
        return None
    batch.triggered_at = utcnow()
    next_batch = Batch.query.filter(Batch.number > batch.number).order_by(Batch.number).first()
    if next_batch and next_batch.status == "WAITING" and active_count(next_batch):
        release(next_batch, "ROUND_3_ENTRY", team)
        released = next_batch
    else:
        released = None
    audit("BATCH_TRIGGERED", str(batch.number), {"team": team.team_id, "released_batch": released.number if released else None})
    return released


def mark_completed(team):
    batch = team.batch
    if batch and batch.status in ("RELEASED", "IN_PROGRESS", "PAUSED") and all(
        t.status in ("COMPLETED", "DISABLED", "DISQUALIFIED") for t in batch.teams
    ):
        batch.status, batch.completed_at = "COMPLETED", utcnow()
        audit("BATCH_COMPLETED", str(batch.number))
