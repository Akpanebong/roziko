"""Role and workflow tests. Run with:  python manage.py test"""
from datetime import date, timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from desk.models import Loan, Officer, Payment, Role, User


def make_user(username, role, **kw):
    return User.objects.create_user(username=username, password="pw-Test-12345", role=role,
                                    first_name=username.title(), **kw)


class RoleAccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.cashier = make_user("cash", Role.CASHIER)
        cls.officer_user = make_user("off", Role.OFFICER)
        cls.manager = make_user("mgr", Role.MANAGER)
        cls.advisor = make_user("adv", Role.ADVISOR)
        cls.officer = Officer.objects.create(name="Oscar", branch="G")
        today = timezone.localdate()
        cls.loan = Loan.objects.create(
            branch="G", client_name="Test Client", officer=cls.officer, date_issued=today - timedelta(days=40),
            due_date=today - timedelta(days=10), principal=1000000, interest=130000, total_due=1130000)

    def status(self, user, name, args=None, method="get", data=None):
        self.client.force_login(user)
        url = reverse(name, args=args or [])
        resp = getattr(self.client, method)(url, data or {})
        return resp.status_code

    def test_anonymous_redirected_to_login(self):
        for name in ("dashboard", "loan_list", "reminders"):
            r = self.client.get(reverse(name))
            self.assertEqual(r.status_code, 302)
            self.assertIn("/login/", r["Location"])

    def test_everyone_can_view(self):
        for u in (self.cashier, self.officer_user, self.manager, self.advisor):
            for name in ("dashboard", "loan_list", "reminders"):
                self.assertEqual(self.status(u, name), 200, (u.username, name))
            self.assertEqual(self.status(u, "loan_detail", [self.loan.pk]), 200)

    def test_add_loan_only_cashier_and_manager(self):
        self.assertEqual(self.status(self.cashier, "loan_add"), 200)
        self.assertEqual(self.status(self.manager, "loan_add"), 200)
        self.assertEqual(self.status(self.officer_user, "loan_add"), 403)
        self.assertEqual(self.status(self.advisor, "loan_add"), 403)

    def test_delete_loan(self):
        self.assertEqual(self.status(self.officer_user, "loan_delete", [self.loan.pk]), 403)
        self.assertEqual(self.status(self.advisor, "loan_delete", [self.loan.pk]), 403)
        self.client.force_login(self.cashier)
        r = self.client.post(reverse("loan_delete", args=[self.loan.pk]))
        self.assertEqual(r.status_code, 302)
        self.assertFalse(Loan.objects.filter(pk=self.loan.pk).exists())

    def test_edit_loan_manager_only(self):
        for u in (self.cashier, self.officer_user, self.advisor):
            self.assertEqual(self.status(u, "loan_edit", [self.loan.pk]), 403)
        self.assertEqual(self.status(self.manager, "loan_edit", [self.loan.pk]), 200)

    def test_export_advisor_and_manager_only(self):
        self.assertEqual(self.status(self.advisor, "export_loans"), 200)
        self.assertEqual(self.status(self.manager, "export_loans"), 200)
        self.assertEqual(self.status(self.cashier, "export_loans"), 403)
        self.assertEqual(self.status(self.officer_user, "export_loans"), 403)

    def test_recommendations(self):
        self.assertEqual(self.status(self.advisor, "recommendation_list"), 200)
        self.assertEqual(self.status(self.cashier, "recommendation_list"), 403)
        self.client.force_login(self.advisor)
        r = self.client.post(reverse("loan_recommend", args=[self.loan.pk]),
                             {"title": "Restructure", "text": "Offer a 2-month plan."})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.loan.recommendations.count(), 1)
        self.client.force_login(self.officer_user)
        r = self.client.post(reverse("loan_recommend", args=[self.loan.pk]), {"title": "x", "text": "y"})
        self.assertEqual(r.status_code, 403)

    def test_followup_officer_yes_advisor_no(self):
        data = {"outcome": "No answer", "note": "phone off"}
        self.assertEqual(self.status(self.officer_user, "followup_add", [self.loan.pk], "post", data), 302)
        self.assertEqual(self.status(self.advisor, "followup_add", [self.loan.pk], "post", data), 403)

    def test_payment_reduces_balance_and_delete(self):
        self.client.force_login(self.cashier)
        r = self.client.post(reverse("payment_add", args=[self.loan.pk]),
                             {"amount": 130000, "paid_on": timezone.localdate().isoformat(), "receipt_no": "R1"})
        self.assertEqual(r.status_code, 302)
        p = Payment.objects.get()
        self.client.force_login(self.officer_user)
        self.assertEqual(self.client.post(reverse("payment_add", args=[self.loan.pk]),
                                          {"amount": 5, "paid_on": "2026-11-18"}).status_code, 403)
        self.assertEqual(self.client.post(reverse("payment_delete", args=[p.pk])).status_code, 403)
        self.client.force_login(self.cashier)
        self.assertEqual(self.client.post(reverse("payment_delete", args=[p.pk])).status_code, 302)
        self.assertEqual(Payment.objects.count(), 0)

    def test_user_management(self):
        self.assertEqual(self.status(self.manager, "user_list"), 200)
        for u in (self.cashier, self.officer_user, self.advisor):
            self.assertEqual(self.status(u, "user_list"), 403)
        self.assertEqual(self.status(self.advisor, "user_add"), 200)
        self.assertEqual(self.status(self.manager, "user_add"), 200)
        self.assertEqual(self.status(self.cashier, "user_add"), 403)
        self.assertEqual(self.status(self.officer_user, "user_add"), 403)
        self.assertEqual(self.status(self.cashier, "site_settings"), 403)
        self.assertEqual(self.status(self.advisor, "audit_log"), 403)
        self.assertEqual(self.status(self.manager, "audit_log"), 200)

    def _new_user(self, creator, role, name="newbie"):
        self.client.force_login(creator)
        return self.client.post(reverse("user_add"), {
            "username": name, "first_name": "New", "last_name": "User", "role": role, "branch": "",
            "password1": "Str0ng-pass-987", "password2": "Str0ng-pass-987"})

    def test_advisor_can_add_users_but_not_managers(self):
        r = self._new_user(self.advisor, Role.CASHIER)
        self.assertEqual(r.status_code, 302)
        self.assertTrue(User.objects.filter(username="newbie", role=Role.CASHIER).exists())
        r = self._new_user(self.advisor, Role.MANAGER, "sneaky")
        self.assertEqual(r.status_code, 200)  # form re-shown with an error
        self.assertFalse(User.objects.filter(username="sneaky").exists())

    def test_manager_can_add_any_role(self):
        for i, role in enumerate((Role.CASHIER, Role.OFFICER, Role.MANAGER, Role.ADVISOR)):
            self.assertEqual(self._new_user(self.manager, role, f"u{i}").status_code, 302)

    def test_cannot_remove_last_manager(self):
        self.client.force_login(self.manager)
        self.assertEqual(self.client.post(reverse("user_delete", args=[self.manager.pk])).status_code, 200)
        self.assertTrue(User.objects.filter(pk=self.manager.pk).exists())


