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
    # The DOCX role matrix makes the Cashier an operational data-entry role,
    # while still allowing the full recommendation and export workflow.
    CASHIER: _VIEW | {
        "add_loan", "add_payment", "delete_loan", "delete_payment", "log_followup",
        "edit_loan", "view_recommendations", "add_recommendation",
        "review_recommendations", "export",
    },
    # Loans Officers can work the reminder/recommendation workflow, but cannot
    # change loan or payment records.
    OFFICER: _VIEW | {
        "log_followup", "view_recommendations", "add_recommendation",
        "review_recommendations", "export",
    },
    # Branch Managers oversee branch operations and settings. User and audit
    # administration belongs to the Advisory Board in the supplied matrix.
    MANAGER: _VIEW | {
        "add_loan", "add_payment", "delete_loan", "delete_payment", "log_followup",
        "edit_loan", "view_recommendations", "add_recommendation",
        "review_recommendations", "export", "settings",
    },
    # Advisory Board is the overall role: it receives every application
    # permission, including user administration and the activity log.
    ADVISOR: set(PERMISSION_LABELS),
}

# Which roles a user may assign when creating someone. Only the overall role can
# access user creation, and it may assign any application role.
CREATABLE_ROLES = {
    ADVISOR: [CASHIER, OFFICER, MANAGER, ADVISOR],
}


def perms_for(role: str) -> set:
    return ROLE_PERMS.get(role, set())


def creatable_roles(role: str) -> list:
    return CREATABLE_ROLES.get(role, [])
