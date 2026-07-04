import click

from services.data_audit_service import run_data_consistency_audit


def register_data_audit_commands(app):
    @app.cli.group("data")
    def data_group():
        """Data quality and consistency commands."""

    @data_group.command("audit")
    def audit_command():
        """Run the read-only data consistency audit."""
        report = run_data_consistency_audit()
        click.echo(report.to_text())
