from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import (AuditLog, FollowUp, Loan, Officer, Payment, Recommendation, SiteSettings, User)


@admin.register(User)
class RozikoUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (("Roziko", {"fields": ("role", "branch", "officer", "phone")}),)
    add_fieldsets = UserAdmin.add_fieldsets + (("Roziko", {"fields": ("role", "branch", "officer", "phone")}),)
    list_display = ("username", "first_name", "last_name", "role", "branch", "is_active")
    list_filter = ("role", "branch", "is_active")


@admin.register(Loan)
class LoanAdmin(admin.ModelAdmin):
    list_display = ("client_name", "branch", "officer", "date_issued", "due_date", "principal", "status")
    list_filter = ("branch", "status", "officer")
    search_fields = ("client_name", "client_contact", "guarantor_contact", "legacy_id")


admin.site.register([Officer, Payment, FollowUp, Recommendation, SiteSettings])


@admin.register(AuditLog)
class AuditAdmin(admin.ModelAdmin):
    list_display = ("created_at", "user_name", "action", "object_type", "object_repr")
    list_filter = ("action", "object_type")
    readonly_fields = [f.name for f in AuditLog._meta.fields]

    def has_add_permission(self, request):
        return False
