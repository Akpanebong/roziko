from functools import wraps
import secrets

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import SetPasswordForm
from django.contrib.auth.tokens import default_token_generator
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.core.cache import cache
from django.core.mail import send_mail
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes
from django.views.decorators.http import require_POST

from . import permissions, rules, services
from .forms import (FollowUpForm, LOAN_TYPES, LoanForm, PaymentForm, RecommendationForm,
                    CredentialChangeForm, SettingsForm, StyledPasswordResetForm, UserCreateForm, UserEditForm)
from .models import (AuditLog, FOLLOWUP_OUTCOMES, FollowUp, Loan, Officer, Payment, Recommendation, Role, User)
from .services import BR, audit, counts, load_loans, officer_names, scope


# --------------------------------------------------------------------------
# Access control
# --------------------------------------------------------------------------
def perm_required(*keys):
    """Login + at least one of the listed permissions (see permissions.py)."""
    def deco(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            if not any(request.user.can(k) for k in keys):
                raise PermissionDenied
            return view(request, *args, **kwargs)
        return wrapper
    return deco


def visible_loan_or_404(request, pk):
    try:
        return services.scoped_loans(request.user).get(pk=pk)
    except Loan.DoesNotExist:
        raise Http404("Loan not found")


def officer_datalists():
    out = {"A": [], "G": [], "ALL": []}
    for o in Officer.objects.order_by("name"):
        out.setdefault(o.branch, []).append(o.name)
        if o.name not in out["ALL"]:
            out["ALL"].append(o.name)
    return out


# --------------------------------------------------------------------------
# Filters (GET parameters)
# --------------------------------------------------------------------------
def dash_filters(request):
    g = request.GET.get
    return {k: g(k, "All") or "All" for k in ("branch", "year", "month", "officer", "status", "flag")} | {
        "basis": g("basis", "Date Issued") if g("basis") in ("Date Issued", "Due Date") else "Date Issued"}


def _month_ok(l, F, skip):
    if skip == "month" or F["month"] == "All":
        return True
    return F["month"] in rules.MONTHS and l.x.mo == rules.MONTHS.index(F["month"])


def matches(l, F, skip=None):
    x = l.x
    return ((skip == "branch" or F["branch"] == "All" or l.branch_name == F["branch"])
            and (F["year"] == "All" or str(x.yr) == F["year"])
            and _month_ok(l, F, skip)
            and (skip == "officer" or F["officer"] == "All" or x.officer == F["officer"])
            and (F["status"] == "All" or x.status == F["status"])
            and (F["flag"] == "All" or x.flag == F["flag"]))


# --------------------------------------------------------------------------
# Dashboard
# --------------------------------------------------------------------------
FLAG_COLOUR = {"TODAY": "var(--tod-fg)", "SOON": "var(--soon-fg)", "DEFAULTER": "var(--def-fg)",
               "SEVERE": "var(--sev-bg)", "ND": "var(--mut)", "CHECK": "var(--chk-fg)",
               "PAID": "var(--good)"}


@perm_required("view_data")
def dashboard(request):
    F = dash_filters(request)
    loans = load_loans(request.user, F["basis"])
    s_ = services.get_settings()
    sel = [l for l in loans if matches(l, F)]
    P = sum(l.principal or 0 for l in sel)
    TD = sum(l.x.td for l in sel)
    PD = sum(l.x.paid for l in sel)
    OUT = sum(l.x.out for l in sel)

    sc = scope(loans, F["branch"], F["officer"])
    c = services.alias_counts(counts(sc))
    at_risk = c["defl"]["out"] + c["sev"]["out"]
    tot_out = sum(l.x.out for l in sc)
    act = sum(c[k]["n"] for k in c)

    # month chart ignores the Month filter; officer chart ignores the Officer filter
    ml = [l for l in loans if matches(l, F, "month")]
    mon = [[l for l in ml if l.x.mo == i] for i in range(12)]
    ol = [l for l in loans if matches(l, F, "officer")]
    offs = []
    for n in officer_names(loans):
        ls = [l for l in ol if l.x.officer == n]
        if not ls:
            continue
        td, pd = sum(l.x.td for l in ls), sum(l.x.paid for l in ls)
        offs.append({"name": n, "loans": len(ls), "principal": sum(l.principal or 0 for l in ls),
                     "out": sum(l.x.out for l in ls), "defaulters": sum(1 for l in ls if l.x.is_default),
                     "rate": (pd / td * 100) if td else 0})
    fc = counts(sel)

    reminder_rows = [l for l in sc if l.x.flag in rules.ACTIONABLE]
    reminder_rows.sort(key=lambda l: (-l.x.pri, -l.x.out, l.x.due or services.today()))
    month_rows = []
    for i, month in enumerate(rules.MONTHS):
        ml_rows = [l for l in ml if l.x.mo == i]
        month_rows.append({
            "name": month,
            "loans": len(ml_rows),
            "principal": sum(l.principal or 0 for l in ml_rows),
            "collected": sum(l.x.paid for l in ml_rows),
            "outstanding": sum(l.x.out for l in ml_rows),
        })
    flag_rows = [{"name": flag, "loans": fc[flag]["n"], "outstanding": fc[flag]["out"]}
                 for flag in rules.FLAGS if fc[flag]["n"]]

    chart = {
        "months": [m[:3] for m in rules.MONTHS],
        "series": [
            {"n": "Principal", "c": "--ch1", "v": [sum(l.principal or 0 for l in m) for m in mon]},
            {"n": "Collected", "c": "--ch2", "v": [sum(l.x.paid for l in m) for m in mon]},
            {"n": "Outstanding", "c": "--ch3", "v": [sum(l.x.out for l in m) for m in mon]},
        ],
        "officers": sorted(({"l": o["name"], "v": o["out"]} for o in offs), key=lambda i: -i["v"]),
        "flags": [{"l": f, "v": fc[f]["n"], "c": FLAG_COLOUR[rules.FLAG_CLASS[f]]}
                  for f in rules.FLAGS if f != "Paid"],
    }

    show_alert = False
    t = services.today().isoformat()
    if request.session.get("alert_day") != t:
        request.session["alert_day"] = t
        show_alert = True
    me = services.alert_counts(request.user) if show_alert else None

    ctx = {
        "F": F, "years": sorted({str(l.x.yr) for l in loans if l.x.yr}), "months": rules.MONTHS,
        "officers": officer_names(loans), "flags": rules.FLAGS, "n_loans": len(sel),
        "principal_issued": P, "TD": TD, "PD": PD, "OUT": OUT, "rate": f"{PD / TD * 100:.1f}%" if TD else "0.0%",
        "c": c, "at_risk": at_risk, "par": f"{at_risk / tot_out * 100:.1f}%" if tot_out else "0.0%",
        "act": act, "window": s_.reminder_window_days, "severe": s_.severe_default_days,
        "offs": offs, "chart_json": chart, "show_alert": show_alert and me and me["total"], "me": me,
        "me_name": services.default_officer(request.user), "reminder_rows": reminder_rows[:25],
        "reminder_total": len(reminder_rows), "month_rows": month_rows, "flag_rows": flag_rows,
    }
    return render(request, "desk/dashboard.html", ctx)


# --------------------------------------------------------------------------
# Reminders
# --------------------------------------------------------------------------
RVIEWS = {
    "Open actionable": lambda f: f in rules.ACTIONABLE,
    "Due today": lambda f: f == "DUE TODAY",
    "Due soon": lambda f: f == "DUE SOON",
    "Defaulters (all)": lambda f: f in ("DEFAULTER", "SEVERE DEFAULT"),
    "Fresh defaulters": lambda f: f == "DEFAULTER",
    "Severe default": lambda f: f == "SEVERE DEFAULT",
}


def reminder_list(request):
    g = request.GET.get
    view = g("view") if g("view") in RVIEWS else "Open actionable"
    branch = g("branch", "All") or "All"
    officer = g("officer")
    if officer is None:
        officer = services.default_officer(request.user)
    elif officer == "":
        officer = "All"
    q = (g("q") or "").strip().lower()
    loans = load_loans(request.user)
    base = scope(loans, branch, officer)
    rows = [l for l in base if RVIEWS[view](l.x.flag)
            and (not q or q in l.client_name.lower() or q in (l.client_contact or "")
                 or q in (l.guarantor_contact or ""))]
    rows.sort(key=lambda l: (-l.x.pri, -l.x.out))
    return loans, base, rows, {"view": view, "branch": branch, "officer": officer, "q": g("q") or ""}


@perm_required("view_data")
def reminders(request):
    loans, base, rows, R = reminder_list(request)
    c = services.alias_counts(counts(base))
    page = Paginator(rows, 30).get_page(request.GET.get("page"))
    # last follow-up per loan on this page
    ids = [l.pk for l in page]
    last = {}
    for fu in FollowUp.objects.filter(loan_id__in=ids).select_related("by").order_by("created_at"):
        last[fu.loan_id] = fu
    t = services.today()
    for l in page:
        l.last_fu = last.get(l.pk)
        l.promise_active = bool(l.last_fu and l.last_fu.promise_date and l.last_fu.promise_date >= t)
    ctx = {
        "R": R, "views": list(RVIEWS), "officers": officer_names(loans), "page": page, "c": c,
        "n_alert": c["today"]["n"] + c["defl"]["n"] + c["sev"]["n"],
        "total": len(rows), "outcomes": FOLLOWUP_OUTCOMES,
    }
    return render(request, "desk/reminders.html", ctx)


@perm_required("export")
def export_reminders(request):
    _, _, rows, _ = reminder_list(request)
    services.audit(request.user, "export", object_type="Reminders", object_repr=f"{len(rows)} rows")
    return services.loans_csv_response(rows, "reminders")


# --------------------------------------------------------------------------
# Loans list / detail
# --------------------------------------------------------------------------
SORTS = {
    "client": lambda l: l.client_name.lower(), "officer": lambda l: l.x.officer,
    "due": lambda l: l.x.due.toordinal() if l.x.due else 0,
    "issued": lambda l: l.x.issued.toordinal() if l.x.issued else 0,
    "principal": lambda l: l.principal or 0, "td": lambda l: l.x.td, "paid": lambda l: l.x.paid,
    "out": lambda l: l.x.out, "days": lambda l: l.x.days if l.x.days is not None else -10 ** 9,
    "pri": lambda l: (l.x.pri, l.x.out), "branch": lambda l: l.branch,
}
LOAN_COLS = [("branch", "Branch", False), ("client", "Client", False), ("officer", "Officer", False),
             ("issued", "Issued", False), ("due", "Due", False), ("principal", "Principal", True),
             ("td", "Total due", True), ("paid", "Paid", True), ("out", "Outstanding", True),
             ("days", "Days late", True), ("pri", "Alert", False)]


def filtered_loans(request):
    g = request.GET.get
    F = {"branch": g("branch", "All") or "All", "officer": g("officer", "All") or "All",
         "flag": g("flag", "All") or "All", "status": g("status", "All") or "All",
         "q": (g("q") or "").strip()}
    loans = load_loans(request.user)
    q = F["q"].lower()
    rows = [l for l in loans
            if (F["branch"] == "All" or l.branch_name == F["branch"])
            and (F["officer"] == "All" or l.x.officer == F["officer"])
            and (F["flag"] == "All" or l.x.flag == F["flag"])
            and (F["status"] == "All" or l.x.status == F["status"])
            and (not q or q in l.client_name.lower() or q in (l.client_contact or "")
                 or q in (l.guarantor_contact or "") or str(l.serial_no) == q)]
    sort = g("sort") if g("sort") in SORTS else "pri"
    desc = g("dir", "desc" if sort not in ("client", "officer", "branch") else "asc") != "asc"
    rows.sort(key=SORTS[sort], reverse=desc)
    F.update(sort=sort, dir="desc" if desc else "asc")
    return loans, rows, F


@perm_required("view_data")
def loan_list(request):
    loans, rows, F = filtered_loans(request)
    page = Paginator(rows, 50).get_page(request.GET.get("page"))
    return render(request, "desk/loan_list.html", {
        "F": F, "page": page, "total": len(rows), "cols": LOAN_COLS,
        "officers": officer_names(loans), "flags": rules.FLAGS})


@perm_required("export")
def export_loans(request):
    _, rows, filters = filtered_loans(request)
    services.audit(request.user, "export", object_type="Loans", object_repr=f"{len(rows)} rows")
    branch_name = filters["branch"] if filters["branch"] in ("Arua", "Gulu") else "All-branches"
    return services.loans_xlsx_response(rows, f"loans-{branch_name}")


@perm_required("view_data")
def loan_detail(request, pk):
    loan = visible_loan_or_404(request, pk)
    x = services.compute_one(loan)
    user = request.user
    hist = []
    hist.append((loan.created_at, loan.created_by.display_name if loan.created_by else "",
                 "Imported from the Excel tracker" if loan.legacy_id else "Loan created"))
    for p in loan.payments.select_related("recorded_by"):
        hist.append((p.created_at, p.recorded_by.display_name if p.recorded_by else "",
                     f"Payment of {rules.fmt_money(p.amount)} UGX received on {rules.fmt_date(p.paid_on)}"
                     + (f" (receipt {p.receipt_no})" if p.receipt_no else "")))
    for f in loan.followups.select_related("by"):
        hist.append((f.created_at, f.by.display_name if f.by else "",
                     f"Follow-up: {f.outcome}"
                     + (f" (pay-by date {rules.fmt_date(f.promise_date)})" if f.promise_date else "")
                     + (f". {f.note}" if f.note else "")))
    recs = []
    if user.can("view_recommendations"):
        recs = list(loan.recommendations.select_related("by"))
        for r in recs:
            hist.append((r.created_at, r.by.display_name if r.by else "", f"Recommendation: {r.title}"))
    for a in AuditLog.objects.filter(object_type="Loan", object_id=str(loan.pk)).exclude(action__in=["create", "payment"]):
        hist.append((a.created_at, a.user_name, f"{a.action.capitalize()}: {a.detail}" if a.detail else a.action.capitalize()))
    hist.sort(key=lambda h: h[0], reverse=True)

    ctx = {
        "loan": loan, "x": x, "history": hist, "recs": recs,
        "payments": loan.payments.select_related("recorded_by"),
        "pay_form": PaymentForm(initial={"paid_on": services.today(), "amount": x.out or None}),
        "fu_form": FollowUpForm(), "rec_form": RecommendationForm(),
        "branch_name": BR.get(loan.branch),
    }
    return render(request, "desk/loan_detail.html", ctx)


# --------------------------------------------------------------------------
# Loan add / edit / delete
# --------------------------------------------------------------------------
def _loan_form_ctx(form, title, loan=None):
    return {"form": form, "title": title, "loan": loan, "officer_lists": officer_datalists(),
            "loan_types": LOAN_TYPES}


def _json_settings():
    s = services.get_settings()
    return {"rate": float(s.interest_rate_percent), "termA": s.term_days_arua, "termG": s.term_days_gulu}


@perm_required("add_loan")
def loan_add(request):
    form = LoanForm(request.POST or None, initial={"date_issued": services.today()})
    if request.method == "POST" and form.is_valid():
        loan = form.save(commit=False)
        loan.created_by = request.user
        loan.status = "Current"
        loan.save()
        audit(request.user, "create", loan, f"principal {loan.principal:,}, due {loan.due_date}")
        if form.new_officer:
            messages.info(request, f"New loan officer “{form.new_officer.name}” added to the {BR[loan.branch]} list.")
            audit(request.user, "create", form.new_officer)
        messages.success(request, f"Loan for {loan.client_name} saved.")
        return redirect(loan)
    ctx = _loan_form_ctx(form, "New loan")
    ctx["js_settings"] = _json_settings()
    return render(request, "account/loan_form.html", ctx)


@perm_required("edit_loan")
def loan_edit(request, pk):
    loan = visible_loan_or_404(request, pk)
    form = LoanForm(request.POST or None, instance=loan, is_edit=True)
    if request.method == "POST" and form.is_valid():
        changed = ", ".join(form.changed_data)
        loan = form.save()
        audit(request.user, "edit", loan, f"changed: {changed}" if changed else "no changes")
        if form.new_officer:
            messages.info(request, f"New loan officer “{form.new_officer.name}” added to the {BR[loan.branch]} list.")
        messages.success(request, "Loan updated.")
        return redirect(loan)
    ctx = _loan_form_ctx(form, f"Edit loan: {loan.client_name}", loan)
    ctx["js_settings"] = None
    return render(request, "account/loan_form.html", ctx)


@perm_required("delete_loan")
def loan_delete(request, pk):
    loan = visible_loan_or_404(request, pk)
    x = services.compute_one(loan)
    if request.method == "POST":
        snap = (f"{loan.client_name}; officer {loan.officer_name}; principal {loan.principal:,}; "
                f"total due {loan.total_due:,}; paid {x.paid:,}; due {loan.due_date}")
        n_pay = loan.payments.count()
        repr_, pk_ = str(loan), loan.pk
        loan.delete()
        audit(request.user, "delete", object_type="Loan", object_id=pk_, object_repr=repr_,
              detail=f"{snap}; {n_pay} payment(s) removed with it")
        messages.success(request, f"Loan for {repr_} deleted.")
        return redirect("loan_list")
    return render(request, "desk/confirm_delete.html", {
        "what": f"the loan for {loan.client_name}", "loan": loan, "x": x,
        "extra": f"This also removes {loan.payments.count()} payment(s), {loan.followups.count()} follow-up(s) "
                 f"and {loan.recommendations.count()} recommendation(s) attached to it.",
        "cancel": loan.get_absolute_url()})


# --------------------------------------------------------------------------
# Payments, follow-ups
# --------------------------------------------------------------------------
def _safe_next(request):
    nxt = request.POST.get("next", "")
    return nxt if nxt.startswith("/") and not nxt.startswith("//") else None


def _back(request, loan):
    return redirect(_safe_next(request) or loan)


@perm_required("add_payment")
@require_POST
def payment_add(request, pk):
    loan = visible_loan_or_404(request, pk)
    form = PaymentForm(request.POST)
    if form.is_valid():
        p = form.save(commit=False)
        p.loan, p.recorded_by = loan, request.user
        p.save()
        audit(request.user, "payment", loan, f"{p.amount:,} UGX on {p.paid_on}")
        messages.success(request, f"Payment of {p.amount:,} UGX saved. The balance has been updated.")
    else:
        messages.error(request, "Payment not saved: " + "; ".join(
            f"{f}: {' '.join(e)}" for f, e in form.errors.items()))
    return _back(request, loan)


@perm_required("delete_payment")
def payment_delete(request, pk):
    p = get_object_or_404(Payment.objects.select_related("loan"), pk=pk)
    loan = visible_loan_or_404(request, p.loan_id)
    if request.method == "POST":
        audit(request.user, "delete payment", loan, f"{p.amount:,} UGX of {p.paid_on} (receipt {p.receipt_no or '-'})",
              object_type="Loan")
        p.delete()
        messages.success(request, "Payment deleted.")
        return redirect(loan)
    return render(request, "desk/confirm_delete.html", {
        "what": f"the payment of {p.amount:,} UGX received on {rules.fmt_date(p.paid_on)} "
                f"for {loan.client_name}", "extra": "The loan balance will go back up by this amount.",
        "cancel": loan.get_absolute_url()})


@perm_required("log_followup")
@require_POST
def followup_add(request, pk):
    loan = visible_loan_or_404(request, pk)
    form = FollowUpForm(request.POST)
    if form.is_valid():
        f = form.save(commit=False)
        f.loan, f.by = loan, request.user
        f.save()
        messages.success(request, "Follow-up saved.")
    else:
        messages.error(request, "Follow-up not saved. Check the form.")
    return _back(request, loan)


# --------------------------------------------------------------------------
# Recommendations
# --------------------------------------------------------------------------
@perm_required("view_recommendations")
def recommendation_list(request):
    status = request.GET.get("status", "all")
    qs = Recommendation.objects.select_related("loan", "by", "reviewed_by")
    if request.user.branch:
        qs = qs.filter(Q(loan__branch=request.user.branch) | Q(loan__isnull=True))
    if status in ("open", "reviewed"):
        qs = qs.filter(status=status)
    page = Paginator(qs, 25).get_page(request.GET.get("page"))
    return render(request, "desk/recommendations.html", {
        "page": page, "status": status, "form": RecommendationForm()})


@perm_required("add_recommendation")
@require_POST
def recommendation_add(request, pk=None):
    loan = visible_loan_or_404(request, pk) if pk else None
    form = RecommendationForm(request.POST)
    if form.is_valid():
        r = form.save(commit=False)
        r.loan, r.by = loan, request.user
        r.save()
        audit(request.user, "recommend", r, r.title, object_type="Recommendation")
        messages.success(request, "Recommendation saved.")
    else:
        messages.error(request, "Recommendation not saved. Add a title and the recommendation text.")
    return redirect(loan) if loan else redirect("recommendation_list")


@perm_required("add_recommendation", "review_recommendations")
def recommendation_delete(request, pk):
    r = get_object_or_404(Recommendation, pk=pk)
    if not (request.user.can("review_recommendations") or r.by_id == request.user.pk):
        raise PermissionDenied
    if request.method == "POST":
        audit(request.user, "delete", r, object_type="Recommendation")
        r.delete()
        messages.success(request, "Recommendation deleted.")
        return redirect("recommendation_list")
    return render(request, "desk/confirm_delete.html", {
        "what": f"the recommendation “{r.title}”", "extra": "", "cancel": "/recommendations/"})


@perm_required("review_recommendations")
@require_POST
def recommendation_toggle(request, pk):
    r = get_object_or_404(Recommendation, pk=pk)
    if r.status == Recommendation.Status.OPEN:
        r.status, r.reviewed_by = Recommendation.Status.REVIEWED, request.user
    else:
        r.status, r.reviewed_by = Recommendation.Status.OPEN, None
    r.save()
    return redirect(_safe_next(request) or "recommendation_list")


# --------------------------------------------------------------------------
# Users
# --------------------------------------------------------------------------
def _other_active_managers(exclude_pk):
    return User.objects.filter(is_active=True).exclude(pk=exclude_pk).filter(
        role=Role.MANAGER).exists() or User.objects.filter(
        is_active=True, is_superuser=True).exclude(pk=exclude_pk).exists()


def _generated_credentials(first_name, last_name, preferred=""):
    """Return a unique username and a strong temporary password."""
    base = "-".join(part.lower() for part in (first_name, last_name) if part).replace(" ", "-")
    base = "".join(ch for ch in base if ch.isalnum() or ch in "._-") or "user"
    # The optional legacy value keeps API callers compatible; the form no
    # longer exposes it, so normal user creation is always automatic.
    username = preferred.strip()[:150] if preferred.strip() else base[:138]
    while User.objects.filter(username__iexact=username).exists():
        username = f"{base[:138]}-{secrets.token_hex(3)}"
    return username, secrets.token_urlsafe(12)


def _send_new_user_credentials(request, user, temporary_password):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    login_url = request.build_absolute_uri(reverse("login"))
    reset_url = request.build_absolute_uri(reverse("password_reset_confirm", args=[uid, token]))
    context = {"user": user, "temporary_password": temporary_password,
               "login_url": login_url, "reset_url": reset_url}
    send_mail(
        subject="Your Roziko Loan Desk account",
        message=render_to_string("account/emails/new_user_credentials.txt", context),
        from_email=None,
        recipient_list=[user.email],
        html_message=render_to_string("account/emails/new_user_credentials.html", context),
    )


@login_required
def account_credentials(request):
    form = CredentialChangeForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        audit(request.user, "change credentials", request.user, object_type="User")
        messages.success(request, "Your username and password have been updated.")
        return redirect("dashboard")
    return render(request, "account/credentials.html", {"form": form})


@perm_required("manage_users")
def user_list(request):
    users = User.objects.select_related("officer").order_by("role", "username")
    matrix = []
    for key, label in permissions.PERMISSION_LABELS.items():
        matrix.append((label, [key in permissions.perms_for(r) for r, _ in permissions.ROLE_CHOICES]))
    return render(request, "desk/user_list.html", {
        "users": users, "roles": permissions.ROLE_CHOICES, "matrix": matrix})


@perm_required("create_users")
def user_add(request):
    form = UserCreateForm(request.POST or None, creator=request.user)
    if request.method == "POST" and form.is_valid():
        username, temporary_password = _generated_credentials(
            form.cleaned_data["first_name"], form.cleaned_data["last_name"],
            request.POST.get("username", ""))
        u = form.save(commit=False)
        u.username = username
        u.set_password(temporary_password)
        u.save()
        if u.email:
            _send_new_user_credentials(request, u, temporary_password)
            messages.success(request, f"User {u.username} created. Login instructions were sent to {u.email}.")
        else:
            messages.warning(request, f"User {u.username} created without an email address; no login instructions were sent.")
        audit(request.user, "create user", u, f"role {u.get_role_display()}", object_type="User")
        messages.success(request, f"User “{u.username}” created as {u.get_role_display()}.")
        return redirect("user_list" if request.user.can("manage_users") else "dashboard")
    return render(request, "account/user_form.html", {
        "form": form, "title": "Add user", "officer_lists": officer_datalists(), "is_new": True})


@perm_required("manage_users")
def user_edit(request, pk):
    u = get_object_or_404(User, pk=pk)
    form = UserEditForm(request.POST or None, instance=u)
    if request.method == "POST" and form.is_valid():
        new_role, active = form.cleaned_data["role"], form.cleaned_data["is_active"]
        if u.pk == request.user.pk and (not active or new_role != Role.ADVISOR) and not u.is_superuser:
            form.add_error(None, "You cannot remove your own Advisory Board access or deactivate yourself.")
        elif (u.role == Role.MANAGER and (new_role != Role.MANAGER or not active)
              and not _other_active_managers(u.pk)):
            form.add_error(None, "There must be at least one active Branch Manager.")
        else:
            form.save()
            audit(request.user, "edit user", u, f"changed: {', '.join(form.changed_data)}", object_type="User")
            messages.success(request, "User updated.")
            return redirect("user_list")
    return render(request, "account/user_form.html", {
        "form": form, "title": f"Edit user: {u.username}", "officer_lists": officer_datalists(),
        "target": u, "is_new": False})


@perm_required("manage_users")
def user_password(request, pk):
    u = get_object_or_404(User, pk=pk)
    form = SetPasswordForm(u, request.POST or None)
    for f in form.fields.values():
        f.widget.attrs["class"] = "in"
    if request.method == "POST" and form.is_valid():
        form.save()
        audit(request.user, "reset password", u, object_type="User")
        messages.success(request, f"Password changed for {u.username}.")
        return redirect("user_list")
    return render(request, "account/user_password.html", {"form": form, "target": u})


@perm_required("manage_users")
def user_delete(request, pk):
    u = get_object_or_404(User, pk=pk)
    blocked = None
    if u.pk == request.user.pk:
        blocked = "You cannot delete your own account."
    elif u.role == Role.MANAGER and not _other_active_managers(u.pk):
        blocked = "There must be at least one active Branch Manager."
    if request.method == "POST" and not blocked:
        audit(request.user, "delete user", object_type="User", object_id=u.pk,
              object_repr=u.username, detail=f"role {u.get_role_display()}")
        name = u.username
        u.delete()
        messages.success(request, f"User “{name}” deleted.")
        return redirect("user_list")
    return render(request, "desk/confirm_delete.html", {
        "what": f"the user “{u.username}” ({u.get_role_display()})", "blocked": blocked,
        "extra": "Their recorded payments and notes stay, but are no longer linked to a name.",
        "cancel": "/users/"})


# --------------------------------------------------------------------------
# Settings and audit
# --------------------------------------------------------------------------
@perm_required("settings")
def site_settings(request):
    form = SettingsForm(request.POST or None, instance=services.get_settings())
    if request.method == "POST" and form.is_valid():
        form.save()
        audit(request.user, "edit settings", object_type="Settings",
              detail=f"changed: {', '.join(form.changed_data)}")
        cache.clear()
        messages.success(request, "Rules saved.")
        return redirect("site_settings")
    return render(request, "account/settings.html", {"form": form})


@perm_required("view_audit")
def audit_log(request):
    qs = AuditLog.objects.all()
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(user_name__icontains=q) | Q(object_repr__icontains=q) | Q(action__icontains=q))
    page = Paginator(qs, 50).get_page(request.GET.get("page"))
    return render(request, "desk/audit.html", {"page": page, "q": q})
