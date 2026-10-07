"""add normalized team members and QR room assignment

Revision ID: c49d61f0d62a
Revises: 2477c778b692
Create Date: 2026-09-30

"""
from alembic import op
import sqlalchemy as sa


revision = "c49d61f0d62a"
down_revision = "2477c778b692"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("qr_challenge") as batch_op:
        batch_op.add_column(
            sa.Column("room", sa.String(length=120), nullable=False, server_default="")
        )
        batch_op.alter_column("room", server_default=None)

    op.create_table(
        "team_member",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("team_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["team_id"], ["team.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("team_id", "position", name="uq_team_member_position"),
    )
    op.create_index("ix_team_member_team_id", "team_member", ["team_id"])

    connection = op.get_bind()
    for position in range(1, 4):
        connection.execute(
            sa.text(
                "INSERT INTO team_member (team_id, name, position) "
                f"SELECT id, member_{position}, {position} FROM team "
                f"WHERE member_{position} <> ''"
            )
        )

    op.create_index("ix_scan_log_round_id", "scan_log", ["round_id"])
    op.create_index("ix_qr_challenge_question_id", "qr_challenge", ["question_id"])
    op.create_index("ix_qr_challenge_round_id", "qr_challenge", ["round_id"])
    op.create_index("ix_scan_log_qr_id", "scan_log", ["qr_id"])
    op.create_index("ix_answer_question_id", "answer", ["question_id"])
    op.create_index("ix_answer_round_id", "answer", ["round_id"])
    op.create_index("ix_round_session_round_id", "round_session", ["round_id"])
    op.create_index("ix_score_round_id", "score", ["round_id"])
    op.create_index("ix_activity_log_admin_id", "activity_log", ["admin_id"])
    op.create_index("ix_final_result_rank", "final_result", ["rank"])


def downgrade():
    op.drop_index("ix_final_result_rank", table_name="final_result")
    op.drop_index("ix_activity_log_admin_id", table_name="activity_log")
    op.drop_index("ix_score_round_id", table_name="score")
    op.drop_index("ix_round_session_round_id", table_name="round_session")
    op.drop_index("ix_answer_round_id", table_name="answer")
    op.drop_index("ix_answer_question_id", table_name="answer")
    op.drop_index("ix_scan_log_qr_id", table_name="scan_log")
    op.drop_index("ix_scan_log_round_id", table_name="scan_log")
    op.drop_index("ix_qr_challenge_round_id", table_name="qr_challenge")
    op.drop_index("ix_qr_challenge_question_id", table_name="qr_challenge")
    op.drop_index("ix_team_member_team_id", table_name="team_member")
    op.drop_table("team_member")
    with op.batch_alter_table("qr_challenge") as batch_op:
        batch_op.drop_column("room")
