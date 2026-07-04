import click

from services.data_audit_service import run_data_consistency_audit
from services.data_repair_service import run_controlled_repair


def register_data_audit_commands(app):
    @app.cli.group("data")
    def data_group():
        """Data quality and consistency commands."""

    @data_group.command("audit")
    def audit_command():
        """Run the read-only data consistency audit."""
        report = run_data_consistency_audit()
        click.echo(report.to_text())

    @data_group.command("repair")
    @click.option("--dry-run", "dry_run", is_flag=True, help="Preview repairs without changing the database.")
    @click.option("--apply", "apply_changes", is_flag=True, help="Apply safe repairs.")
    @click.option("--yes", is_flag=True, help="Confirm apply mode.")
    @click.option("--only", "only_codes", multiple=True, help="Limit repair planning to specific issue codes.")
    def repair_command(dry_run, apply_changes, yes, only_codes):
        """Run the controlled repair workflow."""
        effective_dry_run = True
        if apply_changes and not dry_run:
            if not yes:
                click.echo("Apply mode requires --yes. Chỉ chạy dry-run, không sửa DB.")
                effective_dry_run = True
            else:
                effective_dry_run = False
        elif apply_changes and dry_run:
            effective_dry_run = True
        elif not apply_changes and not dry_run:
            effective_dry_run = True

        report = run_controlled_repair(
            dry_run=effective_dry_run,
            only=only_codes,
            actor="Hệ thống",
        )
        click.echo(report.to_text())
