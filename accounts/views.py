from datetime import datetime, timedelta
from decimal import Decimal

from django.contrib import messages
from django.conf import settings
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q, Sum
from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from tutoring.models import (
    InvitationStatus,
    MatchingInvitation,
    Pairing,
    PairingReleaseReason,
    PairingReleaseRequest,
    PairingReleaseStatus,
    PairingStatus,
    QualificationDocument,
    QualificationStatus,
    Semester,
    ClassSession,
    ClassSessionStatus,
    ClassAlert,
    ClassAlertStatus,
    MakeupReview,
    MakeupReviewStatus,
)
from tutoring.forms import HoursDownloadForm, ScheduleClassForm, SemesterCreateForm
from tutoring.reporting import user_has_hour_records
from tutoring.services import (
    DAY_LABELS,
    LEARNING_DURATION_LABELS,
    LEVEL_LABELS,
    MAX_ACTIVE_TUTEES_PER_TUTOR,
    SKILL_LABELS,
    anonymous_tutee_candidates,
    anonymous_tutee_profile,
    anonymous_tutor_candidates,
    anonymous_tutor_profile,
    synchronize_matching_state,
    tutor_has_approved_qualification,
    class_is_valid,
    active_semester,
)

from .decorators import role_required
from .forms import (
    BilingualAuthenticationForm,
    BilingualSetPasswordForm,
    QualificationUploadForm,
    RecoveryVerificationForm,
    RegistrationLookupForm,
    TuteeRegistrationForm,
    TutorRegistrationForm,
)
from .models import (
    AuditLog,
    EducationLevel,
    IdentityCategory,
    ProgramSource,
    RegistrationDraft,
    Role,
    RosterEntry,
    SecurityQuestionAnswer,
    User,
)


def client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    return (forwarded.split(",")[0].strip() if forwarded else request.META.get("REMOTE_ADDR")) or None


def log_event(request, event_type, description, target_user=None, metadata=None):
    AuditLog.objects.create(
        actor=request.user if request.user.is_authenticated else None,
        target_user=target_user,
        event_type=event_type,
        description=description,
        ip_address=client_ip(request),
        metadata=metadata or {},
    )


class CSLLoginView(LoginView):
    template_name = "accounts/login.html"
    authentication_form = BilingualAuthenticationForm
    redirect_authenticated_user = True

    def form_valid(self, form):
        response = super().form_valid(form)
        log_event(self.request, "LOGIN_SUCCESS", "使用者登入成功 / User signed in", self.request.user)
        return response


def register(request):
    if request.user.is_authenticated:
        return redirect("accounts:dashboard")
    if request.method == "GET":
        old_draft_id = request.session.pop("registration_draft_id", None)
        if old_draft_id:
            RegistrationDraft.objects.filter(pk=old_draft_id).delete()
    form = RegistrationLookupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        roster = form.roster
        draft = form.save_draft()
        request.session["registration_draft_id"] = draft.pk
        target = "accounts:register_tutor" if roster.role == Role.TUTOR else "accounts:register_tutee"
        return redirect(target)
    return render(request, "accounts/register.html", {"form": form})


def _registration_roster(request, expected_role):
    draft_id = request.session.get("registration_draft_id")
    if not draft_id:
        return None
    draft = RegistrationDraft.objects.select_related("roster_entry").filter(pk=draft_id).first()
    roster = draft.roster_entry if draft else None
    if (
        not draft
        or draft.is_expired
        or not roster.is_enabled
        or roster.role != expected_role
        or roster.is_claimed
        or User.objects.filter(username=roster.student_id).exists()
    ):
        if draft:
            draft.delete()
        request.session.pop("registration_draft_id", None)
        return None
    return roster, draft


def _role_registration(request, role, form_class, template_name):
    if request.user.is_authenticated:
        return redirect("accounts:dashboard")
    registration = _registration_roster(request, role)
    if registration is None:
        messages.info(request, "請先輸入學號確認名冊身分。\nEnter your student ID to verify your roster role first.")
        return redirect("accounts:register")
    roster, draft = registration
    form = form_class(request.POST or None, request.FILES or None, roster=roster, draft=draft)
    if request.method == "POST" and form.is_valid():
        try:
            user = form.save()
        except ValidationError as error:
            request.session.pop("registration_draft_id", None)
            messages.error(request, " ".join(error.messages))
            return redirect("accounts:register")
        request.session.pop("registration_draft_id", None)
        log_event(
            request,
            "ACCOUNT_REGISTERED",
            "完成名冊註冊與個人檔案 / Roster account and profile registered",
            user,
            {"role": role},
        )
        login(request, user)
        messages.success(request, "註冊與個人資料已完成！ / Registration and profile are complete!")
        return redirect("accounts:dashboard")
    return render(request, template_name, {"form": form, "roster": roster})


