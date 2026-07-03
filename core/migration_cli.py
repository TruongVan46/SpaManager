import importlib
import pkgutil
from pathlib import Path

import click
from sqlalchemy import text

from extensions import db

MIGRATIONS_PACKAGE = "migrations.versions"
MIGRATION_TABLE = "alembic_version"


def _load_revision_modules():
    package = importlib.import_module(MIGRATIONS_PACKAGE)
    package_path = Path(package.__file__).resolve().parent
    modules = []

    for module_info in sorted(pkgutil.iter_modules([str(package_path)]), key=lambda item: item.name):
        if module_info.name.startswith("_"):
            continue
        module = importlib.import_module(f"{MIGRATIONS_PACKAGE}.{module_info.name}")
        revision = getattr(module, "revision", None)
        if revision:
            modules.append(module)

    modules_by_revision = {module.revision: module for module in modules}
    ordered = []
    parent_revision = None
    visited = set()

    while True:
        children = [module for module in modules if getattr(module, "down_revision", None) == parent_revision]
        if not children:
            break
        if len(children) > 1:
            raise RuntimeError("Lightweight migration loader does not support branching revisions.")

        next_module = children[0]
        if next_module.revision in visited:
            raise RuntimeError("Circular migration chain detected.")

        ordered.append(next_module)
        visited.add(next_module.revision)
        parent_revision = next_module.revision

    if len(ordered) != len(modules_by_revision):
        missing = sorted(set(modules_by_revision) - visited)
        raise RuntimeError(f"Unlinked migration revisions found: {', '.join(missing)}")

    return ordered


def _ensure_version_table(connection):
    connection.execute(
        text(
            f"""
            CREATE TABLE IF NOT EXISTS {MIGRATION_TABLE} (
                version_num VARCHAR(32) NOT NULL
            )
            """
        )
    )


def _get_current_revision(connection):
    _ensure_version_table(connection)
    row = connection.execute(text(f"SELECT version_num FROM {MIGRATION_TABLE} LIMIT 1")).fetchone()
    return row[0] if row else None


def _set_current_revision(connection, revision):
    _ensure_version_table(connection)
    connection.execute(text(f"DELETE FROM {MIGRATION_TABLE}"))
    connection.execute(text(f"INSERT INTO {MIGRATION_TABLE} (version_num) VALUES (:revision)"), {"revision": revision})


def _head_revision():
    revisions = _load_revision_modules()
    if not revisions:
        return None
    return revisions[-1].revision


def _revision_lookup():
    return {module.revision: module for module in _load_revision_modules()}


def _resolve_revision_label(label):
    label = (label or "").strip().lower()
    if label == "head":
        return _head_revision()
    return label or None


def _format_revision_line(module, is_current=False):
    marker = " [current]" if is_current else ""
    message = getattr(module, "message", module.revision)
    return f"{module.revision}{marker} - {message}"


def register_migration_commands(app):
    @app.cli.group("db")
    def db_group():
        """Database migration commands."""

    @db_group.command("current")
    def current_command():
        """Show the active schema revision."""
        with db.engine.begin() as connection:
            current_revision = _get_current_revision(connection)

        if not current_revision:
            click.echo("No revision stamp found.")
            return

        click.echo(current_revision)

    @db_group.command("history")
    def history_command():
        """Show available schema revisions."""
        revisions = _load_revision_modules()
        with db.engine.begin() as connection:
            current_revision = _get_current_revision(connection)

        if not revisions:
            click.echo("No revisions found.")
            return

        for module in revisions:
            click.echo(_format_revision_line(module, module.revision == current_revision))

    @db_group.command("upgrade")
    @click.argument("revision", required=False, default="head")
    def upgrade_command(revision):
        """Apply pending migrations up to the requested revision."""
        target_revision = _resolve_revision_label(revision)
        revision_lookup = _revision_lookup()
        revisions = _load_revision_modules()

        if target_revision is None and revisions:
            target_revision = revisions[-1].revision

        if target_revision is None:
            click.echo("No migrations available.")
            return

        if target_revision not in revision_lookup:
            raise click.ClickException(f"Unknown revision: {revision}")

        with db.engine.begin() as connection:
            current_revision = _get_current_revision(connection)

        pending = []
        seen_current = current_revision is None
        for module in revisions:
            if not seen_current:
                if module.revision == current_revision:
                    seen_current = True
                continue
            if module.revision == current_revision:
                continue
            pending.append(module)
            if module.revision == target_revision:
                break

        if current_revision == target_revision:
            click.echo(f"Database already at revision {target_revision}.")
            return

        if not pending:
            click.echo("No pending migrations.")
            return

        for module in pending:
            module.upgrade()
            with db.engine.begin() as connection:
                _set_current_revision(connection, module.revision)
            click.echo(f"Applied {module.revision}")

    @db_group.command("stamp")
    @click.argument("revision", required=False, default="head")
    def stamp_command(revision):
        """Stamp the database with a revision without running migrations."""
        resolved_revision = _resolve_revision_label(revision)
        if resolved_revision is None:
            raise click.ClickException("No migration revisions are available to stamp.")

        revision_lookup = _revision_lookup()
        if resolved_revision not in revision_lookup:
            raise click.ClickException(f"Unknown revision: {revision}")

        with db.engine.begin() as connection:
            _set_current_revision(connection, resolved_revision)

        click.echo(f"Stamped {resolved_revision}")
