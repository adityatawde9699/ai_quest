from datetime import datetime, timezone

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from extensions import db


def utcnow():
    return datetime.now(timezone.utc)


class Admin(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    active = db.Column(db.Boolean, nullable=False, default=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="admin")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def get_id(self):
        return f"admin:{self.id}"


class Team(UserMixin, db.Model):
    __table_args__ = (
        db.UniqueConstraint("batch_id", "batch_position", name="uq_team_batch_position"),
        db.Index("ix_team_batch_status", "batch_id", "status"),
    )
    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.String(20), unique=True, nullable=False, index=True)
    team_name = db.Column(db.String(120), nullable=False)
    member_1 = db.Column(db.String(100), nullable=False, default="")
    member_2 = db.Column(db.String(100), nullable=False, default="")
    member_3 = db.Column(db.String(100), nullable=False, default="")
    pin_hash = db.Column(db.String(255), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="READY", index=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    role = "team"

    state = db.Column(db.String(30), nullable=False, default="REGISTERED", index=True)
    assigned_qr_id = db.Column(db.Integer, db.ForeignKey("qr_challenge.id"))
    bonus = db.Column(db.Integer, nullable=False, default=0)
    penalty = db.Column(db.Integer, nullable=False, default=0)
    batch_id = db.Column(db.Integer, db.ForeignKey("batch.id"), index=True)
    batch_position = db.Column(db.Integer)
    batch = db.relationship("Batch", back_populates="teams")

    scans = db.relationship("QRScan", back_populates="team", cascade="all, delete-orphan")
    answers = db.relationship("Answer", back_populates="team", cascade="all, delete-orphan")
    round_sessions = db.relationship(
        "RoundSession", back_populates="team", cascade="all, delete-orphan"
    )
    scores = db.relationship("Score", back_populates="team", cascade="all, delete-orphan")
    final_results = db.relationship("FinalResult", back_populates="team", cascade="all, delete-orphan")
    members = db.relationship(
        "TeamMember", back_populates="team", cascade="all, delete-orphan",
        order_by="TeamMember.position",
    )

    def set_pin(self, pin):
        self.pin_hash = generate_password_hash(pin)

    def check_pin(self, pin):
        return check_password_hash(self.pin_hash, pin)

    def get_id(self):
        return f"team:{self.id}"


class TeamMember(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey("team.id", ondelete="CASCADE"), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    position = db.Column(db.Integer, nullable=False)

    __table_args__ = (
        db.UniqueConstraint("team_id", "position", name="uq_team_member_position"),
        db.Index("ix_team_member_team_id", "team_id"),
    )

    team = db.relationship("Team", back_populates="members")


class Round(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.Integer, unique=True, nullable=False)
    name = db.Column(db.String(120), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="LOCKED")
    started_at = db.Column(db.DateTime(timezone=True))
    ended_at = db.Column(db.DateTime(timezone=True))

    questions = db.relationship("Question", back_populates="round", cascade="all, delete-orphan")
    challenges = db.relationship(
        "QRCode", back_populates="round", cascade="all, delete-orphan"
    )


class Question(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    round_id = db.Column(db.Integer, db.ForeignKey("round.id"), nullable=False, index=True)
    prompt = db.Column(db.Text, nullable=False)
    option_a = db.Column(db.String(300), nullable=False, default="")
    option_b = db.Column(db.String(300), nullable=False, default="")
    option_c = db.Column(db.String(300), nullable=False, default="")
    option_d = db.Column(db.String(300), nullable=False, default="")
    correct_answer = db.Column(db.String(300), nullable=False)
    points = db.Column(db.Integer, nullable=False, default=10)
    time_limit = db.Column(db.Integer, nullable=False, default=60)
    active = db.Column(db.Boolean, nullable=False, default=True)

    kind = db.Column(db.String(30), nullable=False, default="MCQ")
    position = db.Column(db.Integer, nullable=False, default=0)

    round = db.relationship("Round", back_populates="questions")
    answers = db.relationship("Answer", back_populates="question", cascade="all, delete-orphan")


class QRCode(db.Model):
    __tablename__ = "qr_challenge"

    id = db.Column(db.Integer, primary_key=True)
    qr_id = db.Column(db.String(30), unique=True, nullable=False, index=True)
    secure_token = db.Column(db.String(96), unique=True, nullable=False, index=True)
    round_id = db.Column(db.Integer, db.ForeignKey("round.id"), nullable=False, index=True)
    question_id = db.Column(db.Integer, db.ForeignKey("question.id"), index=True)
    quiz_id = db.Column(db.Integer, db.ForeignKey("quiz.id"))
    room = db.Column(db.String(120), nullable=False, default="")
    status = db.Column(db.String(20), nullable=False, default="INACTIVE")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    activated_at = db.Column(db.DateTime(timezone=True))
    deactivated_at = db.Column(db.DateTime(timezone=True))
    expires_at = db.Column(db.DateTime(timezone=True))

    title = db.Column(db.String(120), nullable=False, default="")
    clue = db.Column(db.Text, nullable=False, default="")
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    round = db.relationship("Round", back_populates="challenges")
    question = db.relationship("Question")
    scans = db.relationship("QRScan", back_populates="challenge", cascade="all, delete-orphan")


class QRScan(db.Model):
    __tablename__ = "scan_log"

    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey("team.id"), nullable=False, index=True)
    qr_id = db.Column(db.Integer, db.ForeignKey("qr_challenge.id"), nullable=False, index=True)
    round_id = db.Column(db.Integer, db.ForeignKey("round.id"), nullable=False, index=True)
    scan_time = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    answer_time = db.Column(db.DateTime(timezone=True))
    submitted_answer = db.Column(db.Text)
    answer_status = db.Column(db.String(20), nullable=False, default="PENDING")
    points = db.Column(db.Integer, nullable=False, default=0)

    __table_args__ = (db.UniqueConstraint("team_id", "qr_id", name="uq_team_qr_scan"),)

    team = db.relationship("Team", back_populates="scans")
    challenge = db.relationship("QRCode", back_populates="scans")


class Answer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey("team.id"), nullable=False, index=True)
    question_id = db.Column(db.Integer, db.ForeignKey("question.id"), nullable=False, index=True)
    round_id = db.Column(db.Integer, db.ForeignKey("round.id"), nullable=False, index=True)
    question_start_time = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    answer_time = db.Column(db.DateTime(timezone=True))
    selected_answer = db.Column(db.String(10), nullable=False, default="")
    correct = db.Column(db.Boolean, nullable=False, default=False)
    points = db.Column(db.Integer, nullable=False, default=0)

    __table_args__ = (db.UniqueConstraint("team_id", "question_id", name="uq_team_question_answer"),)

    team = db.relationship("Team", back_populates="answers")
    question = db.relationship("Question", back_populates="answers")


class RoundSession(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey("team.id"), nullable=False, index=True)
    round_id = db.Column(db.Integer, db.ForeignKey("round.id"), nullable=False, index=True)
    started_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    ended_at = db.Column(db.DateTime(timezone=True))
    status = db.Column(db.String(20), nullable=False, default="ACTIVE")

    __table_args__ = (db.UniqueConstraint("team_id", "round_id", name="uq_team_round_session"),)
    team = db.relationship("Team", back_populates="round_sessions")
    round = db.relationship("Round")


class Score(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey("team.id"), nullable=False, index=True)
    round_id = db.Column(db.Integer, db.ForeignKey("round.id"), nullable=False, index=True)
    points = db.Column(db.Integer, nullable=False, default=0)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (db.UniqueConstraint("team_id", "round_id", name="uq_team_round_score"),)
    team = db.relationship("Team", back_populates="scores")
    round = db.relationship("Round")


class ActivityLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    admin_id = db.Column(db.Integer, db.ForeignKey("admin.id"), index=True)
    action = db.Column(db.String(100), nullable=False)
    target = db.Column(db.String(160), nullable=False, default="")
    metadata_json = db.Column(db.JSON, nullable=False, default=dict)
    timestamp = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, index=True)

    team_id = db.Column(db.Integer, db.ForeignKey("team.id"), index=True)
    request_id = db.Column(db.String(36))

    admin = db.relationship("Admin")


