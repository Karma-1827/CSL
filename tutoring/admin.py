from django.contrib import admin

from accounts.forms import SKILL_CHOICES
from accounts.models import AuditLog

from .models import (
    Attendance,
    ClassConfirmation,
    ClassAlert,
    ClassDocument,
    ClassRecord,
    ClassSession,
    HourAdjustment,
    IncidentReport,
    MakeupReview,
    MatchingInvitation,
    Pairing,
    PairingReleaseRequest,
    QualificationDocument,
    Semester,
    TuteeProfile,
    TutorProfile,
)


@admin.register(QualificationDocument)
class QualificationDocumentAdmin(admin.ModelAdmin):
    list_display = ("tutor", "status", "original_filename", "uploaded_at", "reviewed_by")
    list_filter = ("status", "uploaded_at")
    search_fields = ("tutor__username", "tutor__name_zh", "tutor__name_en")
    readonly_fields = ("original_filename", "uploaded_at", "updated_at")


@admin.register(Semester)
class SemesterAdmin(admin.ModelAdmin):
    list_display = ("name_zh", "name_en", "starts_on", "ends_on", "is_active")
    list_filter = ("is_active",)


@admin.register(TutorProfile)
class TutorProfileAdmin(admin.ModelAdmin):
    list_display = ("tutor", "native_language", "nationality", "updated_at")
    search_fields = ("tutor__username", "tutor__name_zh", "tutor__name_en", "nationality")
    readonly_fields = ("created_at", "updated_at")


@admin.register(TuteeProfile)
class TuteeProfileAdmin(admin.ModelAdmin):
    list_display = ("tutee", "overall_level", "native_language", "nationality", "updated_at")
    search_fields = ("tutee__username", "tutee__name_zh", "tutee__name_en", "nationality")
    readonly_fields = ("created_at", "updated_at")


@admin.register(MatchingInvitation)
class MatchingInvitationAdmin(admin.ModelAdmin):
    list_display = ("semester", "tutor", "tutee", "initiated_by", "status", "expires_at")
    list_filter = ("semester", "status", "created_at")
    search_fields = ("tutor__username", "tutee__username")
    readonly_fields = ("created_at", "updated_at", "responded_at")


@admin.register(Pairing)
class PairingAdmin(admin.ModelAdmin):
    list_display = ("semester", "tutor", "tutee", "status", "started_at", "ended_at")
    list_filter = ("semester", "status")
    search_fields = ("tutor__username", "tutee__username")
    readonly_fields = ("started_at",)


@admin.register(PairingReleaseRequest)
class PairingReleaseRequestAdmin(admin.ModelAdmin):
    list_display = ("pairing", "requested_by", "reason", "status", "auto_resolve_at", "created_at")
    list_filter = ("status", "reason", "pairing__semester")
    search_fields = (
        "pairing__tutor__username",
        "pairing__tutee__username",
        "requested_by__username",
        "reason_note",
    )
    readonly_fields = ("created_at", "updated_at", "reviewed_at")


@admin.register(ClassSession)
class ClassSessionAdmin(admin.ModelAdmin):
    list_display = ("class_date", "start_time", "duration", "pairing", "status")
    list_filter = ("pairing__semester", "status", "class_date")
    search_fields = ("pairing__tutor__username", "pairing__tutee__username")
    readonly_fields = ("created_at", "updated_at", "cancelled_at")


@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = ("session", "participant", "signed_at", "is_makeup")
    list_filter = ("is_makeup", "session__pairing__semester")


class SkillsPracticedFilter(admin.SimpleListFilter):
    title = "授課類型 / Skill practiced"
    parameter_name = "skill"

    def lookups(self, request, model_admin):
        return SKILL_CHOICES

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(skills_practiced__contains=[self.value()])
        return queryset


@admin.register(ClassRecord)
class ClassRecordAdmin(admin.ModelAdmin):
    list_display = ("session", "author", "topic", "skills_practiced", "submitted_at", "is_makeup")
    list_filter = ("is_makeup", "session__pairing__semester", SkillsPracticedFilter)
    search_fields = ("author__username", "topic")


@admin.register(ClassConfirmation)
class ClassConfirmationAdmin(admin.ModelAdmin):
    list_display = ("session", "reviewer", "subject", "status", "confirmed_at")
    list_filter = ("status", "session__pairing__semester")


@admin.register(MakeupReview)
class MakeupReviewAdmin(admin.ModelAdmin):
    list_display = ("session", "status", "reviewed_by", "reviewed_at")
    list_filter = ("status", "session__pairing__semester")


@admin.register(ClassAlert)
class ClassAlertAdmin(admin.ModelAdmin):
    list_display = ("session", "reporter", "subject", "reason", "status", "created_at")
    list_filter = ("status", "reason", "session__pairing__semester")
    search_fields = ("reporter__username", "subject__username", "note")
    readonly_fields = ("created_at", "cancelled_at", "resolved_at")


@admin.register(IncidentReport)
class IncidentReportAdmin(admin.ModelAdmin):
    list_display = ("session", "reporter", "category", "status", "created_at", "resolved_by")
    list_filter = ("status", "category", "session__pairing__semester")
    search_fields = ("reporter__username", "content")
    readonly_fields = ("created_at", "resolved_at")


@admin.register(HourAdjustment)
class HourAdjustmentAdmin(admin.ModelAdmin):
    list_display = ("user", "semester", "program", "hours", "created_by", "created_at")
    list_filter = ("semester", "program")
    search_fields = ("user__username", "user__name_zh", "user__name_en", "reason")
    autocomplete_fields = ("user",)
    readonly_fields = ("created_by", "created_at")

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)
        AuditLog.record(
            actor=request.user,
            target_user=obj.user,
            event_type="HOUR_ADJUSTMENT_UPDATED" if change else "HOUR_ADJUSTMENT_CREATED",
            description="更新行政更正紀錄 / Administrative correction updated" if change else "新增行政更正紀錄 / Administrative correction created",
            metadata={
                "hours": str(obj.hours),
                "semester": str(obj.semester),
                "program": obj.program.code,
                "reason": obj.reason,
            },
        )


@admin.register(ClassDocument)
class ClassDocumentAdmin(admin.ModelAdmin):
    list_display = ("title_zh", "program", "semester", "is_active", "uploaded_by", "uploaded_at")
    list_filter = ("program", "is_active", "semester")
    search_fields = ("title_zh", "title_en")
    readonly_fields = ("uploaded_by", "uploaded_at")

    def save_model(self, request, obj, form, change):
        if not change:
            obj.uploaded_by = request.user
        super().save_model(request, obj, form, change)


admin.site.site_header = "華語實習暨輔導系統管理 / MPTS Administration"
admin.site.site_title = "華語實習暨輔導系統 / MPTS"
admin.site.index_title = "系統管理 / System administration"
