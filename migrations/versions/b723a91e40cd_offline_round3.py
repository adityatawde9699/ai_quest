"""Team password QR and manually evaluated offline Round 3.

Revision ID: b723a91e40cd
Revises: 8e41a2c9b7d0
"""
from alembic import op
import sqlalchemy as sa

revision = 'b723a91e40cd'
down_revision = '8e41a2c9b7d0'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('offline_round3',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('team_id', sa.Integer(), sa.ForeignKey('team.id'), nullable=False, unique=True),
        sa.Column('password_qr_id', sa.Integer(), sa.ForeignKey('qr_challenge.id'), nullable=False, unique=True),
        sa.Column('password_hash', sa.String(255), nullable=False),
        sa.Column('max_points', sa.Integer(), nullable=False, server_default='100'),
        sa.Column('password_attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('password_solved', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('started_at', sa.DateTime(timezone=True)),
        sa.Column('sheet_path', sa.String(20)),
        sa.Column('sheet_received_at', sa.DateTime(timezone=True)),
        sa.Column('submitted_at', sa.DateTime(timezone=True)),
        sa.Column('reviewed_at', sa.DateTime(timezone=True)),
        sa.Column('points', sa.Integer()),
        sa.Column('judging_reason', sa.Text(), nullable=False, server_default=''),
        sa.CheckConstraint('password_attempts BETWEEN 0 AND 3', name='ck_offline_password_attempts'),
        sa.CheckConstraint('max_points >= 0 AND (points IS NULL OR (points >= 0 AND points <= max_points))', name='ck_offline_points'))
    op.execute("UPDATE round SET name='Offline Sheet Challenge' WHERE number=3")
    op.execute("UPDATE event SET round_3_destination='Scan your Round 3 QR, solve the password riddle, and collect your question sheet from the organizer.' WHERE round_3_destination='Contact the coordinator for your desktop station.'")


def downgrade():
    op.drop_table('offline_round3')
    op.execute("UPDATE round SET name='Desktop Final Challenge' WHERE number=3 AND name='Offline Sheet Challenge'")
