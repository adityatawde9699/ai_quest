"""Store Round 3 password with the QR so teams can be assigned later."""
from alembic import op
import sqlalchemy as sa

revision = "d47c1e8a62bf"
down_revision = "c6a94c2f0d31"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("qr_challenge", sa.Column("password_hash", sa.String(length=255), nullable=True))
    op.execute(sa.text("""
        UPDATE qr_challenge
        SET password_hash = (
            SELECT offline_round3.password_hash
            FROM offline_round3
            WHERE offline_round3.password_qr_id = qr_challenge.id
            ORDER BY offline_round3.id
            LIMIT 1
        )
        WHERE EXISTS (
            SELECT 1 FROM offline_round3
            WHERE offline_round3.password_qr_id = qr_challenge.id
        )
    """))


def downgrade():
    op.drop_column("qr_challenge", "password_hash")