def register_tutor(request):
    return _role_registration(request, Role.TUTOR, TutorRegistrationForm, "accounts/register_tutor.html")


def register_tutee(request):
    return _role_registration(request, Role.TUTEE, TuteeRegistrationForm, "accounts/register_tutee.html")


def _registration_preview(request, role, form_class, template_name):
    if not settings.DEBUG:
        raise Http404
    if role == Role.TUTOR:
        roster = RosterEntry(
            student_id="PREVIEW-TUTOR",
            name_zh="Tutor 預覽學生",
            name_en="Tutor Preview Student",
            role=Role.TUTOR,
            education_level=EducationLevel.MASTER,
            identity_category=IdentityCategory.LOCAL,
            program_source=ProgramSource.NOT_APPLICABLE,
        )
    else:
        roster = RosterEntry(
            student_id="PREVIEW-TUTEE",
            name_zh="Tutee 預覽學生",
            name_en="Tutee Preview Student",
            role=Role.TUTEE,
            education_level=EducationLevel.NOT_APPLICABLE,
            identity_category=IdentityCategory.INTERNATIONAL,
            program_source=ProgramSource.NTNU,
        )
    form = form_class(roster=roster, draft=None)
    return render(request, template_name, {"form": form, "roster": roster, "preview_mode": True})


@require_GET
def preview_tutor(request):
    return _registration_preview(request, Role.TUTOR, TutorRegistrationForm, "accounts/register_tutor.html")


@require_GET
def preview_tutee(request):
    return _registration_preview(request, Role.TUTEE, TuteeRegistrationForm, "accounts/register_tutee.html")


