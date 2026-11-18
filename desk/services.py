"""Query helpers shared by the views, the context processor and the CSV export."""
from __future__ import annotations

import csv
from io import BytesIO

from django.core.cache import cache
from django.db.models import BigIntegerField, Sum, Value
from django.db.models.functions import Coalesce
from django.http import HttpResponse
from django.utils import timezone
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from . import rules
from .models import AuditLog, Branch, Loan, SiteSettings

BR = {"A": "Arua", "G": "Gulu"}


def today():
    return timezone.localdate()


def get_settings() -> SiteSettings:
    obj, _ = SiteSettings.objects.get_or_create(pk=1)
    return obj


def scoped_loans(user):
    """Loans this user is allowed to see (users tied to a branch only see that branch)."""
    qs = Loan.objects.select_related("officer")
    if user.branch:
        qs = qs.filter(branch=user.branch)
    return qs


def load_loans(user, basis="Date Issued"):
    """All visible loans with a `.x` attribute holding the computed figures."""
    s = get_settings()
    t = today()
    qs = scoped_loans(user).annotate(
        pay_sum=Coalesce(Sum("payments__amount"), Value(0), output_field=BigIntegerField()))
    loans = list(qs)
    for l in loans:
        l.x = rules.compute(
            total_due=l.total_due, paid=(l.amount_received or 0) + (l.pay_sum or 0),
            status=l.status, due=l.due_date, issued=l.date_issued, officer=l.officer_name,
            today=t, window=s.reminder_window_days, severe=s.severe_default_days, basis=basis)
        l.branch_name = BR.get(l.branch, l.branch)
    return loans


def compute_one(loan, user=None):
    """Computed figures for a single loan (used on the detail page)."""
    s = get_settings()
    paid = (loan.amount_received or 0) + (loan.payments.aggregate(t=Sum("amount"))["t"] or 0)
    return rules.compute(
        total_due=loan.total_due, paid=paid, status=loan.status, due=loan.due_date,
        issued=loan.date_issued, officer=loan.officer_name, today=today(),
        window=s.reminder_window_days, severe=s.severe_default_days)


def counts(loans):
    c = {f: {"n": 0, "out": 0} for f in rules.FLAGS}
    for l in loans:
        c[l.x.flag]["n"] += 1
        c[l.x.flag]["out"] += l.x.out
    return c


def alias_counts(raw):
    """Template-friendly keys (Django templates cannot use keys that contain spaces)."""
    return {"today": raw["DUE TODAY"], "soon": raw["DUE SOON"], "defl": raw["DEFAULTER"],
            "sev": raw["SEVERE DEFAULT"]}


def scope(loans, branch="All", officer="All"):
    return [l for l in loans
            if (branch == "All" or l.branch_name == branch)
            and (officer == "All" or l.x.officer == officer)]


def officer_names(loans):
    names = sorted({l.x.officer for l in loans})
    if "Unassigned" in names:
        names.remove("Unassigned")
        names.append("Unassigned")
    return names


def default_officer(user) -> str:
    return user.officer.name if getattr(user, "officer_id", None) else "All"


def alert_counts(user):
    """Cached (60s) counts used for the navigation badge."""
    key = f"alerts:{today()}:{user.branch}:{user.officer_id or 0}"
    data = cache.get(key)
    if data is None:
        loans = load_loans(user)
        loans = scope(loans, "All", default_officer(user))
        c = counts(loans)
        data = {
            "today": c["DUE TODAY"]["n"], "soon": c["DUE SOON"]["n"],
            "def": c["DEFAULTER"]["n"], "severe": c["SEVERE DEFAULT"]["n"],
            "today_out": c["DUE TODAY"]["out"], "def_out": c["DEFAULTER"]["out"],
            "severe_out": c["SEVERE DEFAULT"]["out"],
        }
        data["badge"] = data["today"] + data["def"] + data["severe"]
        data["total"] = data["badge"] + data["soon"]
        cache.set(key, data, 60)
    return data


# --------------------------------------------------------------------------
# Audit log
# --------------------------------------------------------------------------
def audit(user, action, obj=None, detail="", object_type=None, object_id=None, object_repr=None):
    AuditLog.objects.create(
        user=user if getattr(user, "pk", None) else None,
        user_name=getattr(user, "username", "") or "",
        action=action,
        object_type=object_type or (obj.__class__.__name__ if obj is not None else ""),
        object_id=str(object_id if object_id is not None else (getattr(obj, "pk", "") or "")),
        object_repr=(object_repr if object_repr is not None else (str(obj) if obj is not None else ""))[:255],
        detail=detail,
    )


# --------------------------------------------------------------------------
# CSV
# --------------------------------------------------------------------------
CSV_COLUMNS = ["Branch", "Client", "Officer", "Date issued", "Due date", "Principal", "Total due",
               "Paid", "Outstanding", "Days past due", "Alert flag", "Client contact",
               "Guarantor contact", "Status", "Recommended action"]
XLSX_COLUMNS = [column for column in CSV_COLUMNS if column != "Branch"]


def loans_csv_response(loans, name):
    resp = HttpResponse(content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="roziko-{name}-{today():%Y-%m-%d}.csv"'
    resp.write("﻿")  # BOM so Excel opens UTF-8 correctly
    w = csv.writer(resp)
    w.writerow(CSV_COLUMNS)
    for l in loans:
        x = l.x
        w.writerow([
            l.branch_name, l.client_name, x.officer,
            l.date_issued or "", l.due_date or "", l.principal or 0, x.td, x.paid, x.out,
            x.days if x.days is not None else "", x.flag, l.client_contact, l.guarantor_contact,
            x.status, x.reco,
        ])
    return resp


def loans_xlsx_response(loans, name="loans"):
    """Return a formatted Excel workbook with one worksheet per branch."""
    workbook = Workbook()
    workbook.remove(workbook.active)
    grouped = {}
    for loan in loans:
        grouped.setdefault(loan.branch_name or "Other", []).append(loan)

    ordered_branches = [branch for branch in ("Arua", "Gulu") if branch in grouped]
    ordered_branches += sorted(set(grouped) - set(ordered_branches))
    headers = XLSX_COLUMNS
    header_fill = PatternFill("solid", fgColor="14656C")
    header_font = Font(color="FFFFFF", bold=True)

    for branch in ordered_branches or ["No loans"]:
        sheet = workbook.create_sheet(title=branch[:31])
        sheet.append(headers)
        for cell in sheet[1]:
            cell.fill = header_fill
            cell.font = header_font
        for loan in grouped.get(branch, []):
            x = loan.x
            sheet.append([
                loan.client_name, x.officer,
                loan.date_issued, loan.due_date, loan.principal or 0, x.td, x.paid, x.out,
                x.days if x.days is not None else "", x.flag, loan.client_contact,
                loan.guarantor_contact, x.status, x.reco,
            ])
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        widths = [28, 20, 14, 14, 14, 14, 14, 14, 14, 18, 20, 22, 14, 70]
        for index, width in enumerate(widths, start=1):
            sheet.column_dimensions[get_column_letter(index)].width = width
        for cell in sheet["C"][1:] + sheet["D"][1:]:
            cell.number_format = "yyyy-mm-dd"
        for column in ("E", "F", "G", "H"):
            for cell in sheet[column][1:]:
                cell.number_format = "#,##0"

    output = BytesIO()
    workbook.save(output)
    response = HttpResponse(
        output.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="roziko-{name}-{today():%Y-%m-%d}.xlsx"'
    return response
