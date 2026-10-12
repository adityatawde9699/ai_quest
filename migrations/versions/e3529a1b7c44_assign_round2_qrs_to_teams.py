"""Allow admins to assign Round 2 quiz QRs to teams."""
from alembic import op
import sqlalchemy as sa


revision = "e3529a1b7c44"
down_revision = "d47c1e8a62bf"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("team") as batch_op:
        batch_op.add_column(sa.Column("assigned_round2_qr_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_team_assigned_round2_qr_id_qr_challenge",
            "qr_challenge", ["assigned_round2_qr_id"], ["id"],
        )
        batch_op.create_index("ix_team_assigned_round2_qr_id", ["assigned_round2_qr_id"])


def downgrade():
    with op.batch_alter_table("team") as batch_op:
        batch_op.drop_index("ix_team_assigned_round2_qr_id")
        batch_op.drop_constraint("fk_team_assigned_round2_qr_id_qr_challenge", type_="foreignkey")
        batch_op.drop_column("assigned_round2_qr_id")