@login_required
def dashboard(request):
    synchronize_matching_state()
    current_semester = active_semester()
    today = timezone.localdate()
    matching_open = bool(
        current_semester
        and today >= current_semester.starts_on
        and today <= current_semester.ends_on
    )
    context = {"current_semester": current_semester, "matching_open": matching_open}
    if request.user.role == Role.ADMIN:
        semester_rows = list(Semester.objects.order_by("-starts_on"))
        overview_semesters = semester_rows
        overview_semester = current_semester or (overview_semesters[0] if overview_semesters else None)
        requested_semester_id = request.GET.get("class_semester")
        if requested_semester_id:
            overview_semester = next(
                (row for row in overview_semesters if str(row.pk) == requested_semester_id),
                overview_semester,
            )
        all_classes = list(
            ClassSession.objects.select_related(
                "pairing__semester", "pairing__tutor", "pairing__tutee"
            ).prefetch_related("attendances", "class_records", "confirmations", "class_alerts", "makeup_review")
            .filter(pairing__semester=overview_semester) if overview_semester else ClassSession.objects.none()
        )
        all_classes.sort(key=lambda row: (row.class_date, row.start_time), reverse=True)
        now = timezone.now()
        anomaly_classes = []
        for session in all_classes:
            session.is_official = class_is_valid(session)
            session.is_incomplete = (
                session.status != ClassSessionStatus.CANCELLED
                and session.ends_at < now
                and not session.is_official
            )
            session.active_alert_count = sum(row.status == ClassAlertStatus.ACTIVE for row in session.class_alerts.all())
            reasons = []
            if session.is_incomplete:
                if len(session.attendances.all()) < 2:
                    reasons.append("簽到未完成 / Attendance incomplete")
                if len(session.class_records.all()) < 2:
                    reasons.append("課堂紀錄未完成 / Records incomplete")
                if len(session.confirmations.all()) < 2:
                    reasons.append("互相確認未完成 / Confirmation incomplete")
            if session.active_alert_count:
                reasons.append("課堂通報待處理 / Active class alert")
            review = getattr(session, "makeup_review", None)
            if review and review.status in {MakeupReviewStatus.WAITING, MakeupReviewStatus.PENDING, MakeupReviewStatus.REJECTED}:
                reasons.append(f"補登：{review.get_status_display()}")
            session.anomaly_reasons = reasons
            if reasons:
                anomaly_classes.append(session)

        tutor_rows = []
        tutor_users = list(User.objects.filter(role=Role.TUTOR).order_by("name_zh", "username"))
        tutor_pairing_counts = {}
        if overview_semester:
            for pairing in Pairing.objects.filter(semester=overview_semester).select_related("tutor"):
                tutor_pairing_counts[pairing.tutor_id] = tutor_pairing_counts.get(pairing.tutor_id, 0) + 1
        tutor_class_map = {}
        for session in all_classes:
            tutor_class_map.setdefault(session.pairing.tutor_id, []).append(session)
        for tutor in tutor_users:
            rows = tutor_class_map.get(tutor.pk, [])
            active_rows = [row for row in rows if row.status != ClassSessionStatus.CANCELLED]
            exception_count = sum(row.is_incomplete for row in rows)
            tutor_rows.append({
                "tutor": tutor,
                "pairing_count": tutor_pairing_counts.get(tutor.pk, 0),
                "class_count": len(active_rows),
                "reserved_hours": sum((row.duration for row in active_rows), start=Decimal("0")),
                "verified_hours": sum((row.duration for row in active_rows if row.is_official), start=Decimal("0")),
                "exception_count": exception_count,
            })
        class_q = request.GET.get("class_q", "").strip().casefold()
        if class_q:
            tutor_rows = [row for row in tutor_rows if class_q in " ".join(filter(None, [
                row["tutor"].username, row["tutor"].name_zh, row["tutor"].name_en,
            ])).casefold()]
        class_status = request.GET.get("class_status", "all")
        if class_status == "incomplete":
            tutor_rows = [row for row in tutor_rows if row["exception_count"]]
        tutor_rows.sort(key=lambda row: (-row["exception_count"], row["tutor"].name_zh or row["tutor"].username))
        tutor_page = Paginator(tutor_rows, 20).get_page(request.GET.get("class_page"))
        active_overview_classes = [row for row in all_classes if row.status != ClassSessionStatus.CANCELLED]
        incomplete_classes = [row for row in all_classes if row.is_incomplete]
        context.update(
            {
                "roster_total": RosterEntry.objects.count(),
                "registered_total": User.objects.exclude(role=Role.ADMIN).count(),
                "tutor_total": User.objects.filter(role=Role.TUTOR).count(),
                "tutee_total": User.objects.filter(role=Role.TUTEE).count(),
                "pending_qualifications": QualificationDocument.objects.filter(status=QualificationStatus.PENDING).select_related("tutor")[:8],
                "recent_logs": AuditLog.objects.select_related("actor", "target_user")[:8],
                "active_pairing_total": Pairing.objects.filter(status=PairingStatus.ACTIVE).count(),
                "pending_invitation_total": MatchingInvitation.objects.filter(status=InvitationStatus.PENDING).count(),
                "pending_invitations": MatchingInvitation.objects.filter(status=InvitationStatus.PENDING).select_related(
                    "semester", "tutor", "tutee", "initiated_by"
                )[:20],
                "recent_pairings": Pairing.objects.select_related("semester", "tutor", "tutee")[:8],
                "pending_pairing_releases": PairingReleaseRequest.objects.filter(
                    status=PairingReleaseStatus.PENDING
                ).select_related("pairing__semester", "pairing__tutor", "pairing__tutee", "requested_by")[:30],
                "pairing_release_history": PairingReleaseRequest.objects.exclude(
                    status=PairingReleaseStatus.PENDING
                ).select_related(
                    "pairing__semester", "pairing__tutor", "pairing__tutee", "requested_by", "reviewed_by"
                )[:30],
                "semester_rows": semester_rows,
                "visible_semester_rows": [row for row in semester_rows if row.is_active],
                "new_semester_form": SemesterCreateForm(),
                "configured_non_past_semester_count": sum(row.ends_on >= today and row.is_active for row in semester_rows),
                "overview_semesters": overview_semesters,
                "overview_semester": overview_semester,
                "class_q": request.GET.get("class_q", ""),
                "class_status": class_status,
                "tutor_class_page": tutor_page,
                "class_overview_totals": {
                    "tutors": len(tutor_users),
                    "classes": len(active_overview_classes),
                    "reserved_hours": sum((row.duration for row in active_overview_classes), start=Decimal("0")),
                    "verified_hours": sum((row.duration for row in active_overview_classes if row.is_official), start=Decimal("0")),
                    "exceptions": len(incomplete_classes),
                },
                "anomaly_class_sessions": incomplete_classes[:5],
                "export_users": User.objects.exclude(role=Role.ADMIN).order_by("username"),
                "export_semesters": overview_semesters,
            }
        )
    elif request.user.role == Role.TUTOR:
        qualification = QualificationDocument.objects.filter(tutor=request.user).first()
        pairings = Pairing.objects.filter(
            semester=current_semester, tutor=request.user, status=PairingStatus.ACTIVE
        ).select_related("tutee") if current_semester else Pairing.objects.none()
        pending = MatchingInvitation.objects.filter(
            semester=current_semester, status=InvitationStatus.PENDING
        ).filter(Q(tutor=request.user)) if current_semester else MatchingInvitation.objects.none()
        sent_rows = []
        received_rows = []
        for invitation in pending.select_related("tutee__tutee_profile", "initiated_by"):
            row = {
                "id": invitation.pk,
                "expires_at": invitation.expires_at,
                "profile": anonymous_tutee_profile(invitation.tutee.tutee_profile),
            }
            (sent_rows if invitation.initiated_by_id == request.user.pk else received_rows).append(row)
        can_match = matching_open and tutor_has_approved_qualification(request.user) and pairings.count() < MAX_ACTIVE_TUTEES_PER_TUTOR
        candidates = anonymous_tutee_candidates(semester=current_semester, tutor=request.user) if can_match else []
        pending_tutee_ids = {row["profile"]["user_id"] for row in sent_rows + received_rows}
        for candidate in candidates:
            candidate["pending"] = candidate["user_id"] in pending_tutee_ids
        context.update(
            {
                "qualification": qualification,
                "qualification_form": QualificationUploadForm(),
                "active_pairings": pairings,
                "active_pairing_count": pairings.count(),
                "can_match": can_match,
                "tutee_candidates": candidates,
                "sent_invitations": sent_rows,
                "received_invitations": received_rows,
                "pairing_release_reason_choices": PairingReleaseReason.choices,
            }
        )
    else:
        pairings = Pairing.objects.filter(
            semester=current_semester, tutee=request.user, status=PairingStatus.ACTIVE
        ).select_related("tutor") if current_semester else Pairing.objects.none()
        pending = MatchingInvitation.objects.filter(
            semester=current_semester, tutee=request.user, status=InvitationStatus.PENDING
        ) if current_semester else MatchingInvitation.objects.none()
        sent_rows = []
        received_rows = []
        for invitation in pending.select_related("tutor__tutor_profile", "initiated_by"):
            row = {
                "id": invitation.pk,
                "expires_at": invitation.expires_at,
                "profile": anonymous_tutor_profile(invitation.tutor.tutor_profile),
            }
            (sent_rows if invitation.initiated_by_id == request.user.pk else received_rows).append(row)
        is_maryland = bool(
            request.user.roster_entry
            and request.user.roster_entry.program_source == ProgramSource.MARYLAND
        )
        candidates = (
            anonymous_tutor_candidates(semester=current_semester, tutee=request.user)
            if matching_open and is_maryland and not pairings.exists()
            else []
        )
        pending_tutor_ids = {row["profile"]["user_id"] for row in sent_rows + received_rows}
        for candidate in candidates:
            candidate["pending"] = candidate["user_id"] in pending_tutor_ids
        context.update(
            {
                "active_pairings": pairings,
                "is_maryland": is_maryland,
                "tutor_candidates": candidates,
                "sent_invitations": sent_rows,
                "received_invitations": received_rows,
                "pairing_release_reason_choices": PairingReleaseReason.choices,
            }
        )
    if request.user.role in {Role.TUTOR, Role.TUTEE}:
        participant_filter = Q(pairing__tutor=request.user) if request.user.role == Role.TUTOR else Q(pairing__tutee=request.user)
        class_sessions = ClassSession.objects.filter(participant_filter).select_related(
            "pairing__semester", "pairing__tutor", "pairing__tutee"
        ).prefetch_related("attendances", "class_records", "confirmations", "class_alerts", "makeup_review")
        all_rows = list(class_sessions.order_by("class_date", "start_time"))
        for session in all_rows:
            session.is_official = class_is_valid(session)
            session.my_attendance = next(
                (row for row in session.attendances.all() if row.participant_id == request.user.pk), None
            )
            session.my_record = next(
                (row for row in session.class_records.all() if row.author_id == request.user.pk), None
            )
        rows = [
            session for session in all_rows
            if current_semester and session.pairing.semester_id == current_semester.pk
        ]
        reserved_hours = sum(
            (session.duration for session in rows if session.status != ClassSessionStatus.CANCELLED),
            start=0,
        )
        official_hours = sum(
            (session.duration for session in rows if session.is_official),
            start=0,
        )
        now = timezone.now()
        upcoming_cutoff = now + timedelta(days=7)
        upcoming_sessions = [session for session in rows if session.ends_at >= now and session.starts_at <= upcoming_cutoff]
        future_sessions = [session for session in rows if session.starts_at > upcoming_cutoff]
        past_sessions = sorted(
            (session for session in rows if session.ends_at < now),
            key=lambda session: (session.class_date, session.start_time),
            reverse=True,
        )
        semester_history = []
        semester_ids = {session.pairing.semester_id for session in all_rows}
        history_semesters = Semester.objects.filter(pk__in=semester_ids).order_by("-starts_on")
        for semester in history_semesters:
            semester_rows = [session for session in all_rows if session.pairing.semester_id == semester.pk]
            history_rows = sorted(
                (session for session in semester_rows if session.ends_at < now),
                key=lambda session: (session.class_date, session.start_time),
                reverse=True,
            )
            semester_history.append({
                "semester": semester,
                "sessions": history_rows,
                "reserved_hours": sum(
                    (session.duration for session in semester_rows if session.status != ClassSessionStatus.CANCELLED),
                    start=0,
                ),
                "official_hours": sum((session.duration for session in semester_rows if session.is_official), start=0),
                "session_count": sum(
                    session.status != ClassSessionStatus.CANCELLED for session in semester_rows
                ),
                "past_session_count": len(history_rows),
            })
        context.update(
            {
                "class_sessions": rows,
                "upcoming_sessions": upcoming_sessions,
                "future_sessions": future_sessions,
                "past_sessions": past_sessions,
                "reserved_hours": reserved_hours,
                "official_hours": official_hours,
                "schedule_form": ScheduleClassForm(tutor=request.user) if request.user.role == Role.TUTOR else None,
                "hours_download_allowed": user_has_hour_records(request.user),
                "hours_download_form": HoursDownloadForm() if user_has_hour_records(request.user) else None,
                "semester_history": semester_history,
                "cumulative_reserved_hours": sum(
                    (session.duration for session in all_rows if session.status != ClassSessionStatus.CANCELLED),
                    start=0,
                ),
                "cumulative_official_hours": sum(
                    (session.duration for session in all_rows if session.is_official), start=0
                ),
                "cumulative_session_count": sum(
                    session.status != ClassSessionStatus.CANCELLED for session in all_rows
                ),
            }
        )
    elif request.user.role == Role.ADMIN:
        makeup_reviews = list(
            MakeupReview.objects.select_related(
                "session__pairing__semester", "session__pairing__tutor", "session__pairing__tutee", "reviewed_by"
            ).prefetch_related("session__attendances", "session__class_records").order_by("-created_at")
        )
        for review in makeup_reviews:
            has_makeup_attendance = any(row.is_makeup for row in review.session.attendances.all())
            has_makeup_record = any(row.is_makeup for row in review.session.class_records.all())
            if has_makeup_attendance and has_makeup_record:
                review.category_label = "補簽到＋補課堂紀錄"
                review.category_label_en = "Attendance + record"
            elif has_makeup_attendance:
                review.category_label = "補簽到"
                review.category_label_en = "Attendance"
            else:
                review.category_label = "補課堂紀錄"
                review.category_label_en = "Class record"
        status_definitions = (
            (MakeupReviewStatus.PENDING, "待管理員審核", "Pending admin review", True),
            (MakeupReviewStatus.WAITING, "等待雙方確認", "Waiting for mutual confirmation", False),
            (MakeupReviewStatus.APPROVED, "已核准", "Approved", False),
            (MakeupReviewStatus.REJECTED, "未核准", "Rejected", False),
        )
        context["makeup_review_sections"] = [
            {
                "status": status,
                "label": label,
                "label_en": label_en,
                "open": is_open,
                "rows": [review for review in makeup_reviews if review.status == status],
            }
            for status, label, label_en, is_open in status_definitions
        ]
        context["pending_makeup_reviews"] = [
            review for review in makeup_reviews if review.status == MakeupReviewStatus.PENDING
        ]
        context["active_class_alerts"] = ClassAlert.objects.filter(
            status=ClassAlertStatus.ACTIVE
        ).select_related("session__pairing__semester", "reporter", "subject")
    return render(request, "dashboard/index.html", context)


