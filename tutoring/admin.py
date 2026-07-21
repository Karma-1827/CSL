from django.contrib import admin

from .models import (
    Attendance,
    ClassConfirmation,
    ClassAlert,
    ClassRecord,
    ClassSession,
    MakeupReview,
    MatchingInvitation,
    Pairing,
    PairingMessage,
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


@admin.register(ClassRecord)
class ClassRecordAdmin(admin.ModelAdmin):
    list_display = ("session", "author", "topic", "submitted_at", "is_makeup")
    list_filter = ("is_makeup", "session__pairing__semester")
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
    readonly_fields = ("created_at", "cancelled_at")


admin.site.site_header = "華語輔導系統管理 / CSL Tutoring Administration"
admin.site.site_title = "華語輔導系統 / CSL Tutoring"
admin.site.index_title = "系統管理 / System administration"
