# Roziko Loan Desk (Django)

The single-page Loan Desk, rebuilt as a multi-user Django application with sign-in,
four user levels, a database, an activity log and CSV downloads. The business rules
(alert flags, outstanding balances, recommended actions, officer-name cleaning) are
ported from the original page; they give the same flags, balances and days-late as the original on all 4,153 loans (checked by running both).

## Quick start

Starter accounts (note the passwords now, they are not shown again):
  manager    Branch Manager   fYRuQHpP2-fr
  cashier    Cashier          99iUoLFgrPyK
  officer    Loans Officer    tT0fJ4lot0Jp
  advisor    Advisory Board   PeYU6-o6NE1_

```bash
./setup.sh                      # Linux / macOS (creates .venv, database, imports loans, makes accounts)
source .venv/bin/activate
python manage.py runserver      # open http://127.0.0.1:8000
```

On Windows run the same commands one by one:

```
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python manage.py makemigrations desk
python manage.py migrate
python manage.py import_loans
python manage.py create_starter_users
python manage.py runserver
```

`create_starter_users` prints a random password for `manager`, `cashier`, `officer` and `advisor`
(shown once). Sign in as `manager`, add the real staff on the **Users** page, then delete or
disable the starter accounts. To make your own first manager instead:
`python manage.py createsuperuser` (superusers are Branch Managers).

## The four user levels

| Permission | Cashier | Loans Officer | Branch Manager | Advisory Board |
|---|:-:|:-:|:-:|:-:|
| View dashboard, loans, reminders | yes | yes | yes | yes |
| Enter new loans, record payments | yes | | yes | |
| Delete loans and payments | yes | | yes | |
| Log follow-ups on reminders | | yes | yes | |
| Edit loan details | | | yes | |
| Make recommendations | | | yes (review / delete) | yes |
| View recommendations | | | yes | yes |
| Download data (CSV) | | | yes | yes |
| Add new users | | | yes (any level) | yes (not Branch Manager) |
| Edit / reset / delete users, settings, activity log | | | yes | |

The whole matrix lives in `desk/permissions.py` (one place to change it). It is also shown
on the Users page. Every view checks it on the server, so hiding a button is never the only guard.

Choices I made where the brief was open (change them in `desk/permissions.py`):

* **Loans Officers** can also log follow-ups on a reminder (call/visit outcome and promised date).
  They cannot enter payments or change loans. If an officer account is linked to a loan-officer
  name, their Reminders page opens on their own clients (they can switch to All).
* **Advisory Board** can add users but cannot create Branch Managers, so the board cannot
  promote anyone to manager. Set `CREATABLE_ROLES[ADVISOR]` to include `MANAGER` to allow it.
* **Branch scope:** a user's Branch can be set to Arua or Gulu to show only that branch's data;
  leave it blank for both branches.
* **Cashier** has no edit right (enter, delete, view only, as requested). A wrongly entered loan is
  deleted and re-entered, or corrected by a Branch Manager.

## Loan officer name: pick or type

On **Add loan** (and Edit loan, and the Loans Officer user form) the *Loan officer* box is a
combo box: choose a name from the drop-down for the selected branch, or type the name of an officer
who is not on the list. A typed name is matched to an existing officer ignoring capitals and extra
spaces, otherwise a new officer is created for that branch and appears in the drop-down from then on.

## What you get

* **Dashboard** with the original filters, tiles, charts and officer table, plus a once-per-day
  reminder pop-up after sign-in.
* **Reminders** ordered by urgency, with copy-able phone numbers, follow-up log and payment entry.
  The red badge in the menu counts due-today, defaulters and severe defaults.
* **Loans** list with search, sorting, paging, and a detail page with payments, follow-ups,
  recommendations and history.
* **Recommendations** page for the Advisory Board, with management marking them reviewed.
* **Activity log** (managers): who created, edited, deleted, exported, or changed users and settings.
  Deleted loans keep a one-line record of what they were.
* **Settings** (managers): reminder window, severe-default days, interest rate, loan terms.

## Notes on the data

* `python manage.py import_loans` loads `desk/data/loans_seed.json` (the 4,153 loans that were embedded
  in the HTML). It can be run again safely; existing loans are skipped. Use `--html path` to read a
  fresh copy of the HTML page instead.
* 26 loans had a date that cannot be read (for example `9/92025`). They are imported with a blank date and
  the original text is shown in the *Import note* on the loan page. The 7 that still have a balance are
  flagged **CHECK DATE** so a manager can correct them with Edit loan.
* Amounts already received in the Excel tracker are kept as *Amount received before this system*;
  payments entered here are added on top.
* One deliberate change from the original page: a loan whose balance is fully paid now shows status
  **Completed** (319 loans were labelled "Current" in the old page even though they were paid).

## Going live

Copy `.env.example` to `.env` and replace the deployment values. The settings module
loads `.env` without overriding environment variables supplied by the process.

```bash
cp .env.example .env
# edit .env with a real secret, domain, database path, and SMTP credentials
python manage.py collectstatic --noinput
gunicorn roziko.wsgi
```

Serve `/static/` from `staticfiles/` with your web server (or add WhiteNoise), put it behind HTTPS,
and back up `db.sqlite3` regularly. For heavier multi-branch use, switch `DATABASES` to PostgreSQL.

## Tests

```bash
python -m unittest desk.tests.test_rules   # business rules, no Django needed
python manage.py test                       # roles, permissions, officer combo box, workflows
```

## Layout

```
roziko/            settings, urls, WSGI/ASGI entry points
desk/rules.py      business rules (pure Python)
desk/permissions.py role -> permission matrix
desk/models.py     User, Officer, Loan, Payment, FollowUp, Recommendation, AuditLog, SiteSettings
desk/views.py      pages; desk/forms.py forms; desk/services.py shared queries and CSV
desk/templates/    HTML; static/desk/ CSS, JavaScript, and logo
```
