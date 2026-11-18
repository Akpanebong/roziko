from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.contrib.auth.models import AbstractUser, UserManager
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.urls import reverse

from . import permissions


class Branch(models.TextChoices):
    ARUA = "A", "Arua"
    GULU = "G", "Gulu"


class Role(models.TextChoices):
    CASHIER = permissions.CASHIER, "Cashier"
    OFFICER = permissions.OFFICER, "Loans Officer"
    MANAGER = permissions.MANAGER, "Branch Manager"
    ADVISOR = permissions.ADVISOR, "Advisory Board"


class LoanStatus(models.TextChoices):
    CURRENT = "Current", "Current"
    DEFAULT = "Default", "Default"
    COMPLETED = "Completed", "Completed"


# --------------------------------------------------------------------------
# Officers and users
# --------------------------------------------------------------------------
class Officer(models.Model):
    """A loan officer name. New names can be typed in on the loan form."""
    name = models.CharField(max_length=80)
    branch = models.CharField(max_length=1, choices=Branch.choices)

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["branch", "name"], name="uniq_officer_per_branch")]

    def __str__(self):
        return f"{self.name} ({self.get_branch_display()})"


class RozikoUserManager(UserManager):
    def create_superuser(self, username, email=None, password=None, **extra_fields):
        extra_fields.setdefault("role", Role.MANAGER)
        return super().create_superuser(username, email, password, **extra_fields)


class User(AbstractUser):
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.OFFICER)
    branch = models.CharField(
        max_length=1, choices=Branch.choices, blank=True,
        help_text="Leave blank to give access to both branches.",
    )
    officer = models.ForeignKey(
        Officer, null=True, blank=True, on_delete=models.SET_NULL, related_name="users",
        help_text="For Loans Officers: the officer name whose clients this user follows up.",
    )
    phone = models.CharField(max_length=30, blank=True)

    objects = RozikoUserManager()

    @property
    def perm_set(self) -> set:
        if self.is_superuser:
            return set(permissions.PERMISSION_LABELS)
        return permissions.perms_for(self.role)

    def can(self, key: str) -> bool:
        return key in self.perm_set

    @property
    def display_name(self) -> str:
        return self.get_full_name() or self.username


# --------------------------------------------------------------------------
# Settings (single row)
# --------------------------------------------------------------------------
class SiteSettings(models.Model):
    reminder_window_days = models.PositiveSmallIntegerField(
        "Remind this many days before the due date", default=3,
        validators=[MaxValueValidator(30)])
    severe_default_days = models.PositiveSmallIntegerField(
        "Severe default after (days late)", default=30,
        validators=[MinValueValidator(2), MaxValueValidator(365)])
    interest_rate_percent = models.DecimalField(
        "Interest on new loans (%)", max_digits=5, decimal_places=2, default=13,
        validators=[MinValueValidator(0), MaxValueValidator(100)])
    term_days_arua = models.PositiveSmallIntegerField("Arua loan term (days)", default=28,
                                                     validators=[MinValueValidator(1)])
    term_days_gulu = models.PositiveSmallIntegerField("Gulu loan term (days)", default=30,
                                                     validators=[MinValueValidator(1)])

    class Meta:
        verbose_name = "Site settings"
        verbose_name_plural = "Site settings"

    def save(self, *args, **kwargs):
        self.pk = 1  # single row
        super().save(*args, **kwargs)

    def term_for(self, branch: str) -> int:
        return self.term_days_arua if branch == Branch.ARUA else self.term_days_gulu

    def interest_for(self, principal: int) -> int:
        v = (Decimal(principal) * self.interest_rate_percent / 100)
        return int(v.quantize(Decimal(1), rounding=ROUND_HALF_UP))


