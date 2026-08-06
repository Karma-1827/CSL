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
from django.db.models import Q
from django.http import FileResponse, Http404, HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
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
    ClassDocument,
    ClassSession,
    ClassSessionStatus,
    ClassAlert,
    ClassAlertStatus,
    HourAdjustment,
    IncidentReport,
    IncidentReportStatus,
    MakeupReview,
    MakeupReviewStatus,
)
from tutoring.forms import AdminPairingForm, HoursDownloadForm, ScheduleClassForm, SemesterCreateForm, SemesterSettingsForm
from tutoring.reporting import user_has_hour_records
from tutoring.services import (
    DAY_LABELS,
    LEARNING_DURATION_LABELS,
    LEVEL_LABELS,
    MAX_ACTIVE_TUTEES_PER_TUTOR,
    SKILL_LABELS,
    annotate_conversation_summaries,
    anonymous_tutee_candidates,
    anonymous_tutee_profile,
    anonymous_tutor_candidates,
    anonymous_tutor_profile,
    synchronize_matching_state,
    tutor_has_approved_qualification,
    class_is_valid,
    active_semester,
    semester_applies_to_user,
    user_program,
    visible_class_document_programs,
    visible_class_documents,
)

from .decorators import role_required
from .forms import (
    DAYS,
    GENDER_CHOICES,
    OVERALL_LEVEL_CHOICES,
    SKILL_CHOICES,
    TIME_SLOTS,
    BilingualAuthenticationForm,
    BilingualSetPasswordForm,
    QualificationUploadForm,
    client_ip,
    RecoveryVerificationForm,
    RegistrationLookupForm,
    RosterImportForm,
    TuteeProfileEditForm,
    TuteeRegistrationForm,
    TutorProfileEditForm,
    TutorRegistrationForm,
)
from .models import (
    AuditLog,
    PartnerProgram,
    RegistrationDraft,
    Role,
    RosterEntry,
    SecurityQuestionAnswer,
    User,
)
from .services import (
    RosterImportFileError,
    import_roster_entries,
    import_roster_ids,
    roster_template_csv_bytes,
    roster_template_xlsx_bytes,
)


