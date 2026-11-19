"""
Create one starter account per role with a random password (printed once).

    python manage.py create_starter_users

The Advisory Board user should then sign in, add real users from the Users page
and delete or deactivate these starter accounts.
"""
import secrets

from django.core.management.base import BaseCommand

from desk.models import Role, User

STARTERS = [
    ("manager", Role.MANAGER, "Branch", "Manager"),
    ("cashier", Role.CASHIER, "Starter", "Cashier"),
    ("officer", Role.OFFICER, "Starter", "Loans Officer"),
    ("advisor", Role.ADVISOR, "Advisory", "Board"),
]


class Command(BaseCommand):
    help = "Create starter accounts for each of the four roles (random passwords, shown once)."

    def handle(self, *args, **opts):
        made = []
        for username, role, first, last in STARTERS:
            if User.objects.filter(username=username).exists():
                self.stdout.write(f"  {username}: already exists, skipped")
                continue
            pw = secrets.token_urlsafe(9)
            User.objects.create_user(username=username, password=pw, role=role,
                                     first_name=first, last_name=last)
            made.append((username, role.label, pw))
        if made:
            self.stdout.write(self.style.SUCCESS("\nStarter accounts (note the passwords now, they are not shown again):"))
            for u, r, pw in made:
                self.stdout.write(f"  {u:<10} {r:<16} {pw}")
