from django import forms
from django.contrib.auth.forms import PasswordResetForm, SetPasswordForm

from . import permissions, rules
from .models import (Branch, FollowUp, Loan, Officer, Payment, Recommendation, Role,
                     SiteSettings, User)
from .services import get_settings

LOAN_TYPES = ["Business loan", "Salary loan", "Personal loan", "School fees loan",
              "Rental loan", "Supply loan"]


class StyledMixin:
    """Adds the app's `in` CSS class to every input."""

    def _style(self):
        for f in self.fields.values():
            if isinstance(f.widget, forms.CheckboxInput):
                continue
            f.widget.attrs["class"] = (f.widget.attrs.get("class", "") + " in").strip()


def date_input():
    return forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")


# --------------------------------------------------------------------------
# Officer name: pick from the list OR type a new one
# --------------------------------------------------------------------------
def resolve_officer(name: str, branch: str):
    """Find the officer for this branch (case-insensitive) or create a new one.
    Returns (officer_or_None, created_bool)."""
    name = rules.normalise_name(name)
    if not name:
        return None, False
    found = Officer.objects.filter(branch=branch, name__iexact=name).first()
    if found:
        return found, False
    return Officer.objects.create(branch=branch, name=rules.proper(name)), True


class OfficerNameInput(forms.TextInput):
    """Text box wired to a <datalist>: choose a name from the drop-down or type a new one."""

    def __init__(self, attrs=None):
        base = {"list": "officers-A", "autocomplete": "off",
                "placeholder": "Select from the list or type a new name", "data-officer-input": "1"}
        base.update(attrs or {})
        super().__init__(base)