def log_event(request, event_type, description, target_user=None, metadata=None):
    AuditLog.record(
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
        request.session.pop("registration_confirmed", None)
        if old_draft_id:
            RegistrationDraft.objects.filter(pk=old_draft_id).delete()
    form = RegistrationLookupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        draft = form.save_draft()
        request.session["registration_draft_id"] = draft.pk
        request.session.pop("registration_confirmed", None)
        return redirect("accounts:register_confirm")
    return render(request, "accounts/register.html", {"form": form})


def _pending_registration(request):
    """The roster/draft pair behind the current session's registration attempt, or None
    if there isn't a still-valid one. Doesn't check the roster's role — see
    _registration_roster() for the role-specific wrapper used by stage-2 views."""
    draft_id = request.session.get("registration_draft_id")
    if not draft_id:
        return None
    draft = RegistrationDraft.objects.select_related("roster_entry").filter(pk=draft_id).first()
    roster = draft.roster_entry if draft else None
    if (
        not draft
        or draft.is_expired
        or not roster.is_enabled
        or roster.is_claimed
        or User.objects.filter(username=roster.student_id).exists()
    ):
        if draft:
            draft.delete()
        request.session.pop("registration_draft_id", None)
        request.session.pop("registration_confirmed", None)
        return None
    return roster, draft


def register_confirm(request):
    """Item 7: a mandatory "confirm your student ID" step between stage 1 (roster lookup +
    password) and stage 2 (Tutor/Tutee profile), so the account/roster claim isn't just one
    accidental click away from the ID lookup form. Confirming only flips a session flag —
    it never touches draft.expires_at, so the original 30-minute window still applies."""
    if request.user.is_authenticated:
        return redirect("accounts:dashboard")
    registration = _pending_registration(request)
    if registration is None:
        messages.info(request, "請先輸入學號確認名冊身分。\nEnter your student ID to verify your roster role first.")
        return redirect("accounts:register")
    roster, draft = registration
    if request.method == "POST":
        request.session["registration_confirmed"] = True
        target = "accounts:register_tutor" if roster.role == Role.TUTOR else "accounts:register_tutee"
        return redirect(target)
    return render(request, "accounts/register_confirm.html", {"roster": roster})


def _registration_roster(request, expected_role):
    registration = _pending_registration(request)
    if registration is None:
        return None
    roster, draft = registration
    if roster.role != expected_role:
        draft.delete()
        request.session.pop("registration_draft_id", None)
        request.session.pop("registration_confirmed", None)
        return None
    return roster, draft


def _role_registration(request, role, form_class, template_name):
    if request.user.is_authenticated:
        return redirect("accounts:dashboard")
    registration = _registration_roster(request, role)
    if registration is None:
        messages.info(request, "請先輸入學號確認名冊身分。\nEnter your student ID to verify your roster role first.")
        return redirect("accounts:register")
    if not request.session.get("registration_confirmed"):
        return redirect("accounts:register_confirm")
    roster, draft = registration
    form = form_class(request.POST or None, request.FILES or None, roster=roster, draft=draft)
    if request.method == "POST" and form.is_valid():
        try:
            user = form.save()
        except ValidationError as error:
            request.session.pop("registration_draft_id", None)
            request.session.pop("registration_confirmed", None)
            messages.error(request, " ".join(error.messages))
            return redirect("accounts:register")
        request.session.pop("registration_draft_id", None)
        request.session.pop("registration_confirmed", None)
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
            role=Role.TUTOR,
        )
    else:
        preview_program = PartnerProgram.objects.filter(code="NTNU").first() or PartnerProgram(
            code="NTNU", name_zh="師大外籍生", name_en="NTNU international student"
        )
        roster = RosterEntry(
            student_id="PREVIEW-TUTEE",
            role=Role.TUTEE,
            program=preview_program,
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
    current_semester = active_semester(program=user_program(request.user))
    today = timezone.localdate()
    matching_open = bool(
        current_semester
        and today >= current_semester.starts_on
        and today <= current_semester.ends_on
        and semester_applies_to_user(current_semester, request.user)
    )
    context = {"current_semester": current_semester, "matching_open": matching_open}
    if request.user.role == Role.ADMIN:
        semester_rows = list(Semester.objects.order_by("-starts_on"))
        for row in semester_rows:
            row.edit_form = SemesterSettingsForm(instance=row, prefix=f"semester-{row.pk}")
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
                "admin_pairing_form": AdminPairingForm(),
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
                "semester_ids_with_pairings": set(
                    Pairing.objects.filter(semester__in=semester_rows).values_list("semester_id", flat=True)
                ),
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
                "roster_import_form": RosterImportForm(),
                "quick_import_programs": PartnerProgram.objects.filter(is_active=True).order_by("name_zh"),
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
        candidate_filters = {
            "gender": request.GET.get("tutee_gender", "").strip(),
            "overall_level": request.GET.get("tutee_level", "").strip(),
            "native_language": request.GET.get("tutee_language", "").strip(),
            "target_skills": request.GET.getlist("tutee_skill"),
            "days": request.GET.getlist("tutee_day"),
            "time_slots": request.GET.getlist("tutee_slot"),
        }
        candidates = (
            anonymous_tutee_candidates(semester=current_semester, tutor=request.user, filters=candidate_filters)
            if can_match else []
        )
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
                "tutee_candidate_filters": candidate_filters,
                "tutee_gender_choices": [choice for choice in GENDER_CHOICES if choice[0]],
                "tutee_level_choices": OVERALL_LEVEL_CHOICES,
                "tutee_skill_choices": SKILL_CHOICES,
                "tutee_day_choices": DAYS,
                "tutee_slot_choices": TIME_SLOTS,
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
        can_initiate_invitation = bool(
            request.user.roster_entry
            and request.user.roster_entry.program_id
            and request.user.roster_entry.program.allow_tutee_initiate_invitation
        )
        tutor_candidate_filters = {
            "gender": request.GET.get("tutor_gender", "").strip(),
            "native_language": request.GET.get("tutor_language", "").strip(),
            "days": request.GET.getlist("tutor_day"),
            "time_slots": request.GET.getlist("tutor_slot"),
        }
        candidates = (
            anonymous_tutor_candidates(semester=current_semester, tutee=request.user, filters=tutor_candidate_filters)
            if matching_open and can_initiate_invitation and not pairings.exists()
            else []
        )
        pending_tutor_ids = {row["profile"]["user_id"] for row in sent_rows + received_rows}
        for candidate in candidates:
            candidate["pending"] = candidate["user_id"] in pending_tutor_ids
        context.update(
            {
                "active_pairings": pairings,
                "is_maryland": can_initiate_invitation,
                "tutor_candidates": candidates,
                "tutor_candidate_filters": tutor_candidate_filters,
                "tutor_gender_choices": [choice for choice in GENDER_CHOICES if choice[0]],
                "tutor_day_choices": DAYS,
                "tutor_slot_choices": TIME_SLOTS,
                "sent_invitations": sent_rows,
                "received_invitations": received_rows,
                "pairing_release_reason_choices": PairingReleaseReason.choices,
            }
        )
    if request.user.role in {Role.TUTOR, Role.TUTEE}:
        participant_pairings = list(
            Pairing.objects.filter(
                Q(tutor=request.user) | Q(tutee=request.user)
            ).select_related("semester", "tutor", "tutee").order_by("-started_at")
        )
        conversation_pairings = annotate_conversation_summaries(participant_pairings, viewer=request.user)
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
                "hours_download_form": HoursDownloadForm(user=request.user) if user_has_hour_records(request.user) else None,
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
                "active_conversations": [
                    pairing for pairing in conversation_pairings if pairing.status == PairingStatus.ACTIVE
                ],
                "ended_conversations": [
                    pairing for pairing in conversation_pairings if pairing.status == PairingStatus.ENDED
                ],
                "unread_message_total": sum(pairing.unread_count for pairing in conversation_pairings),
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
        context["class_alert_history"] = ClassAlert.objects.filter(
            status=ClassAlertStatus.RESOLVED
        ).select_related("session__pairing__semester", "reporter", "resolved_by")[:30]
        context["pending_incident_reports"] = IncidentReport.objects.filter(
            status=IncidentReportStatus.PENDING
        ).select_related("session__pairing__semester", "reporter")
        context["incident_report_history"] = IncidentReport.objects.filter(
            status=IncidentReportStatus.RESOLVED
        ).select_related("session__pairing__semester", "reporter", "resolved_by")[:30]
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


@login_required
def admin_user_profile(request, user_id):
    """Read-only aggregated view of one Tutor/Tutee's roster, qualification, pairings, hours, and reports."""
    if request.user.role != Role.ADMIN:
        raise Http404
    subject = get_object_or_404(
        User.objects.select_related("roster_entry", "roster_entry__program"),
        pk=user_id, role__in=[Role.TUTOR, Role.TUTEE],
    )
    context = {"subject": subject, "roster": subject.roster_entry}
    context.update(_role_profile_context(subject))

    if subject.role == Role.TUTOR:
        context["qualification"] = QualificationDocument.objects.filter(tutor=subject).select_related("reviewed_by").first()

    context["pairings"] = list(
        Pairing.objects.filter(Q(tutor=subject) | Q(tutee=subject))
        .select_related("semester", "tutor", "tutee")
        .order_by("-started_at")
    )

    participant_filter = Q(pairing__tutor=subject) if subject.role == Role.TUTOR else Q(pairing__tutee=subject)
    sessions = list(
        ClassSession.objects.filter(participant_filter)
        .select_related("pairing__semester", "pairing__tutor", "pairing__tutee")
        .prefetch_related("attendances", "class_records", "confirmations")
        .order_by("class_date", "start_time")
    )
    for session in sessions:
        session.is_official = class_is_valid(session)
    active_sessions = [row for row in sessions if row.status != ClassSessionStatus.CANCELLED]

    hour_adjustments = list(
        HourAdjustment.objects.filter(user=subject)
        .select_related("semester", "program", "created_by")
        .order_by("-created_at")
    )
    adjustment_by_semester = {}
    for adjustment in hour_adjustments:
        adjustment_by_semester[adjustment.semester_id] = (
            adjustment_by_semester.get(adjustment.semester_id, Decimal("0")) + adjustment.hours
        )
    total_adjustment_hours = sum((row.hours for row in hour_adjustments), start=Decimal("0"))

    semester_ids = {session.pairing.semester_id for session in sessions} | set(adjustment_by_semester)
    semester_history = []
    for semester in Semester.objects.filter(pk__in=semester_ids).order_by("-starts_on"):
        rows = [row for row in active_sessions if row.pairing.semester_id == semester.pk]
        adjustment_hours = adjustment_by_semester.get(semester.pk, Decimal("0"))
        semester_history.append(
            {
                "semester": semester,
                "session_count": len(rows),
                "reserved_hours": sum((row.duration for row in rows), start=Decimal("0")),
                "verified_hours": sum((row.duration for row in rows if row.is_official), start=Decimal("0")) + adjustment_hours,
                "adjustment_hours": adjustment_hours,
            }
        )
    context.update(
        {
            "semester_history": semester_history,
            "hour_adjustments": hour_adjustments,
            "total_adjustment_hours": total_adjustment_hours,
            "cumulative_session_count": len(active_sessions),
            "cumulative_reserved_hours": sum((row.duration for row in active_sessions), start=Decimal("0")),
            "cumulative_verified_hours": sum(
                (row.duration for row in active_sessions if row.is_official), start=Decimal("0")
            ) + total_adjustment_hours,
        }
    )

    context["class_alerts"] = ClassAlert.objects.filter(
        Q(reporter=subject) | Q(subject=subject)
    ).select_related("session__pairing", "resolved_by").order_by("-created_at")[:20]
    context["incident_reports"] = IncidentReport.objects.filter(
        Q(session__pairing__tutor=subject) | Q(session__pairing__tutee=subject)
    ).select_related("session__pairing", "reporter", "resolved_by").order_by("-created_at")[:20]

    return render(request, "accounts/admin_user_profile.html", context)


def _skill_ratings(profile, labels):
    return [
        {"label": label, "label_en": label_en, "score": getattr(profile, field)}
        for field, label, label_en in labels
    ]


def _role_profile_context(subject):
    """Build the shared teaching/learning profile display data for a Tutor or Tutee."""
    context = {
        "role_profile": None,
        "skill_ratings": [],
        "availability_days": [],
        "availability_slots": [],
        "profile_kind": None,
    }
    if subject.role == Role.TUTOR:
        role_profile = getattr(subject, "tutor_profile", None)
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
    elif subject.role == Role.TUTEE:
        role_profile = getattr(subject, "tutee_profile", None)
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
    return context


@login_required
def profile(request):
    """Present the signed-in user's full profile outside the matching workflow."""
    context = {"roster": request.user.roster_entry, "edit_form": None}
    context.update(_role_profile_context(request.user))
    role_profile = context["role_profile"]
    if request.user.role == Role.TUTOR:
        context["qualification"] = QualificationDocument.objects.filter(tutor=request.user).first()
        if role_profile:
            context["edit_form"] = TutorProfileEditForm(profile=role_profile, user=request.user)
    elif request.user.role == Role.TUTEE and role_profile:
        context["edit_form"] = TuteeProfileEditForm(profile=role_profile, user=request.user)
    return render(request, "accounts/profile.html", context)


@login_required
@require_POST
def update_profile(request):
    role_profile = getattr(request.user, "tutor_profile", None) if request.user.role == Role.TUTOR else (
        getattr(request.user, "tutee_profile", None) if request.user.role == Role.TUTEE else None
    )
    if role_profile is None:
        raise Http404
    form_class = TutorProfileEditForm if request.user.role == Role.TUTOR else TuteeProfileEditForm
    form = form_class(request.POST, profile=role_profile, user=request.user)
    if form.is_valid():
        changed_fields = form.save()
        if changed_fields:
            log_event(
                request,
                "PROFILE_UPDATED",
                "更新個人資料 / Profile updated",
                request.user,
                {"fields": changed_fields},
            )
            messages.success(request, "個人資料已更新。 / Your profile has been updated.")
        else:
            messages.success(request, "沒有欄位變更。 / No changes were made.")
    else:
        for errors in form.errors.values():
            for error in errors:
                messages.error(request, error)
    return redirect(reverse("accounts:profile") + "#edit-profile")


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
    }
    context.update(_role_profile_context(counterpart))
    return render(request, "accounts/matched_profile.html", context)