@login_required
def admin_tutor_schedule(request, user_id):
    if request.user.role != Role.ADMIN:
        raise Http404
    tutor = get_object_or_404(User, pk=user_id, role=Role.TUTOR)
    semesters = list(Semester.objects.order_by("-starts_on"))
    semester = active_semester() or (semesters[0] if semesters else None)
    requested_semester_id = request.GET.get("semester")
    if requested_semester_id:
        semester = next((row for row in semesters if str(row.pk) == requested_semester_id), semester)
    sessions = []
    if semester:
        sessions = list(
            ClassSession.objects.filter(pairing__tutor=tutor, pairing__semester=semester)
            .select_related("pairing__semester", "pairing__tutee")
            .prefetch_related("attendances", "class_records", "confirmations", "class_alerts", "makeup_review")
            .order_by("class_date", "start_time")
        )
    now = timezone.now()
    exception_count = 0
    for session in sessions:
        session.is_official = class_is_valid(session)
        reasons = []
        if session.status != ClassSessionStatus.CANCELLED and session.ends_at < now and not session.is_official:
            if len(session.attendances.all()) < 2:
                reasons.append("簽到未完成 / Attendance incomplete")
            if len(session.class_records.all()) < 2:
                reasons.append("課堂紀錄未完成 / Records incomplete")
            if len(session.confirmations.all()) < 2:
                reasons.append("互相確認未完成 / Confirmation incomplete")
        if any(row.status == ClassAlertStatus.ACTIVE for row in session.class_alerts.all()):
            reasons.append("課堂通報待處理 / Active class alert")
        review = getattr(session, "makeup_review", None)
        if review and review.status in {MakeupReviewStatus.WAITING, MakeupReviewStatus.PENDING, MakeupReviewStatus.REJECTED}:
            reasons.append(f"補登：{review.get_status_display()}")
        session.anomaly_reasons = reasons
        exception_count += bool(reasons)
    active_rows = [row for row in sessions if row.status != ClassSessionStatus.CANCELLED]
    future_sessions = [row for row in active_rows if row.ends_at >= now]
    past_sessions = list(reversed([row for row in sessions if row.ends_at < now or row.status == ClassSessionStatus.CANCELLED]))
    pairings = Pairing.objects.filter(tutor=tutor, semester=semester).select_related("tutee") if semester else Pairing.objects.none()
    return render(request, "accounts/admin_tutor_schedule.html", {
        "tutor": tutor,
        "semesters": semesters,
        "selected_semester": semester,
        "pairings": pairings,
        "future_sessions": future_sessions,
        "past_sessions": past_sessions,
        "class_count": len(active_rows),
        "reserved_hours": sum((row.duration for row in active_rows), start=Decimal("0")),
        "verified_hours": sum((row.duration for row in active_rows if row.is_official), start=Decimal("0")),
        "exception_count": exception_count,
    })


