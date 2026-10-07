"""rolling five-team batches

Revision ID: 8e41a2c9b7d0
Revises: 66d5f8c67ffe
"""
from alembic import op
import sqlalchemy as sa
from datetime import datetime, timezone

revision = "8e41a2c9b7d0"
down_revision = "66d5f8c67ffe"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("batch",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("number", sa.Integer(), nullable=False, unique=True),
        sa.Column("capacity", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("status", sa.String(20), nullable=False, server_default="WAITING"),
        sa.Column("released_at", sa.DateTime(timezone=True)),
        sa.Column("triggered_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("capacity > 0", name="ck_batch_capacity"))
    op.create_index("ix_batch_status", "batch", ["status"])
    with op.batch_alter_table("event") as table:
        table.add_column(sa.Column("batch_size", sa.Integer(), nullable=False, server_default="5"))
    with op.batch_alter_table("team") as table:
        table.add_column(sa.Column("batch_id", sa.Integer(), sa.ForeignKey("batch.id", name="fk_team_batch_id")))
        table.add_column(sa.Column("batch_position", sa.Integer()))
        table.create_index("ix_team_batch_id", ["batch_id"])
        table.create_index("ix_team_batch_status", ["batch_id", "status"])
        table.create_unique_constraint("uq_team_batch_position", ["batch_id", "batch_position"])
    conn = op.get_bind()
    teams = conn.execute(sa.text("SELECT id, status FROM team ORDER BY id")).all()
    started = {r[0] for r in conn.execute(sa.text("SELECT DISTINCT team_id FROM round_session"))}
    last_started_batch = max(((i // 5) + 1 for i, (team_id, _) in enumerate(teams) if team_id in started), default=1)
    for offset in range(0, len(teams), 5):
        number = offset // 5 + 1
        status = "RELEASED" if number <= last_started_batch else "WAITING"
        conn.execute(sa.text("INSERT INTO batch (number, capacity, status, released_at) VALUES (:n, 5, :s, :at)"),
                     {"n": number, "s": status, "at": datetime.now(timezone.utc) if status == "RELEASED" else None})
        batch_id = conn.execute(sa.text("SELECT id FROM batch WHERE number=:n"), {"n": number}).scalar_one()
        for position, (team_id, _) in enumerate(teams[offset:offset + 5], 1):
            conn.execute(sa.text("UPDATE team SET batch_id=:b, batch_position=:p WHERE id=:id"),
                         {"b": batch_id, "p": position, "id": team_id})
        statement = sa.text("INSERT INTO activity_log (action, target, metadata_json, timestamp) VALUES ('BATCH_BACKFILLED', :target, :metadata, :at)").bindparams(sa.bindparam("metadata", type_=sa.JSON()))
        conn.execute(statement,
                     {"target": str(number), "metadata": {"team_ids": [team_id for team_id, _ in teams[offset:offset + 5]], "status": status},
                      "at": datetime.now(timezone.utc)})


def downgrade():
    op.execute("DELETE FROM activity_log WHERE action='BATCH_BACKFILLED'")
    with op.batch_alter_table("team") as table:
        table.drop_constraint("uq_team_batch_position", type_="unique")
        table.drop_index("ix_team_batch_id")
        table.drop_index("ix_team_batch_status")
        table.drop_column("batch_position")
        table.drop_column("batch_id")
    with op.batch_alter_table("event") as table:
        table.drop_column("batch_size")
    op.drop_index("ix_batch_status", table_name="batch")
    op.drop_table("batch")