@login_required
def handbook(request):
    roster = request.user.roster_entry
    return render(
        request,
        "accounts/handbook.html",
        {
            "roster": roster,
            "is_maryland": bool(roster and roster.program_id and roster.program.allow_tutee_initiate_invitation),
        },
    )


@role_required(Role.TUTOR, Role.TUTEE)
def class_documents(request):
    documents = visible_class_documents(request.user)
    return render(request, "accounts/class_documents.html", {"documents": documents})


@role_required(Role.TUTOR, Role.TUTEE)
def download_class_document(request, pk):
    document = get_object_or_404(ClassDocument, pk=pk, is_active=True)
    if document.program not in visible_class_document_programs(request.user):
        raise Http404
    AuditLog.record(
        actor=request.user, target_user=request.user, event_type="CLASS_DOCUMENT_DOWNLOADED",
        description="下載上課文件 / Class document downloaded",
        metadata={"document_id": document.pk, "program": document.program.code, "title_zh": document.title_zh},
    )
    return FileResponse(document.file.open("rb"), as_attachment=True, filename=document.filename)


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
        log_event(request, "QUALIFICATION_UPLOADED", "提交口語能力證明 / Oral proficiency document submitted", request.user)
        messages.success(request, "口語能力證明已送出審核。 / Your oral proficiency document was submitted for review.")
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
        "口語能力證明完成審核 / Oral proficiency document reviewed",
        document.tutor,
        {"result": document.status},
    )
    messages.success(request, "審核結果已儲存。 / Review result saved.")
    return redirect("accounts:dashboard")


