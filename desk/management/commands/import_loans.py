"""
Import the loan history that was embedded in Roziko_Loan_Desk.html
(originally from Roziko_Loan_Tracker.xlsx).

    python manage.py import_loans                      # uses desk/data/loans_seed.json
    python manage.py import_loans --html path/to/Roziko_Loan_Desk.html
    python manage.py import_loans --file other_loans.json

Safe to run twice: loans whose legacy ID already exists are skipped.
Officer names are cleaned the same way the original page did it ('oscar', 'Oscar ' -> 'Oscar').
"""
import json
import re
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from desk import rules
from desk.models import Loan, Officer

SEED = Path(__file__).resolve().parents[2] / "data" / "loans_seed.json"


def s(v, n):
    return "" if v is None else str(v).strip()[:n]


class Command(BaseCommand):
    help = "Import the legacy loan history (4,000+ loans) into the database."

    def add_arguments(self, parser):
        parser.add_argument("--file", help="JSON file with a list of loan objects")
        parser.add_argument("--html", help="The original Roziko_Loan_Desk.html (reads its BASE array)")

    def load(self, opts):
        if opts["html"]:
            text = Path(opts["html"]).read_text(encoding="utf8")
            m = re.search(r"const BASE = (\[.*?\]);\n", text, re.S)
            if not m:
                raise CommandError("Could not find the BASE data array in that HTML file.")
            return json.loads(m.group(1))
        path = Path(opts["file"]) if opts["file"] else SEED
        if not path.exists():
            raise CommandError(f"File not found: {path}")
        return json.loads(path.read_text(encoding="utf8"))

    @transaction.atomic
    def handle(self, *args, **opts):
        data = self.load(opts)
        existing = set(Loan.objects.exclude(legacy_id="").values_list("legacy_id", flat=True))
        officers = {(o.branch, o.name.lower()): o for o in Officer.objects.all()}

        def officer_for(raw, branch):
            name = rules.clean_officer(raw, branch)
            if name == "Unassigned":
                return None
            key = (branch, name.lower())
            if key not in officers:
                officers[key] = Officer.objects.create(branch=branch, name=name)
            return officers[key]

        batch, created, skipped, notes = [], 0, 0, 0
        for d in data:
            lid = d["id"]
            if lid in existing:
                skipped += 1
                continue
            b = d["b"]
            p, i = d.get("p") or 0, d.get("i") or 0
            td = d["td"] if isinstance(d.get("td"), (int, float)) else p + i
            rc = d.get("rc") or 0
            issued, due = rules.parse_date(d.get("di")), rules.parse_date(d.get("dd"))
            note = []
            if d.get("di") and not issued:
                note.append(f"Date issued as entered: {d['di']}")
            if d.get("dd") and not due:
                note.append(f"Repayment date as entered: {d['dd']}")
            notes += bool(note)
            out = max(0, td - rc)
            batch.append(Loan(
                legacy_id=lid, branch=b, serial_no=d.get("sn"), client_name=s(d.get("c"), 120),
                officer=officer_for(d.get("off"), b), date_issued=issued, due_date=due,
                principal=p, interest=i, total_due=td, processing_fee=d.get("pf"),
                amount_received=rc, penalty=d.get("pen"), loan_type=s(d.get("det"), 80),
                client_contact=s(d.get("cc"), 100), guarantor_contact=s(d.get("gc"), 100),
                status=rules.clean_status(d.get("st"), out), remarks=s(d.get("rem"), 200),
                receipt_no=s(d.get("rcpt"), 40), received_by=s(d.get("rb"), 80),
                payment_date_text=s(d.get("dr"), 80), import_note="; ".join(note),
            ))
            if len(batch) >= 500:
                Loan.objects.bulk_create(batch)
                created += len(batch)
                batch = []
        if batch:
            Loan.objects.bulk_create(batch)
            created += len(batch)
        self.stdout.write(self.style.SUCCESS(
            f"Imported {created} loans ({skipped} already present, {notes} with unreadable dates noted). "
            f"Officers on file: {Officer.objects.count()}."))
