#!/usr/bin/env python3
import os
import sys

# Build paths inside the project like this: os.path.join(BASE_DIR, ...)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# replace "" by real base path
sys.path[0] = BASE_DIR

if __name__ == "__main__":
    if any(map(lambda x: "runserver" in x, sys.argv)):
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "demo.settings.demo")
    else:
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "demo.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)