@role_required(Role.ADMIN)
@require_POST
def roster_import(request):
    form = RosterImportForm(request.POST, request.FILES)
    redirect_target = reverse("accounts:dashboard") + "#roster-import"
    if not form.is_valid():
        for errors in form.errors.values():
            for error in errors:
                messages.error(request, error)
        return redirect(redirect_target)

    uploaded_file = form.cleaned_data["file"]
    try:
        result = import_roster_entries(uploaded_file)
    except RosterImportFileError as exc:
        messages.error(request, str(exc))
        return redirect(redirect_target)

    if result.errors:
        messages.error(
            request,
            f"匯入失敗，共 {len(result.errors)} 列有誤，未寫入任何資料。 / "
            f"Import failed: {len(result.errors)} row(s) invalid, nothing was saved.",
        )
        for error in result.errors[:50]:
            messages.error(request, error)
    else:
        log_event(
            request,
            "ROSTER_IMPORTED",
            f"批次匯入名冊 {result.created_count} 筆 / Batch imported {result.created_count} roster entries",
            metadata={
                "created_count": result.created_count,
                "student_ids": result.created_ids,
                "skipped_existing_count": len(result.skipped_existing_ids),
                "filename": uploaded_file.name,
            },
        )
        success_text = f"已新增 {result.created_count} 筆名冊資料。 / Added {result.created_count} roster entries."
        if result.skipped_existing_ids:
            success_text += (
                f" 略過 {len(result.skipped_existing_ids)} 筆已存在的學號（保留系統原有資料）。 / "
                f"Skipped {len(result.skipped_existing_ids)} student ID(s) already on the roster (kept as-is)."
            )
        messages.success(request, success_text)
    return redirect(redirect_target)


