from datetime import timedelta

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html

from .forms import ThrottledAdminAuthenticationForm
from .models import AuditLog, PartnerProgram, Role, RosterEntry, SecurityQuestionAnswer, User

IDLE_ACCOUNT_THRESHOLD_DAYS = 180

# Batch 4 item 6 (docs/VULNERABILITY_SCAN_IMPROVEMENTS.md): give /system-admin/'s own login
# view the same shared IP+username throttle as the main site login, since Django Admin's
# default login form has no rate limiting of its own.
admin.site.login_form = ThrottledAdminAuthenticationForm


class IdleAccountFilter(admin.SimpleListFilter):
    """資通系統防護基準檢核表第 3 項:標記閒置帳號供 Admin 人工複核。

    刻意不自動停用——華語班有寒暑假,學生/老師超過門檻天數沒登入很正常,
    自動停用有誤鎖到還在配對期使用者的風險;是否要停用由 Admin 自行判斷。
    """

    title = "閒置帳號 / Idle account"
    parameter_name = "idle"

    def lookups(self, request, model_admin):
        return (
            ("idle", f"{IDLE_ACCOUNT_THRESHOLD_DAYS} 天以上未登入 / Idle {IDLE_ACCOUNT_THRESHOLD_DAYS}+ days"),
            ("never", "從未登入過 / Never logged in"),
        )

    def queryset(self, request, queryset):
        if self.value() == "idle":
            cutoff = timezone.now() - timedelta(days=IDLE_ACCOUNT_THRESHOLD_DAYS)
            return queryset.filter(last_login__lt=cutoff)
        if self.value() == "never":
            return queryset.filter(last_login__isnull=True)
        return queryset


class RosterClaimStatusFilter(admin.SimpleListFilter):
    title = "註冊狀態 / Registration status"
    parameter_name = "claimed"

    def lookups(self, request, model_admin):
        return (
            ("yes", "已註冊 / Registered"),
            ("no", "尚未註冊 / Not registered"),
        )

    def queryset(self, request, queryset):
        if self.value() == "yes":
            return queryset.filter(claimed_at__isnull=False)
        if self.value() == "no":
            return queryset.filter(claimed_at__isnull=True)
        return queryset


@admin.register(User)
class CSLUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ("華語實習暨輔導系統 / MPTS", {"fields": ("role", "account_status", "roster_entry", "name_zh", "name_en", "phone")}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ("華語實習暨輔導系統 / MPTS", {"fields": ("role", "name_zh", "name_en")}),
    )
    list_display = ("username", "name_zh", "name_en", "role", "account_status", "is_staff", "last_login")
    list_filter = ("role", "account_status", "is_staff", "is_active", IdleAccountFilter)
    search_fields = ("username", "name_zh", "name_en")


@admin.register(RosterEntry)
class RosterEntryAdmin(admin.ModelAdmin):
    change_list_template = "admin/accounts/rosterentry/change_list.html"
    list_display = (
        "student_id",
        "name_zh",
        "name_en",
        "role",
        "identity_category",
        "education_level",
        "program",
        "is_enabled",
        "claimed_at",
        "profile_link",
    )
    list_filter = (
        "role",
        "identity_category",
        "education_level",
        "program",
        "is_enabled",
        RosterClaimStatusFilter,
    )
    search_fields = ("student_id", "name_zh", "name_en")
    search_help_text = "可輸入學號、中文姓名或英文姓名。 / Search by student ID, Chinese name, or English name."
    readonly_fields = ("claimed_at", "created_at", "updated_at")

    def changelist_view(self, request, extra_context=None):
        extra_context = {
            **(extra_context or {}),
            "roster_role_choices": RosterEntry._meta.get_field("role").choices,
            "roster_identity_choices": RosterEntry._meta.get_field("identity_category").choices,
            "roster_education_choices": RosterEntry._meta.get_field("education_level").choices,
            "roster_program_choices": PartnerProgram.objects.order_by("name_zh"),
            "roster_filters": {
                "q": request.GET.get("q", ""),
                "role": request.GET.get("role__exact", ""),
                "identity": request.GET.get("identity_category__exact", ""),
                "education": request.GET.get("education_level__exact", ""),
                "program": request.GET.get("program__id__exact", ""),
                "enabled": request.GET.get("is_enabled__exact", ""),
                "claimed": request.GET.get("claimed", ""),
            },
        }
        return super().changelist_view(request, extra_context=extra_context)

    @admin.display(description="行政檔案 / Admin profile")
    def profile_link(self, obj):
        user = getattr(obj, "user", None)
        if not user or user.role not in {Role.TUTOR, Role.TUTEE}:
            return "—"
        return format_html(
            '<a href="{}" target="_blank" rel="noopener">查看檔案 / View profile</a>',
            reverse("accounts:admin_user_profile", args=[user.pk]),
        )


@admin.register(PartnerProgram)
class PartnerProgramAdmin(admin.ModelAdmin):
    list_display = (
        "name_zh", "code", "is_active", "allow_tutee_initiate_invitation",
        "tutee_can_download_hours", "tutee_certificate_filename", "tutor_certificate_filename",
    )
    list_filter = ("is_active", "allow_tutee_initiate_invitation", "tutee_can_download_hours")
    search_fields = ("code", "name_zh", "name_en")
    readonly_fields = ("created_at", "updated_at")


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
