import json

import click

from services.operational_diagnostics_service import run_operational_diagnostics


def register_operational_diagnostics_commands(app):
    @app.cli.group("ops")
    def ops_group():
        """Operational diagnostics commands."""

    def _emit_diagnostics(verbose, skip_performance, skip_repair_plan, as_json):
        report = run_operational_diagnostics(
            include_performance=not skip_performance,
            include_repair_plan=not skip_repair_plan,
            verbose=verbose,
        )
        if as_json:
            click.echo(json.dumps(report.to_dict(verbose=verbose), ensure_ascii=False, indent=2))
        else:
            click.echo(report.to_text(verbose=verbose))

    @ops_group.command("diagnostics")
    @click.option("--verbose", is_flag=True, help="Show detailed section data.")
    @click.option("--skip-performance", is_flag=True, help="Skip the performance profile section.")
    @click.option("--skip-repair-plan", is_flag=True, help="Skip the repair dry-run section.")
    @click.option("--json", "as_json", is_flag=True, help="Output JSON instead of plain text.")
    def diagnostics_command(verbose, skip_performance, skip_repair_plan, as_json):
        """Run the read-only operational diagnostics report."""
        _emit_diagnostics(verbose, skip_performance, skip_repair_plan, as_json)

    @ops_group.command("report")
    @click.option("--verbose", is_flag=True, help="Show detailed section data.")
    @click.option("--skip-performance", is_flag=True, help="Skip the performance profile section.")
    @click.option("--skip-repair-plan", is_flag=True, help="Skip the repair dry-run section.")
    @click.option("--json", "as_json", is_flag=True, help="Output JSON instead of plain text.")
    def report_command(verbose, skip_performance, skip_repair_plan, as_json):
        """Alias for diagnostics."""
        _emit_diagnostics(verbose, skip_performance, skip_repair_plan, as_json)
