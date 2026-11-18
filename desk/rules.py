"""
Roziko business rules, ported 1:1 from the original Loan Desk page.

This module is deliberately free of Django imports so it can be unit-tested on
its own (see desk/tests/test_rules.py) and reused by the importer, the views
and the CSV export.
"""
from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date
from typing import Optional

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------
CANON = {
    "A": ["Sangai Moris", "Buga Joseph", "Agandru Tom"],
    "G": ["Oscar", "Patrick", "Tom", "Wamala", "Jennifer", "Opiyo"],
}

FLAGS = [
    "DUE TODAY", "DUE SOON", "DEFAULTER", "SEVERE DEFAULT",
    "Not Due", "CHECK DATE", "CHECK DATA", "Paid",
]
FLAG_CLASS = {
    "DUE TODAY": "TODAY", "DUE SOON": "SOON", "DEFAULTER": "DEFAULTER",
    "SEVERE DEFAULT": "SEVERE", "Not Due": "ND", "CHECK DATE": "CHECK",
    "CHECK DATA": "CHECK", "Paid": "PAID",
}
FLAG_LABEL = {"Paid": "PAID", "Not Due": "NOT DUE"}
ACTIONABLE = {"DUE TODAY", "DUE SOON", "DEFAULTER", "SEVERE DEFAULT"}

MONTHS = [
    "January", "February", "March", "April", "May", "June", "July",
    "August", "September", "October", "November", "December",
]

DEFAULT_WINDOW = 3
DEFAULT_SEVERE = 30


# --------------------------------------------------------------------------
# Text helpers
# --------------------------------------------------------------------------
def fmt_money(n) -> str:
    try:
        return f"{int(round(n or 0)):,}"
    except (TypeError, ValueError):
        return "0"


def fmt_date(d: Optional[date]) -> str:
    return d.strftime("%d %b %Y") if d else ""


def proper(s: str) -> str:
    """'oscar WAMALA' -> 'Oscar Wamala' (same as the original proper())."""
    return re.sub(r"(^|\s)\S", lambda m: m.group(0).upper(), s.lower())


def normalise_name(s) -> str:
    return " ".join(str(s or "").split())


def levenshtein(a: str, b: str) -> int:
    m, n = len(a), len(b)
    prev = list(range(n + 1))
    for i in range(1, m + 1):
        cur = [i] + [0] * n
        for j in range(1, n + 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1,
                         prev[j - 1] + (0 if a[i - 1] == b[j - 1] else 1))
        prev = cur
    return prev[n]


def clean_officer(raw, branch: str) -> str:
    """Map a messy officer entry onto the canonical officer list for a branch."""
    t = normalise_name(raw)
    if not t:
        return "Unassigned"
    low = t.lower()
    cands = CANON.get(branch, [])
    hit = next((c for c in cands if c.lower() == low), None)
    if hit is None:
        hit = next((c for c in cands if levenshtein(low, c.lower()) <= 3), None)
    if hit is None and len(low) >= 3:
        toks = [w for w in low.split(" ") if len(w) >= 3]
        hit = next(
            (c for c in cands
             if any(levenshtein(w, ct) <= 1 for ct in c.lower().split(" ") for w in toks)),
            None,
        )
    if hit is None and len(low) <= 2:
        m = [c for c in cands if c.lower().startswith(low[0])]
        if len(m) == 1:
            hit = m[0]
    return hit or proper(t)


def clean_status(raw, out: float) -> str:
    s = str(raw if raw is not None else "").lower()
    if "comp" in s:
        return "Completed"
    if "def" in s or "deaf" in s:
        return "Default"
    if "cur" in s or "go" in s or "issu" in s:
        return "Current"
    return "Completed" if out <= 0 else "Current"


_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")


def parse_date(value) -> Optional[date]:
    """ISO date string -> date. Years outside 2020-2030 are treated as invalid."""
    if isinstance(value, date):
        return value if 2020 <= value.year <= 2030 else None
    if not isinstance(value, str):
        return None
    m = _DATE_RE.match(value)
    if not m:
        return None
    y, mo, d = int(m[1]), int(m[2]), int(m[3])
    if not 2020 <= y <= 2030:
        return None
    try:
        return date(y, mo, d)
    except ValueError:
        return None


def _month_back(d: date) -> date:
    y, m = (d.year, d.month - 1) if d.month > 1 else (d.year - 1, 12)
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