class OfficerNameTests(TestCase):
    """The Loan officer box accepts a name from the list or a new typed name."""

    def setUp(self):
        self.cashier = make_user("cash", Role.CASHIER)
        Officer.objects.create(name="Oscar", branch="G")
        self.client.force_login(self.cashier)

    def post_loan(self, officer_name, branch="G", **extra):
        data = {"branch": branch, "officer_name": officer_name, "client_name": "Akello Test",
                "date_issued": "2026-11-18", "due_date": "", "principal": 1000000, "interest": "",
                "total_due": "", "client_contact": "0771000000", "guarantor_contact": "",
                "loan_type": "Business loan"}
        data.update(extra)
        return self.client.post(reverse("loan_add"), data)

    def test_pick_existing_name_ignoring_case(self):
        self.assertEqual(self.post_loan("oscar").status_code, 302)
        self.assertEqual(Officer.objects.count(), 1)
        self.assertEqual(Loan.objects.get().officer.name, "Oscar")

    def test_type_new_name_creates_officer(self):
        self.assertEqual(self.post_loan("  grace   atim ").status_code, 302)
        o = Officer.objects.get(name="Grace Atim")
        self.assertEqual(o.branch, "G")
        self.assertEqual(Loan.objects.get().officer, o)

    def test_defaults_filled_in(self):
        self.post_loan("Oscar")
        loan = Loan.objects.get()
        self.assertEqual(loan.interest, 130000)
        self.assertEqual(loan.total_due, 1130000)
        self.assertEqual(loan.due_date, date(2026, 11, 18) + timedelta(days=30))  # Gulu term
        self.assertEqual(loan.status, "Current")

    def test_officer_required_on_new_loan(self):
        self.assertEqual(self.post_loan("").status_code, 200)
        self.assertEqual(Loan.objects.count(), 0)
