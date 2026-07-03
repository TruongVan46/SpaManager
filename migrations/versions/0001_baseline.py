revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None
message = "Baseline current SQLite production schema"


def upgrade():
    from extensions import db
    import models  # noqa: F401 - ensure all tables are registered

    db.create_all()


def downgrade():
    raise RuntimeError("The baseline migration cannot be downgraded safely.")

