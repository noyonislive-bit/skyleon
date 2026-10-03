"""
Entry point for cPanel "Setup Python App" (Phusion Passenger).

In cPanel set:
  Application root:          the folder containing this file
  Application startup file:  passenger_wsgi.py
  Application Entry point:   application
"""
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from config.wsgi import application  # noqa: E402,F401