# --------------------------------------------------------------------------
# Loans
# --------------------------------------------------------------------------
class LoanForm(StyledMixin, forms.ModelForm):
    officer_name = forms.CharField(
        label="Loan officer", max_length=80, required=False, widget=OfficerNameInput(),
        help_text="Pick a name from the list, or type the name of an officer who is not listed.")

    class Meta:
        model = Loan
        fields = ["branch", "client_name", "date_issued", "due_date", "principal", "interest",
                  "processing_fee", "total_due", "client_contact", "guarantor_contact", "loan_type",
                  "status", "amount_received", "penalty", "remarks"]
        widgets = {
            "date_issued": date_input(), "due_date": date_input(),
            "loan_type": forms.TextInput(attrs={"list": "loan-types"}),
            "client_contact": forms.TextInput(attrs={"inputmode": "tel"}),
            "total_due": forms.NumberInput(attrs={"min": 0}),
        }

    def __init__(self, *args, is_edit=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.is_edit = is_edit
        self.new_officer = None
        if not is_edit:
            for f in ("status", "amount_received", "penalty", "remarks"):
                del self.fields[f]
            self.fields["date_issued"].required = True
        else:
            self.fields["date_issued"].required = False
            self.fields["officer_name"].initial = self.instance.officer.name if self.instance.officer_id else ""
        self.fields["officer_name"].required = not is_edit
        self.fields["interest"].required = False
        self.fields["total_due"].required = False
        self.fields["due_date"].required = is_edit
        self.fields["interest"].help_text = "Left blank, this is filled in from the interest rate in Settings."
        self.fields["due_date"].help_text = "" if is_edit else "Left blank, this is filled in from the loan term in Settings."
        self.fields["total_due"].help_text = "Principal + interest. Left blank, this is calculated for you."
        self.fields["principal"].widget.attrs.update({"min": 1})
        self._style()

    def clean_officer_name(self):
        return rules.normalise_name(self.cleaned_data.get("officer_name"))

    def clean(self):
        cd = super().clean()
        s = get_settings()
        p = cd.get("principal")
        if p is not None and p < 1:
            self.add_error("principal", "Principal must be at least 1.")
        if p is not None:
            if cd.get("interest") is None:
                cd["interest"] = s.interest_for(p)
            if not cd.get("total_due"):
                cd["total_due"] = p + cd["interest"]
        if not self.is_edit and not cd.get("due_date") and cd.get("date_issued") and cd.get("branch"):
            from datetime import timedelta
            cd["due_date"] = cd["date_issued"] + timedelta(days=s.term_for(cd["branch"]))
        if cd.get("due_date") is None and not self.has_error("due_date"):
            self.add_error("due_date", "Enter the repayment date.")
        return cd

    def save(self, commit=True):
        loan = super().save(commit=False)
        branch = self.cleaned_data["branch"]
        name = self.cleaned_data.get("officer_name", "")
        if name:
            loan.officer, created = resolve_officer(name, branch)
            self.new_officer = loan.officer if created else None
        elif not self.is_edit:
            loan.officer = None
        if commit:
            loan.save()
        return loan


class PaymentForm(StyledMixin, forms.ModelForm):
    class Meta:
        model = Payment
        fields = ["amount", "paid_on", "receipt_no"]
        widgets = {"paid_on": date_input(), "amount": forms.NumberInput(attrs={"min": 1, "step": 1})}
        labels = {"amount": "Amount received (UGX)"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style()


class FollowUpForm(StyledMixin, forms.ModelForm):
    class Meta:
        model = FollowUp
        fields = ["outcome", "promise_date", "note"]
        widgets = {"promise_date": date_input(), "note": forms.Textarea(attrs={"rows": 3,
                                                                              "placeholder": "What was agreed?"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style()


class RecommendationForm(StyledMixin, forms.ModelForm):
    class Meta:
        model = Recommendation
        fields = ["title", "text"]
        widgets = {"text": forms.Textarea(attrs={"rows": 4})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style()


class SettingsForm(StyledMixin, forms.ModelForm):
    class Meta:
        model = SiteSettings
        fields = ["reminder_window_days", "severe_default_days", "interest_rate_percent",
                  "term_days_arua", "term_days_gulu"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style()


# --------------------------------------------------------------------------
# Users
# --------------------------------------------------------------------------
def _resolve_user_officer(name, branch):
    """Link a user to an Officer, creating the officer if the name is new."""
    name = rules.normalise_name(name)
    if not name:
        return None
    q = Officer.objects.filter(name__iexact=name)
    found = (q.filter(branch=branch).first() if branch else None) or q.first()
    if found:
        return found
    return Officer.objects.create(branch=branch, name=rules.proper(name))


def _check_officer_branch(form):
    """A brand-new officer name needs a branch so we know which list it belongs to."""
    name = rules.normalise_name(form.cleaned_data.get("officer_name"))
    branch = form.cleaned_data.get("branch")
    if name and not branch and not Officer.objects.filter(name__iexact=name).exists():
        form.add_error("branch", "Choose a branch so the new officer name is added to the right list.")


class UserCreateForm(StyledMixin, forms.ModelForm):
    officer_name = forms.CharField(
        label="Loan officer name", max_length=80, required=False, widget=OfficerNameInput(),
        help_text="Only for Loans Officers: pick or type the name used on loans (new names are added).")

    class Meta:
        model = User
        fields = ("first_name", "last_name", "email", "phone", "role", "branch")

    def __init__(self, *args, creator=None, **kwargs):
        super().__init__(*args, **kwargs)
        allowed = permissions.creatable_roles(creator.role if creator else permissions.MANAGER)
        if creator is not None and creator.is_superuser:
            allowed = [r for r, _ in Role.choices]
        self.fields["role"].choices = [c for c in Role.choices if c[0] in allowed]
        self.fields["first_name"].required = True
        # Keep imports and older data compatible; the email workflow is used
        # whenever an address is supplied and the UI explains its importance.
        self.fields["email"].required = False
        self.fields["branch"].choices = [("", "Both branches")] + list(Branch.choices)
        self._style()

    def clean(self):
        cd = super().clean()
        if cd.get("role") == Role.OFFICER:
            _check_officer_branch(self)
        return cd

    def save(self, commit=True):
        user = super().save(commit=False)
        user.officer = (_resolve_user_officer(self.cleaned_data.get("officer_name"), user.branch)
                        if user.role == Role.OFFICER else None)
        if commit:
            user.save()
        return user


class CredentialChangeForm(StyledMixin, SetPasswordForm):
    """Allow a signed-in user to choose both a username and a new password."""

    username = forms.CharField(max_length=150, label="Preferred username")

    def __init__(self, user, *args, **kwargs):
        super().__init__(user, *args, **kwargs)
        self.fields["username"].initial = user.username
        self._style()

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        if User.objects.exclude(pk=self.user.pk).filter(username__iexact=username).exists():
            raise forms.ValidationError("That username is already in use.")
        if not username:
            raise forms.ValidationError("Enter a username.")
        return username

    def save(self, commit=True):
        self.user.username = self.cleaned_data["username"]
        return super().save(commit=commit)


class StyledPasswordResetForm(PasswordResetForm):
    """Use the application's form-control styling on the reset email field."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["email"].widget.attrs["class"] = "in form-control"


class StyledSetPasswordForm(SetPasswordForm):
    """Use the application's form-control styling on reset password fields."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "in form-control"


class UserEditForm(StyledMixin, forms.ModelForm):
    officer_name = forms.CharField(label="Loan officer name", max_length=80, required=False,
                                   widget=OfficerNameInput())

    class Meta:
        model = User
        fields = ["first_name", "last_name", "email", "phone", "role", "branch", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["branch"].choices = [("", "Both branches")] + list(Branch.choices)
        if self.instance.officer_id:
            self.fields["officer_name"].initial = self.instance.officer.name
        self._style()

    def clean(self):
        cd = super().clean()
        if cd.get("role") == Role.OFFICER:
            _check_officer_branch(self)
        return cd

    def save(self, commit=True):
        user = super().save(commit=False)
        user.officer = (_resolve_user_officer(self.cleaned_data.get("officer_name"), user.branch)
                        if user.role == Role.OFFICER else None)
        if commit:
            user.save()
        return user
