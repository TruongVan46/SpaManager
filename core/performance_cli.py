import click

from services.performance_profile_service import run_performance_profile


def register_performance_profile_commands(app):
    @app.cli.group("perf")
    def perf_group():
        """Performance profiling commands."""

    @perf_group.command("profile")
    def profile_command():
        """Run the read-only performance profile."""
        report = run_performance_profile()
        click.echo(report.to_text())
