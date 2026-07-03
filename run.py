# run.py - SpaManager Project (Local development runner only)
# For production, use Gunicorn via: gunicorn wsgi:app
import os
from app import app

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=app.debug)
