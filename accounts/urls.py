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
    path("profile/", views.profile, name="profile"),
    path("matching/profile/<int:user_id>/", views.matched_profile, name="matched_profile"),
    path("handbook/", views.handbook, name="handbook"),
    path("qualification/upload/", views.upload_qualification, name="upload_qualification"),
    path("qualification/<int:pk>/review/", views.review_qualification, name="review_qualification"),
    path("recover/", views.recover_account, name="recover"),
    path("recover/new-password/", views.set_recovered_password, name="set_recovered_password"),
]

urlpatterns += [
    path("preview/tutor/", views.preview_tutor, name="preview_tutor"),
    path("preview/tutee/", views.preview_tutee, name="preview_tutee"),
]