class FinalResult(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey("team.id"), nullable=False, unique=True)
    rank = db.Column(db.Integer, nullable=False, index=True)
    total_score = db.Column(db.Integer, nullable=False)
    total_time = db.Column(db.Integer, nullable=False)
    completed_at = db.Column(db.DateTime(timezone=True))
    generated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    locked = db.Column(db.Boolean, nullable=False, default=False)

    team = db.relationship("Team", back_populates="final_results")


# Preserve the names used by the existing routes and integrations.
QRChallenge = QRCode
ScanLog = QRScan


class Event(db.Model):
    """One event per database; this row also serializes event mutations."""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, default="Swayambhu 2026")
    mode = db.Column(db.String(20), nullable=False, default="TEST")
    active = db.Column(db.Boolean, nullable=False, default=False)
    results_published = db.Column(db.Boolean, nullable=False, default=False)
    results_locked = db.Column(db.Boolean, nullable=False, default=False)
    leaderboard_visible = db.Column(db.Boolean, nullable=False, default=False)
    final_question_count = db.Column(db.Integer, nullable=False, default=10)
    round_1_points = db.Column(db.Integer, nullable=False, default=0)
    round_3_destination = db.Column(db.String(300), nullable=False, default="Contact the coordinator for your desktop station.")
    version = db.Column(db.Integer, nullable=False, default=0)
    batch_size = db.Column(db.Integer, nullable=False, default=5)


