"""
Role -> permission matrix. This is the single place that decides who can do what.
Views check these keys with @perm_required("key"); templates check them via the
`P` set that the context processor injects.
"""

CASHIER = "cashier"
OFFICER = "officer"
MANAGER = "manager"
ADVISOR = "advisor"

ROLE_CHOICES = [
    (CASHIER, "Cashier"),
    (OFFICER, "Loans Officer"),
    (MANAGER, "Branch Manager"),
    (ADVISOR, "Advisory Board"),
]

# Every permission key used in the app, with a human label (shown on the Users page).
PERMISSION_LABELS = {
    "view_data": "View dashboard, loans and reminders",
    "add_loan": "Enter new loans",
    "add_payment": "Record payments",
    "delete_loan": "Delete loans",
    "delete_payment": "Delete payments",
    "log_followup": "Log follow-ups on reminders",
    "edit_loan": "Edit loan details",
    "view_recommendations": "View recommendations",
    "add_recommendation": "Make recommendations",
    "review_recommendations": "Mark recommendations as reviewed / delete any",
    "export": "Download data (CSV)",
    "create_users": "Add new users",
    "manage_users": "Edit, reset password and delete users",
    "settings": "Change alert rules and interest/term settings",
    "view_audit": "View the activity log",
}

_VIEW = {"view_data"}

ROLE_PERMS = {
    # Cashier: enter data, delete and view.
    CASHIER: _VIEW | {"add_loan", "add_payment", "delete_loan", "delete_payment"},
    # Loans Officer: view client repayments and payment reminders (and log the follow-up).
    OFFICER: _VIEW | {"log_followup"},
    # Branch Manager: review everything, add users, delete data, etc.
    MANAGER: set(PERMISSION_LABELS),
    # Advisory Board: view, recommend, download and add users.
    ADVISOR: _VIEW | {"view_recommendations", "add_recommendation", "export", "create_users"},
}

# Which roles a user may assign when creating someone. The Advisory Board cannot
# create Branch Managers (stops a privilege jump). Change here if you want otherwise.
CREATABLE_ROLES = {
    MANAGER: [CASHIER, OFFICER, MANAGER, ADVISOR],
    ADVISOR: [CASHIER, OFFICER, ADVISOR],
}


def perms_for(role: str) -> set:
    return ROLE_PERMS.get(role, set())


def creatable_roles(role: str) -> list:
    return CREATABLE_ROLES.get(role, [])
