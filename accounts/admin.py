from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import AuditLog, RosterEntry, SecurityQuestionAnswer, User


@admin.register(User)
class CSLUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ("華語輔導系統 / CSL Tutoring", {"fields": ("role", "account_status", "roster_entry", "name_zh", "name_en", "phone")}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ("華語輔導系統 / CSL Tutoring", {"fields": ("role", "name_zh", "name_en")}),
    )
    list_display = ("username", "name_zh", "name_en", "role", "account_status", "is_staff")
    list_filter = ("role", "account_status", "is_staff", "is_active")
    search_fields = ("username", "name_zh", "name_en")


@admin.register(RosterEntry)
class RosterEntryAdmin(admin.ModelAdmin):
    list_display = ("student_id", "name_zh", "name_en", "role", "education_level", "program_source", "is_enabled", "claimed_at")
    list_filter = ("role", "education_level", "identity_category", "program_source", "is_enabled")
    search_fields = ("student_id", "name_zh", "name_en")
    readonly_fields = ("claimed_at", "created_at", "updated_at")


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "event_type", "actor", "target_user", "ip_address")
    list_filter = ("event_type", "created_at")
    search_fields = ("description", "actor__username", "target_user__username")
    readonly_fields = ("actor", "target_user", "event_type", "description", "ip_address", "metadata", "created_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(SecurityQuestionAnswer)
class SecurityQuestionAnswerAdmin(admin.ModelAdmin):
    list_display = ("user", "question_1", "question_2", "question_3", "updated_at")
    readonly_fields = ("user", "question_1", "answer_1_hash", "question_2", "answer_2_hash", "question_3", "answer_3_hash", "updated_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

