from django.urls import path

from . import views

app_name = "tutoring"

urlpatterns = [
    path("semesters/save/", views.save_semester, name="save_semester"),
    path("semesters/<int:pk>/save/", views.save_semester, name="update_semester"),
    path("semesters/<int:pk>/archive/", views.archive_semester, name="archive_semester"),
    path("semesters/<int:pk>/delete/", views.delete_semester, name="delete_semester"),
    path("pairings/<int:pk>/messages/", views.pairing_messages, name="pairing_messages"),
    path("hours/download/", views.download_hours, name="download_hours"),
    path("admin/export-excel/", views.export_excel, name="export_excel"),
    path("classes/schedule/", views.schedule_class, name="schedule_class"),
    path("invitations/tutee/<int:user_id>/send/", views.invite_tutee, name="invite_tutee"),
    path("invitations/tutor/<int:user_id>/send/", views.invite_tutor, name="invite_tutor"),
    path("invitations/<int:pk>/respond/", views.respond_invitation, name="respond_invitation"),
    path("invitations/<int:pk>/cancel/", views.cancel_pending_invitation, name="cancel_invitation"),
    path("pairings/admin-create/", views.create_pairing, name="create_pairing"),
    path("pairings/<int:pk>/release/", views.request_pairing_release, name="request_pairing_release"),
    path(
        "pairing-release-requests/<int:pk>/review/",
        views.review_pairing_release,
        name="review_pairing_release",
    ),
    path("classes/<int:pk>/", views.class_detail, name="class_detail"),
    path("classes/<int:pk>/check-in/", views.class_check_in, name="class_check_in"),
    path("classes/<int:pk>/confirm/", views.class_confirm, name="class_confirm"),
    path("classes/<int:pk>/cancel/", views.class_cancel, name="class_cancel"),
    path("classes/<int:pk>/reschedule/", views.class_reschedule, name="class_reschedule"),
    path("classes/<int:pk>/alert/", views.class_alert, name="class_alert"),
    path("classes/<int:pk>/alert/<int:alert_id>/cancel/", views.cancel_alert, name="cancel_alert"),
    path("alerts/<int:alert_id>/resolve/", views.resolve_alert, name="resolve_alert"),
    path("classes/<int:pk>/incident-report/", views.incident_report, name="incident_report"),
    path(
        "incident-reports/<int:report_id>/resolve/",
        views.resolve_incident_report_view,
        name="resolve_incident_report",
    ),
    path("classes/<int:pk>/makeup-review/", views.makeup_review, name="makeup_review"),
]