@role_required(Role.ADMIN)
@require_POST
def roster_import_quick(request, category_code):
    redirect_target = reverse("accounts:dashboard") + "#roster-import"
    if category_code == "TUTOR":
        role, program = Role.TUTOR, None
        category_label = "華語系學生 / CSL students"
    elif category_code.startswith("TUTOR:"):
        program = get_object_or_404(PartnerProgram, code=category_code[len("TUTOR:"):], is_active=True)
        role, category_label = Role.TUTOR, f"{program.name_zh}修課 Tutor / {program.name_en} tutor roster"
    else:
        program = get_object_or_404(PartnerProgram, code=category_code, is_active=True)
        role, category_label = Role.TUTEE, program.name_zh

    form = RosterImportForm(request.POST, request.FILES)
    if not form.is_valid():
        for errors in form.errors.values():
            for error in errors:
                messages.error(request, error)
        return redirect(redirect_target)

    uploaded_file = form.cleaned_data["file"]
    try:
        result = import_roster_ids(uploaded_file, role=role, program=program)
    except RosterImportFileError as exc:
        messages.error(request, str(exc))
        return redirect(redirect_target)

    if result.errors:
        messages.error(request, "、".join(result.errors[:20]))
        return redirect(redirect_target)

    log_event(
        request,
        "ROSTER_IMPORTED",
        f"快速匯入名冊（{category_label}）{result.created_count} 筆 / "
        f"Quick roster import ({category_label}): {result.created_count} entries",
        metadata={
            "category": category_code,
            "created_count": result.created_count,
            "student_ids": result.created_ids,
            "skipped_existing_count": len(result.skipped_existing_ids),
            "skipped_invalid_count": len(result.skipped_invalid),
            "filename": uploaded_file.name,
        },
    )
    success_text = f"「{category_label}」已新增 {result.created_count} 筆學號。 / Added {result.created_count} student ID(s) to {category_label}."
    if result.skipped_existing_ids:
        success_text += f" 略過 {len(result.skipped_existing_ids)} 筆已存在的學號。 / Skipped {len(result.skipped_existing_ids)} existing ID(s)."
    messages.success(request, success_text)
    for warning in result.skipped_invalid[:20]:
        messages.warning(request, warning)
    return redirect(redirect_target)


@role_required(Role.ADMIN)
@require_GET
def download_roster_template(request, file_format):
    if file_format == "csv":
        content = roster_template_csv_bytes()
        response = HttpResponse(content, content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="roster_import_template.csv"'
        return response
    if file_format == "xlsx":
        content = roster_template_xlsx_bytes()
        response = HttpResponse(
            content, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        response["Content-Disposition"] = 'attachment; filename="roster_import_template.xlsx"'
        return response
    raise Http404


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