def _skill_ratings(profile, labels):
    return [
        {"label": label, "label_en": label_en, "score": getattr(profile, field)}
        for field, label, label_en in labels
    ]


@login_required
def profile(request):
    """Present the signed-in user's full profile outside the matching workflow."""
    context = {
        "roster": request.user.roster_entry,
        "role_profile": None,
        "skill_ratings": [],
        "availability_days": [],
        "availability_slots": [],
    }
    if request.user.role == Role.TUTOR:
        role_profile = getattr(request.user, "tutor_profile", None)
        context.update(
            {
                "role_profile": role_profile,
                "qualification": QualificationDocument.objects.filter(tutor=request.user).first(),
                "profile_kind": "tutor",
            }
        )
        if role_profile:
            context.update(
                {
                    "skill_ratings": _skill_ratings(
                        role_profile,
                        [
                            ("level_listening", "聽力教學", "Listening"),
                            ("level_speaking", "口說教學", "Speaking"),
                            ("level_reading", "閱讀教學", "Reading"),
                            ("level_writing", "寫作教學", "Writing"),
                        ],
                    ),
                    "availability_days": [DAY_LABELS.get(day, day) for day in role_profile.available_days],
                    "availability_slots": role_profile.available_time_slots,
                }
            )
    elif request.user.role == Role.TUTEE:
        role_profile = getattr(request.user, "tutee_profile", None)
        context.update({"role_profile": role_profile, "profile_kind": "tutee"})
        if role_profile:
            context.update(
                {
                    "skill_ratings": _skill_ratings(
                        role_profile,
                        [
                            ("level_listening", "聽力", "Listening"),
                            ("level_speaking", "口說", "Speaking"),
                            ("level_reading", "閱讀", "Reading"),
                            ("level_writing", "寫作", "Writing"),
                        ],
                    ),
                    "overall_level": LEVEL_LABELS.get(role_profile.overall_level, role_profile.overall_level),
                    "learning_duration": LEARNING_DURATION_LABELS.get(
                        role_profile.learning_duration, role_profile.learning_duration
                    ),
                    "target_skills": [SKILL_LABELS.get(skill, skill) for skill in role_profile.target_skills],
                    "availability_days": [DAY_LABELS.get(day, day) for day in role_profile.preferred_days],
                    "availability_slots": role_profile.preferred_time_slots,
                }
            )
    else:
        context["profile_kind"] = "admin"
    return render(request, "accounts/profile.html", context)