# --------------------------------------------------------------------------
# Recommendation text
# --------------------------------------------------------------------------
def recommendation(flag: str, days: Optional[int], out: float, due: Optional[date],
                   severe: int = DEFAULT_SEVERE) -> str:
    m = fmt_money(out)
    if flag == "Paid":
        return "No action. Loan fully settled."
    if flag == "CHECK DATE":
        return "Repayment date is missing or invalid. Verify in the loan file and correct it (Edit loan)."
    if flag == "CHECK DATA":
        return "Principal or interest is missing. Verify in the loan file."
    if flag == "Not Due":
        return "Monitor. Payment is not due yet."
    if flag == "DUE SOON":
        return (f"Courtesy reminder: call the client and guarantor. {m} is due "
                f"{fmt_date(due)}. Confirm how they will pay.")
    if flag == "DUE TODAY":
        return f"Due today: call the client this morning, visit by midday, collect {m} and issue a receipt."
    d = days or 0
    if d <= 7:
        return "1-7 days late: call client and guarantor today. Agree a firm pay-by date and record it."
    if d <= 14:
        return ("8-14 days late: field visit within 48 hours with the guarantor. "
                "Issue a written demand and offer a part-payment plan.")
    if d < severe:
        return ("15+ days late: escalate to the Branch Manager. Send a formal demand notice "
                "and negotiate a restructure or part-payment this week.")
    if d < 90:
        return ("Severe default: invoke the guarantor, follow up on collateral and send a final "
                "demand letter. Review weekly with the Branch Manager.")
    return "90+ days: recovery or legal action. Enforce the guarantee and assess provisioning or write-off."


# --------------------------------------------------------------------------
# The calculation
# --------------------------------------------------------------------------
@dataclass
class Calc:
    due: Optional[date]
    issued: Optional[date]
    td: int
    paid: int
    out: int
    days: Optional[int]
    flag: str
    status: str
    officer: str
    pd: Optional[date]
    yr: Optional[int]
    mo: Optional[int]
    pri: int
    reco: str

    @property
    def flag_class(self) -> str:
        return FLAG_CLASS[self.flag]

    @property
    def flag_label(self) -> str:
        return FLAG_LABEL.get(self.flag, self.flag)

    @property
    def is_default(self) -> bool:
        return self.flag in ("DEFAULTER", "SEVERE DEFAULT")

    @property
    def late_text(self) -> str:
        d = self.days
        if d is None:
            return ""
        if d > 0:
            return f"{d} day{'s' if d > 1 else ''} overdue"
        if d == 0:
            return "due today"
        return f"due in {-d} day{'s' if d < -1 else ''}"


def compute(*, total_due: int, paid: int, status: str, due: Optional[date],
            issued: Optional[date], officer: str, today: date,
            window: int = DEFAULT_WINDOW, severe: int = DEFAULT_SEVERE,
            basis: str = "Date Issued") -> Calc:
    td = int(total_due or 0)
    paid = int(paid or 0)
    comp = "comp" in (status or "").lower()
    out = 0 if comp else max(0, td - paid)
    days = (today - due).days if (out > 0 and due) else None

    if not comp and out <= 0 and td <= 0:
        flag = "CHECK DATA"
    elif out <= 0:
        flag = "Paid"
    elif not due:
        flag = "CHECK DATE"
    elif days >= severe:
        flag = "SEVERE DEFAULT"
    elif days >= 1:
        flag = "DEFAULTER"
    elif days == 0:
        flag = "DUE TODAY"
    elif days >= -window:
        flag = "DUE SOON"
    else:
        flag = "Not Due"

    # A loan that is fully paid is shown as Completed whatever the stored status says.
    final_status = "Completed" if (comp or (out <= 0 and td > 0)) else clean_status(status, out)

    if basis == "Due Date":
        pd = due
    else:
        pd = issued or (_month_back(due) if due else None)

    if flag == "DUE TODAY":
        pri = 4000
    elif flag == "DEFAULTER":
        pri = 3000 + days
    elif flag == "DUE SOON":
        pri = 2100 + days
    elif flag == "SEVERE DEFAULT":
        pri = 1000 + min(days, 999)
    else:
        pri = 0

    return Calc(
        due=due, issued=issued, td=td, paid=paid, out=out, days=days, flag=flag,
        status=final_status, officer=officer or "Unassigned", pd=pd,
        yr=pd.year if pd else None, mo=(pd.month - 1) if pd else None, pri=pri,
        reco=recommendation(flag, days, out, due, severe),
    )
