# Minimal adapter so the Start Command 'gunicorn app:app' works with Django
# It re-exports the Django WSGI application under the name 'app'.
from core.wsgi import application as app
