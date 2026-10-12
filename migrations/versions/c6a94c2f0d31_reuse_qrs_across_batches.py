"""Allow one Round 3 QR to be assigned to teams in separate batches."""
from alembic import op
import sqlalchemy as sa

revision = "c6a94c2f0d31"
down_revision = "b723a91e40cd"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table(
            "offline_round3",
            naming_convention={"uq": "uq_%(table_name)s_%(column_0_name)s"},
        ) as batch_op:
            batch_op.drop_constraint("uq_offline_round3_password_qr_id", type_="unique")
    else:
        op.drop_constraint(
            "offline_round3_password_qr_id_key", "offline_round3", type_="unique"
        )
    op.create_index(
        "ix_offline_round3_password_qr_id", "offline_round3", ["password_qr_id"]
    )


def downgrade():
    op.drop_index("ix_offline_round3_password_qr_id", table_name="offline_round3")
    duplicate = op.get_bind().execute(sa.text(
        "SELECT password_qr_id FROM offline_round3 GROUP BY password_qr_id HAVING COUNT(*) > 1 LIMIT 1"
    )).first()
    if duplicate:
        raise RuntimeError("Cannot restore unique Round 3 QR assignment while QR IDs are shared.")
    op.create_unique_constraint(
        "offline_round3_password_qr_id_key", "offline_round3", ["password_qr_id"]
    )
