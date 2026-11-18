from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy

from . import views
from .forms import StyledPasswordResetForm, StyledSetPasswordForm

urlpatterns = [
    path("", views.dashboard, name="dashboard"),

    # authentication
    path("login/", auth_views.LoginView.as_view(redirect_authenticated_user=True), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("account/password/", views.account_credentials, name="password_change"),
    path("account/password/reset/", auth_views.PasswordResetView.as_view(
        form_class=StyledPasswordResetForm,
        template_name="account/password_reset_form.html",
        email_template_name="account/password_reset_email.html",
        subject_template_name="account/password_reset_subject.txt",
        success_url=reverse_lazy("password_reset_done")), name="password_reset"),
    path("account/password/reset/done/", auth_views.PasswordResetDoneView.as_view(
        template_name="account/password_reset_done.html"), name="password_reset_done"),
    path("account/password/reset/<uidb64>/<token>/", auth_views.PasswordResetConfirmView.as_view(
        form_class=StyledSetPasswordForm,
        template_name="account/password_reset_confirm.html",
        success_url=reverse_lazy("password_reset_complete")), name="password_reset_confirm"),
    path("account/password/reset/complete/", auth_views.PasswordResetCompleteView.as_view(
        template_name="account/password_reset_complete.html"), name="password_reset_complete"),

    # reminders and loans
    path("reminders/", views.reminders, name="reminders"),
    path("loans/", views.loan_list, name="loan_list"),
    path("loans/add/", views.loan_add, name="loan_add"),
    path("loans/<int:pk>/", views.loan_detail, name="loan_detail"),
    path("loans/<int:pk>/edit/", views.loan_edit, name="loan_edit"),
    path("loans/<int:pk>/delete/", views.loan_delete, name="loan_delete"),
    path("loans/<int:pk>/payments/add/", views.payment_add, name="payment_add"),
    path("loans/<int:pk>/followups/add/", views.followup_add, name="followup_add"),
    path("loans/<int:pk>/recommend/", views.recommendation_add, name="loan_recommend"),
    path("payments/<int:pk>/delete/", views.payment_delete, name="payment_delete"),

    # recommendations
    path("recommendations/", views.recommendation_list, name="recommendation_list"),
    path("recommendations/add/", views.recommendation_add, name="recommendation_add"),
    path("recommendations/<int:pk>/delete/", views.recommendation_delete, name="recommendation_delete"),
    path("recommendations/<int:pk>/toggle/", views.recommendation_toggle, name="recommendation_toggle"),

    # downloads
    path("export/loans.xlsx", views.export_loans, name="export_loans"),
    path("export/reminders.csv", views.export_reminders, name="export_reminders"),

    # users, settings, audit
    path("users/", views.user_list, name="user_list"),
    path("users/add/", views.user_add, name="user_add"),
    path("users/<int:pk>/edit/", views.user_edit, name="user_edit"),
    path("users/<int:pk>/password/", views.user_password, name="user_password"),
    path("users/<int:pk>/delete/", views.user_delete, name="user_delete"),
    path("settings/", views.site_settings, name="site_settings"),
    path("activity/", views.audit_log, name="audit_log"),
]