@login_required
def matched_profile(request, user_id):
    """Show a full profile only when the viewer and subject have an active pairing."""
    counterpart = get_object_or_404(User.objects.select_related("roster_entry"), pk=user_id)
    pairing = (
        Pairing.objects.filter(status=PairingStatus.ACTIVE)
        .filter(
            Q(tutor=request.user, tutee=counterpart)
            | Q(tutee=request.user, tutor=counterpart)
        )
        .select_related("semester")
        .first()
    )
    if not pairing:
        raise Http404

    context = {
        "counterpart": counterpart,
        "pairing": pairing,
        "roster": counterpart.roster_entry,
        "role_profile": None,
        "skill_ratings": [],
        "availability_days": [],
        "availability_slots": [],
    }
    if counterpart.role == Role.TUTOR:
        role_profile = getattr(counterpart, "tutor_profile", None)
        context.update({"role_profile": role_profile, "profile_kind": "tutor"})
        if role_profile:
            context.update(
                {
                    "skill_ratings": _skill_ratings(
                        role_profile,
                        [
                            ("level_listening", "聽力教學", "Listening"),
                            ("level_speaking", "口說教學", "Speaking"),
                            ("level_reading", "閱讀教學", "Reading"),
                            ("level_writing", "寫作教學", "Writing"),
                        ],
                    ),
                    "availability_days": [DAY_LABELS.get(day, day) for day in role_profile.available_days],
                    "availability_slots": role_profile.available_time_slots,
                }
            )
    elif counterpart.role == Role.TUTEE:
        role_profile = getattr(counterpart, "tutee_profile", None)
        context.update({"role_profile": role_profile, "profile_kind": "tutee"})
        if role_profile:
            context.update(
                {
                    "skill_ratings": _skill_ratings(
                        role_profile,
                        [
                            ("level_listening", "聽力", "Listening"),
                            ("level_speaking", "口說", "Speaking"),
                            ("level_reading", "閱讀", "Reading"),
                            ("level_writing", "寫作", "Writing"),
                        ],
                    ),
                    "overall_level": LEVEL_LABELS.get(role_profile.overall_level, role_profile.overall_level),
                    "learning_duration": LEARNING_DURATION_LABELS.get(
                        role_profile.learning_duration, role_profile.learning_duration
                    ),
                    "target_skills": [SKILL_LABELS.get(skill, skill) for skill in role_profile.target_skills],
                    "availability_days": [DAY_LABELS.get(day, day) for day in role_profile.preferred_days],
                    "availability_slots": role_profile.preferred_time_slots,
                }
            )
    return render(request, "accounts/matched_profile.html", context)


