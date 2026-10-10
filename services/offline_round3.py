"""Public status never exposes passwords or unscanned riddles."""
from models import OfflineRound3, ScanLog, RoundSession
from routes.common import iso_utc


def participant_status(team):
    config = OfflineRound3.query.filter_by(team_id=team.id).first()
    if not config:
        return {"configured": False}
    session = RoundSession.query.filter_by(team_id=team.id, round_id=config.password_qr.round_id).first()
    scanned = {s.qr_id for s in ScanLog.query.filter_by(team_id=team.id)}
    return dict(configured=True,
                password_clue=config.password_qr.clue if config.password_qr_id in scanned else None,
                attempts_remaining=3-config.password_attempts, password_solved=config.password_solved,
                sheet_path=config.sheet_path, sheet_received_at=iso_utc(config.sheet_received_at),
                completed_at=iso_utc(session.ended_at) if session and session.status == "COMPLETED" else None,
                submitted_at=iso_utc(config.submitted_at), reviewed=bool(config.reviewed_at))
