from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import selectinload

from extensions import db
from models import Score, Team


def refresh_round_score(team_id, round_id):
    round_points = db.session.query(func.coalesce(func.sum(Score.points), 0)).filter_by(
        team_id=team_id, round_id=round_id
    ).scalar()
    return int(round_points or 0)


def _completed_at(team):
    finished = [session.ended_at for session in team.round_sessions if session.ended_at]
    if not finished:
        return None
    latest = max(finished)
    if latest.tzinfo is None:
        latest = latest.replace(tzinfo=timezone.utc)
    return latest.astimezone(timezone.utc)


def leaderboard_rows():
    teams = db.session.query(Team).filter(
        Team.status.notin_(("DISQUALIFIED", "DISABLED"))
    ).options(selectinload(Team.scores), selectinload(Team.round_sessions)).all()
    rows = []
    for team in teams:
        total_score = sum(score.points for score in team.scores) + team.bonus - team.penalty
        total_time = sum(
            int((session.ended_at - session.started_at).total_seconds())
            for session in team.round_sessions
            if session.ended_at and session.started_at
        )
        completed_at = _completed_at(team)
        rows.append(
            {
                "rank": 0,
                "team_id": team.team_id,
                "team_name": team.team_name,
                "round_scores": {str(score.round_id): int(score.points) for score in team.scores},
                "score": total_score,
                "time": total_time,
                "completed_at": completed_at.isoformat() if completed_at else None,
                "status": team.status,
                "round": max((s.round.number for s in team.round_sessions if s.round), default=0),
            }
        )
    rows.sort(
        key=lambda row: (
            -row["score"],
            row["time"],
            row["completed_at"] or datetime.max.replace(tzinfo=timezone.utc).isoformat(),
            row["team_id"],
        )
    )
    for index, row in enumerate(rows, start=1):
        row["rank"] = index
    return rows
