"""
WSGI entry point for PythonAnywhere.
"""
import sys
import os

# Add the project directory to the path
path = os.path.dirname(os.path.abspath(__file__))
if path not in sys.path:
    sys.path.insert(0, path)

# Set matplotlib to non-interactive backend before importing the app
import matplotlib
matplotlib.use('Agg')

# Import the Flask app
from gnss_app import app as application

# On PythonAnywhere the secret key should be set from environment
# (optional — os.urandom is fine for development)
# import os
# application.secret_key = os.environ.get('FLASK_SECRET_KEY', os.urandom(24))
