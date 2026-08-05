from django.contrib.auth.views import LogoutView
from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("", views.CSLLoginView.as_view(), name="login"),
    path("register/", views.register, name="register"),
    path("register/tutor/", views.register_tutor, name="register_tutor"),
    path("register/tutee/", views.register_tutee, name="register_tutee"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("dashboard/tutors/<int:user_id>/schedule/", views.admin_tutor_schedule, name="admin_tutor_schedule"),
    path("dashboard/users/<int:user_id>/profile/", views.admin_user_profile, name="admin_user_profile"),
    path("profile/", views.profile, name="profile"),
    path("profile/update/", views.update_profile, name="update_profile"),
    path("matching/profile/<int:user_id>/", views.matched_profile, name="matched_profile"),
    path("handbook/", views.handbook, name="handbook"),
    path("class-documents/", views.class_documents, name="class_documents"),
    path("class-documents/<int:pk>/download/", views.download_class_document, name="download_class_document"),
    path("qualification/upload/", views.upload_qualification, name="upload_qualification"),
    path("qualification/<int:pk>/review/", views.review_qualification, name="review_qualification"),
    path("roster/import/", views.roster_import, name="roster_import"),
    path("roster/import/quick/<str:category_code>/", views.roster_import_quick, name="roster_import_quick"),
    path("roster/import/template/<str:file_format>/", views.download_roster_template, name="roster_import_template"),
    path("recover/", views.recover_account, name="recover"),
    path("recover/new-password/", views.set_recovered_password, name="set_recovered_password"),
]

urlpatterns += [
    path("preview/tutor/", views.preview_tutor, name="preview_tutor"),
    path("preview/tutee/", views.preview_tutee, name="preview_tutee"),
]