# --------------------------------------------------------------------------
# Loans
# --------------------------------------------------------------------------
class Loan(models.Model):
    legacy_id = models.CharField(max_length=20, blank=True, db_index=True,
                                 help_text="ID from the original Excel tracker, e.g. A4 or G2644")
    branch = models.CharField(max_length=1, choices=Branch.choices)
    serial_no = models.IntegerField(null=True, blank=True)
    client_name = models.CharField(max_length=120)
    officer = models.ForeignKey(Officer, null=True, blank=True, on_delete=models.SET_NULL,
                                related_name="loans")
    date_issued = models.DateField(null=True, blank=True)
    due_date = models.DateField("Repayment date", null=True, blank=True)
    principal = models.BigIntegerField(default=0)
    interest = models.BigIntegerField(default=0)
    total_due = models.BigIntegerField("Total due (P+I)", default=0)
    processing_fee = models.BigIntegerField(null=True, blank=True)
    amount_received = models.BigIntegerField(
        "Amount received before this system", default=0,
        help_text="Repayments carried over from the Excel tracker. New payments are recorded separately.")
    penalty = models.BigIntegerField(null=True, blank=True)
    loan_type = models.CharField("Loan type / details", max_length=80, blank=True)
    client_contact = models.CharField(max_length=100, blank=True)
    guarantor_contact = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=10, choices=LoanStatus.choices, default=LoanStatus.CURRENT)
    remarks = models.CharField(max_length=200, blank=True)
    receipt_no = models.CharField(max_length=40, blank=True)
    received_by = models.CharField(max_length=80, blank=True)
    payment_date_text = models.CharField("Payment date (as entered)", max_length=80, blank=True)
    import_note = models.TextField(blank=True,
                                   help_text="Original text of dates that could not be read during import")

    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="loans_created")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date_issued", "-id"]
        indexes = [models.Index(fields=["branch", "due_date"])]

    def __str__(self):
        return f"{self.client_name} ({self.get_branch_display()})"

    def get_absolute_url(self):
        return reverse("loan_detail", args=[self.pk])

    @property
    def officer_name(self):
        return self.officer.name if self.officer_id else "Unassigned"


class Payment(models.Model):
    loan = models.ForeignKey(Loan, on_delete=models.CASCADE, related_name="payments")
    amount = models.BigIntegerField(validators=[MinValueValidator(1)])
    paid_on = models.DateField("Date received")
    receipt_no = models.CharField("Voucher / receipt no.", max_length=40, blank=True)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL,
                                    related_name="payments_recorded")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-paid_on", "-id"]

    def __str__(self):
        return f"{self.amount:,} UGX on {self.paid_on}"


FOLLOWUP_OUTCOMES = [
    "Reached - promised to pay",
    "Reached - part payment made",
    "No answer",
    "Phone off or unreachable",
    "Visit made",
    "Guarantor contacted",
    "Client refused or disputes",
]


class FollowUp(models.Model):
    loan = models.ForeignKey(Loan, on_delete=models.CASCADE, related_name="followups")
    outcome = models.CharField(max_length=60, choices=[(o, o) for o in FOLLOWUP_OUTCOMES])
    promise_date = models.DateField("Promised pay date", null=True, blank=True)
    note = models.TextField(blank=True)
    by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL,
                           related_name="followups")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class Recommendation(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        REVIEWED = "reviewed", "Reviewed by management"

    loan = models.ForeignKey(Loan, null=True, blank=True, on_delete=models.CASCADE,
                             related_name="recommendations")
    title = models.CharField(max_length=140)
    text = models.TextField("Recommendation")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL,
                           related_name="recommendations")
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name="recommendations_reviewed")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title


class AuditLog(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                             on_delete=models.SET_NULL, related_name="+")
    user_name = models.CharField(max_length=150, blank=True)
    action = models.CharField(max_length=40)
    object_type = models.CharField(max_length=40, blank=True)
    object_id = models.CharField(max_length=40, blank=True)
    object_repr = models.CharField(max_length=255, blank=True)
    detail = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["object_type", "object_id"])]

    def __str__(self):
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.user_name} {self.action} {self.object_repr}"