@login_required
def handbook(request):
    roster = request.user.roster_entry
    return render(
        request,
        "accounts/handbook.html",
        {
            "roster": roster,
            "is_maryland": bool(roster and roster.program_source == ProgramSource.MARYLAND),
        },
    )


@role_required(Role.TUTOR)
@require_POST
def upload_qualification(request):
    current = QualificationDocument.objects.filter(tutor=request.user).first()
    form = QualificationUploadForm(request.POST, request.FILES, instance=current)
    if form.is_valid():
        document = form.save(commit=False)
        document.tutor = request.user
        document.original_filename = request.FILES["file"].name
        document.status = QualificationStatus.PENDING
        document.review_note = ""
        document.reviewed_by = None
        document.reviewed_at = None
        document.save()
        log_event(request, "QUALIFICATION_UPLOADED", "提交資格證明 / Qualification submitted", request.user)
        messages.success(request, "資格證明已送出審核。 / Your qualification document was submitted for review.")
    else:
        for errors in form.errors.values():
            for error in errors:
                messages.error(request, error)
    return redirect("accounts:dashboard")


@role_required(Role.ADMIN)
@require_POST
@transaction.atomic
def review_qualification(request, pk):
    document = get_object_or_404(QualificationDocument.objects.select_for_update(), pk=pk)
    action = request.POST.get("action")
    if action not in {"approve", "reject"}:
        return HttpResponseBadRequest("Invalid review action")
    document.status = QualificationStatus.APPROVED if action == "approve" else QualificationStatus.REJECTED
    document.review_note = request.POST.get("review_note", "").strip()
    document.reviewed_by = request.user
    document.reviewed_at = timezone.now()
    document.save()
    log_event(
        request,
        "QUALIFICATION_REVIEWED",
        "資格證明完成審核 / Qualification reviewed",
        document.tutor,
        {"result": document.status},
    )
    messages.success(request, "審核結果已儲存。 / Review result saved.")
    return redirect("accounts:dashboard")


