# Procfile - Railway / Heroku / Render startup command
# Railway automatically injects the $PORT environment variable.
# Gunicorn binds to 0.0.0.0:$PORT to accept external traffic.
#
# Workers:   2 worker processes (suitable for a Starter tier instance)
# Timeout:   120 seconds per request (handles slow backup/export operations)
# Log level: info (visible in Railway deployment logs)
web: gunicorn wsgi:app --bind 0.0.0.0:${PORT:-8000} --workers 2 --timeout 120 --log-level info