class Batch(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.Integer, nullable=False, unique=True)
    capacity = db.Column(db.Integer, nullable=False, default=5)
    status = db.Column(db.String(20), nullable=False, default="WAITING", index=True)
    released_at = db.Column(db.DateTime(timezone=True))
    triggered_at = db.Column(db.DateTime(timezone=True))
    completed_at = db.Column(db.DateTime(timezone=True))
    teams = db.relationship("Team", back_populates="batch", order_by="Team.batch_position")
    __table_args__ = (db.CheckConstraint("capacity > 0", name="ck_batch_capacity"),)


class QRScanEvent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey("team.id"), index=True)
    qr_id = db.Column(db.Integer, db.ForeignKey("qr_challenge.id"), index=True)
    round_id = db.Column(db.Integer, db.ForeignKey("round.id"), index=True)
    timestamp = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, index=True)
    status = db.Column(db.String(30), nullable=False, index=True)
    ip_address = db.Column(db.String(45), nullable=False, default="")
    user_agent = db.Column(db.String(300), nullable=False, default="")
    team = db.relationship("Team")
    qr = db.relationship("QRCode")


class Quiz(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(120), nullable=False)
    active = db.Column(db.Boolean, nullable=False, default=True)
    questions = db.relationship("QuizQuestion", order_by="QuizQuestion.position", cascade="all, delete-orphan")


class QuizQuestion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    quiz_id = db.Column(db.Integer, db.ForeignKey("quiz.id"), nullable=False, index=True)
    question_id = db.Column(db.Integer, db.ForeignKey("question.id"), nullable=False)
    position = db.Column(db.Integer, nullable=False)
    question = db.relationship("Question")
    __table_args__ = (db.UniqueConstraint("quiz_id", "position"), db.UniqueConstraint("quiz_id", "question_id"))


class QuizAttempt(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey("team.id"), nullable=False, unique=True)
    quiz_id = db.Column(db.Integer, db.ForeignKey("quiz.id"), nullable=False)
    started_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    submitted_at = db.Column(db.DateTime(timezone=True))
    assignments = db.Column(db.JSON, nullable=False)  # Immutable server-side question snapshots.
    score = db.Column(db.Integer)


class Desktop(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False, unique=True)
    qr_id = db.Column(db.Integer, db.ForeignKey("qr_challenge.id"), nullable=False, unique=True)
    password_hash = db.Column(db.String(255), nullable=False)
    active = db.Column(db.Boolean, nullable=False, default=True)
    qr = db.relationship("QRCode")

    def set_password(self, value):
        self.password_hash = generate_password_hash(value)


class DesktopSession(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    desktop_id = db.Column(db.Integer, db.ForeignKey("desktop.id"), nullable=False, index=True)
    team_id = db.Column(db.Integer, db.ForeignKey("team.id"), nullable=False, unique=True)
    started_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    password_attempts = db.Column(db.Integer, nullable=False, default=0)
    password_solved = db.Column(db.Boolean, nullable=False, default=False)
    final_challenge_unlocked = db.Column(db.Boolean, nullable=False, default=False)
    completed_at = db.Column(db.DateTime(timezone=True))
    desktop = db.relationship("Desktop")
    team = db.relationship("Team")
    __table_args__ = (db.CheckConstraint("password_attempts BETWEEN 0 AND 3", name="ck_password_attempt_cap"),)


class PasswordAttempt(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("desktop_session.id"), nullable=False, index=True)
    number = db.Column(db.Integer, nullable=False)
    correct = db.Column(db.Boolean, nullable=False)
    timestamp = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    __table_args__ = (db.UniqueConstraint("session_id", "number"), db.CheckConstraint("number BETWEEN 1 AND 3"))


class FinalAssignment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey("team.id"), nullable=False, unique=True)
    questions = db.Column(db.JSON, nullable=False)
    started_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    submitted_at = db.Column(db.DateTime(timezone=True))
    reviewed = db.Column(db.Boolean, nullable=False, default=False)


class FinalAnswer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    assignment_id = db.Column(db.Integer, db.ForeignKey("final_assignment.id"), nullable=False, index=True)
    question_id = db.Column(db.Integer, db.ForeignKey("question.id"), nullable=False)
    answer = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    points = db.Column(db.Integer)
    __table_args__ = (db.UniqueConstraint("assignment_id", "question_id"),)


class RateBucket(db.Model):
    key = db.Column(db.String(64), primary_key=True)
    window = db.Column(db.Integer, nullable=False)
    count = db.Column(db.Integer, nullable=False, default=0)