def recover_account(request):
    if request.user.is_authenticated:
        return redirect("accounts:dashboard")
    form = RecoveryVerificationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        student_id = form.cleaned_data["student_id"].strip().upper()
        throttle_key = f"recovery:{client_ip(request)}:{student_id}"
        attempts = cache.get(throttle_key, 0)
        if attempts >= 5:
            messages.error(request, "嘗試次數過多，請 15 分鐘後再試。 / Too many attempts. Please try again in 15 minutes.")
            return render(request, "accounts/recover.html", {"form": form})
        cache.set(throttle_key, attempts + 1, 900)
        user = User.objects.filter(username=student_id, is_active=True).first()
        verified = False
        if user:
            questions = SecurityQuestionAnswer.objects.filter(user=user).first()
            selected = [form.cleaned_data[f"question_{index}"] for index in range(1, 4)]
            expected = [questions.question_1, questions.question_2, questions.question_3] if questions else []
            answers = [form.cleaned_data[f"answer_{index}"] for index in range(1, 4)]
            verified = bool(questions and selected == expected and questions.check_answers(answers))
        if verified:
            request.session["recovery_user_id"] = user.pk
            request.session["recovery_verified_at"] = timezone.now().isoformat()
            cache.delete(throttle_key)
            log_event(request, "RECOVERY_VERIFIED", "安全問題驗證成功 / Security questions verified", user)
            return redirect("accounts:set_recovered_password")
        log_event(request, "RECOVERY_FAILED", "帳號恢復驗證失敗 / Account recovery verification failed")
        messages.error(request, "資料無法驗證，請重新確認或洽系辦。 / We could not verify the information. Please check again or contact the office.")
    return render(request, "accounts/recover.html", {"form": form})


def set_recovered_password(request):
    user_id = request.session.get("recovery_user_id")
    verified_at = request.session.get("recovery_verified_at")
    if not user_id or not verified_at:
        return redirect("accounts:recover")
    try:
        timestamp = datetime.fromisoformat(verified_at)
    except ValueError:
        return redirect("accounts:recover")
    if timezone.now() - timestamp > timedelta(minutes=10):
        request.session.pop("recovery_user_id", None)
        request.session.pop("recovery_verified_at", None)
        messages.error(request, "驗證已逾時，請重新操作。 / Verification expired. Please try again.")
        return redirect("accounts:recover")
    user = get_object_or_404(User, pk=user_id)
    form = BilingualSetPasswordForm(user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        request.session.flush()
        log_event(request, "PASSWORD_RECOVERED", "透過安全問題重設密碼 / Password reset via security questions", user)
        messages.success(request, "密碼已更新，請重新登入。 / Password updated. Please sign in again.")
        return redirect("accounts:login")
    return render(request, "accounts/set_password.html", {"form": form})
