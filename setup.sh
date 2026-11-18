#!/usr/bin/env bash
# One-time setup: virtualenv, database, import of the 4,153 loans, starter accounts.
set -euo pipefail
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py makemigrations desk
python manage.py migrate
python manage.py import_loans
python manage.py create_starter_users
echo
echo "Done. Start the app with:  source .venv/bin/activate && python manage.py runserver"
