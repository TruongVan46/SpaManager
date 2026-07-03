# wsgi.py - WSGI entry point for Production servers (Gunicorn, uWSGI, etc.)
# Used by Railway, Heroku, Render, and any WSGI-compatible hosting platform.
#
# Railway startup command:
#   gunicorn wsgi:app
#
# Or with explicit host/port binding (Railway injects PORT automatically):
#   gunicorn --bind 0.0.0.0:$PORT wsgi:app
from app import app

if __name__ == "__main__":
    app.run()
