# SpaManager migrations

This project uses a lightweight `flask db` command set to baseline the current SQLite production schema.

Commands:

- `flask db current`
- `flask db history`
- `flask db upgrade`
- `flask db stamp head`

The baseline revision is `0001_baseline`.

