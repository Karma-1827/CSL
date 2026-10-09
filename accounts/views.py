from datetime import datetime, timedelta
from decimal import Decimal
import hashlib
import random

from django.contrib import messages
from django.conf import settings
from django.contrib.auth import login, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.views import LoginView
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.core.validators import URLValidator
from django.db import transaction
from django.db.models import Q
from django.http import FileResponse, Http404, HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from tutoring.models import (
    InvitationStatus,
    MatchingExclusion,
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
    ClassReview,
    ClassReviewDecision,
    ClassReviewStatus,
    HourAdjustment,
    IncidentReport,
    IncidentReportStatus,
    validate_class_document_file,
)
from tutoring.forms import (
    AdminMatchingExclusionForm,
    AdminPairingForm,
    ClassDocumentUploadForm,
    HoursDownloadForm,
    ScheduleClassForm,
    SemesterCreateForm,
    SemesterSettingsForm,
    StandaloneIncidentReportForm,
)
from tutoring.reporting import user_has_hour_records
from tutoring.services import (
    DAY_LABELS,
    LEARNING_DURATION_LABELS,
    LEVEL_LABELS,
    MATCHING_EARLY_OPEN_DAYS,
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
    export_users_for_program,
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
    AdminProfileEditForm,
    AnnouncementForm,
    BilingualAuthenticationForm,
    BilingualSetPasswordForm,
    OralExamAnnouncementForm,
    OralExamPassListImportForm,
    OralExamRegistrationForm,
    QualificationUploadForm,
    client_ip,
    RecoveryLookupForm,
    RecoveryVerificationForm,
    RegistrationLookupForm,
    RosterImportForm,
    TuteeProfileEditForm,
    TuteeRegistrationForm,
    TutorProfileEditForm,
    TutorRegistrationForm,
)
from .models import (
    Announcement,
    AnnouncementReadState,
    AuditLog,
    DashboardReadState,
    DashboardSection,
    DepartmentOralExamPass,
    OralExamAnnouncement,
    OralExamRegistration,
    ORAL_EXAM_MAX_REGISTRATIONS,
    OralExamRegistrationReviewStatus,
    PartnerProgram,
    RegistrationDraft,
    Role,
    RosterEntry,
    SecurityQuestionAnswer,
    User,
)
from .services import (
    OralExamPassListImportError,
    RosterImportFileError,
    count_online_users,
    import_department_oral_exam_pass_list,
    import_roster_entries,
    import_roster_ids,
    roster_template_csv_bytes,
    roster_template_xlsx_bytes,
    schedule_oral_exam_registrations,
)
from .throttle import any_throttled, clear_throttles, register_failures


def csrf_failure(request, reason=""):
    """Keep CSRF protection fail-closed while giving stale tabs a useful recovery path.

    The low-level failure reason is intentionally not rendered because it is only useful
    in server logs and can expose implementation details to an unauthenticated visitor.
    """
    return render(request, "accounts/csrf_failure.html", status=403)


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
    form = RegistrationLookupForm(request.POST or None, request=request)
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


# 2026-09-10 (fixing a real finding from the 師大資訊中心 HCL AppScan report,
# 2026-09-08): the candidate-browsing filter params below used to go straight from
# request.GET into a Django ORM .filter(field=value) call. A NUL byte in the value
# (e.g. ?tutee_level=%00) reaches psycopg as a string literal containing 0x00, which
# PostgreSQL's wire protocol cannot represent — psycopg raises before the query ever
# runs, and that exception was unhandled, producing a 500. Whitelisting known choice
# values closes this off entirely for the fixed-choice filters (gender, overall
# level, skills, days, time slots); native_language has no fixed backend choice
# list (see CLAUDE.md 4.3), so it's sanitized by rejecting control characters and
# capping length instead of a whitelist.
def _sanitize_choice_value(value, valid_values):
    return value if value in valid_values else ""


def _sanitize_choice_list(values, valid_values):
    return [value for value in values if value in valid_values]


def _sanitize_free_text_filter(value, max_length=80):
    if not value or any(ord(character) < 32 for character in value):
        return ""
    return value[:max_length]


@login_required
def dashboard(request):
    synchronize_matching_state()
    # 2026-09-16(使用者轉達助教需求):「學期設定前一週可以先瀏覽tutee名單以及配對，但
    # 還不能安排課程」——配對(瀏覽候選人、邀請、成立配對)提前 MATCHING_EARLY_OPEN_DAYS
    # 天開放,排課本身不受影響(schedule_classes() 另外直接檢查 pairing.semester 的
    # 起訖日,不經過這裡的 current_semester)。
    current_semester = active_semester(program=user_program(request.user), early_days=MATCHING_EARLY_OPEN_DAYS)
    today = timezone.localdate()
    matching_open = bool(
        current_semester
        and today >= current_semester.starts_on - timedelta(days=MATCHING_EARLY_OPEN_DAYS)
        and today <= current_semester.ends_on
    )
    read_state = AnnouncementReadState.objects.filter(user=request.user).first()
    last_viewed_announcements_at = read_state.last_viewed_at if read_state else None
    active_announcements = list(Announcement.objects.filter(is_active=True))
    for announcement in active_announcements:
        announcement.is_new = (
            last_viewed_announcements_at is None or announcement.created_at > last_viewed_announcements_at
        )
    # 2026-10-03(使用者要求):口語能力證明審核結果、課程審核結果、課堂通報/異常回報
    # 被標記已紀錄之後,Tutor/Tutee 的側邊欄原本完全不會冒出任何提示——比照公告欄既有的
    # 「記錄上次查看時間、比對這段期間有沒有新變動」做法,但一個使用者要分別追蹤三個
    # 分類,所以用 DashboardReadState(section 區分)而不是沿用 AnnouncementReadState
    # 那種「每人一筆」的寫法。只對 Tutor/Tutee 計算,Admin 不需要這幾個提示。
    qualification_unread_count = 0
    hours_unread_count = 0
    incident_reports_unread_count = 0
    if request.user.role in (Role.TUTOR, Role.TUTEE):
        dashboard_last_viewed = {
            row.section: row.last_viewed_at
            for row in DashboardReadState.objects.filter(user=request.user)
        }
        hours_last_viewed = dashboard_last_viewed.get(DashboardSection.HOURS)
        decision_qs = ClassReviewDecision.objects.filter(
            Q(review__session__pairing__tutor=request.user) | Q(review__session__pairing__tutee=request.user)
        )
        alert_qs = ClassAlert.objects.filter(reporter=request.user, status=ClassAlertStatus.RESOLVED)
        if hours_last_viewed:
            decision_qs = decision_qs.filter(created_at__gt=hours_last_viewed)
            alert_qs = alert_qs.filter(resolved_at__gt=hours_last_viewed)
        hours_unread_count = decision_qs.count() + alert_qs.count()

        incident_last_viewed = dashboard_last_viewed.get(DashboardSection.INCIDENT_REPORTS)
        incident_qs = IncidentReport.objects.filter(reporter=request.user, status=IncidentReportStatus.RESOLVED)
        if incident_last_viewed:
            incident_qs = incident_qs.filter(resolved_at__gt=incident_last_viewed)
        incident_reports_unread_count = incident_qs.count()

        if request.user.role == Role.TUTOR:
            qualification_last_viewed = dashboard_last_viewed.get(DashboardSection.QUALIFICATION)
            qualification = QualificationDocument.objects.filter(tutor=request.user).first()
            if qualification and qualification.reviewed_at and (
                qualification_last_viewed is None or qualification.reviewed_at > qualification_last_viewed
            ):
                qualification_unread_count = 1
    context = {
        "current_semester": current_semester,
        "matching_open": matching_open,
        "active_announcements": active_announcements,
        "unread_announcement_count": sum(1 for item in active_announcements if item.is_new),
        "qualification_unread_count": qualification_unread_count,
        "hours_unread_count": hours_unread_count,
        "incident_reports_unread_count": incident_reports_unread_count,
    }
    if request.user.role == Role.ADMIN:
        semester_rows = list(Semester.objects.order_by("-starts_on"))
        for row in semester_rows:
            row.edit_form = SemesterSettingsForm(instance=row, prefix=f"semester-{row.pk}")
        class_document_programs = list(PartnerProgram.objects.filter(class_documents_enabled=True).order_by("name_zh"))
        class_document_rows = list(
            ClassDocument.objects.select_related("program", "semester", "uploaded_by").order_by("-uploaded_at")
        )
        for row in class_document_rows:
            row.edit_form = ClassDocumentUploadForm(instance=row, prefix=f"document-{row.pk}")
        announcement_rows = list(Announcement.objects.order_by("display_order", "-created_at"))
        for row in announcement_rows:
            row.edit_form = AnnouncementForm(instance=row, prefix=f"announcement-{row.pk}")
        oral_exam_announcement = OralExamAnnouncement.objects.first()
        oral_exam_form = OralExamAnnouncementForm(instance=oral_exam_announcement)
        oral_exam_registrations = (
            list(OralExamRegistration.objects.filter(exam_date=oral_exam_announcement.exam_date).select_related("tutor"))
            if oral_exam_announcement else []
        )
        # 2026-10-07(使用者要求新增「考試名單」卡片):只取已經成功排入考試順序的
        # (`exam_order` 非空),依考試時間排序;未排入的不在這份名單裡顯示(前一個
        # view 已經用 flash message 提示衝突人數)。**同時要求 `review_status=
        # CONFIRMED`**:撤回登記本來就會順手清空 `exam_time`/`exam_order`(見
        # `revert_oral_exam_registration()`),但這裡還是多一道防呆——萬一有舊資料
        # 在欄位改版(`review_status` 取代 `confirmed_at`)過程中殘留不一致的
        # `exam_order`,不會因此誤把「其實已經不是已登記狀態」的人留在考試名單裡。
        oral_exam_scheduled_registrations = (
            list(
                OralExamRegistration.objects.filter(
                    exam_date=oral_exam_announcement.exam_date, exam_order__isnull=False,
                    review_status=OralExamRegistrationReviewStatus.CONFIRMED,
                ).select_related("tutor").order_by("exam_order")
            )
            if oral_exam_announcement else []
        )
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
            ).prefetch_related("attendances", "class_records", "confirmations", "class_alerts", "class_review")
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
            review = getattr(session, "class_review", None)
            if review and review.status in {ClassReviewStatus.WAITING, ClassReviewStatus.PENDING, ClassReviewStatus.REJECTED, ClassReviewStatus.REVISE}:
                reasons.append(f"課程審核：{review.get_status_display()}")
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
        export_programs = list(PartnerProgram.objects.order_by("-is_active", "name_zh"))
        export_user_rows = []
        export_program_ids_by_user = {}
        for program in export_programs:
            for user_id in export_users_for_program(program).values_list("pk", flat=True):
                export_program_ids_by_user.setdefault(user_id, []).append(str(program.pk))
        for user in User.objects.exclude(role=Role.ADMIN).select_related(
            "roster_entry", "roster_entry__program"
        ).order_by("username"):
            export_user_rows.append(
                {"user": user, "program_ids": " ".join(export_program_ids_by_user.get(user.pk, []))}
            )

        # 2026-09-10 (user-requested): non-superuser Admin accounts (is_staff=False) can't
        # reach /system-admin/, so the "名冊人數"/"已註冊"/"老師"/"學生" overview cards and
        # the sidebar "學生名冊" link — which all used to point straight at Django Admin's
        # RosterEntry/User changelists — were a dead end for them. This read-only roster
        # browse tab mirrors RosterEntryAdmin's search/filter/list capability (not its
        # add/edit/delete) so every Admin, regardless of is_staff, can look someone up.
        roster_q = request.GET.get("roster_q", "").strip()
        roster_role = request.GET.get("roster_role", "")
        roster_program = request.GET.get("roster_program", "")
        roster_claimed = request.GET.get("roster_claimed", "")
        roster_rows = RosterEntry.objects.select_related("program", "user").order_by("student_id")
        if roster_q:
            roster_rows = roster_rows.filter(
                Q(student_id__icontains=roster_q) | Q(name_zh__icontains=roster_q) | Q(name_en__icontains=roster_q)
            )
        if roster_role in {Role.TUTOR, Role.TUTEE}:
            roster_rows = roster_rows.filter(role=roster_role)
        if roster_program:
            roster_rows = roster_rows.filter(program_id=roster_program)
        if roster_claimed == "yes":
            roster_rows = roster_rows.filter(claimed_at__isnull=False)
        elif roster_claimed == "no":
            roster_rows = roster_rows.filter(claimed_at__isnull=True)
        roster_page = Paginator(roster_rows, 30).get_page(request.GET.get("roster_page"))

        # 2026-09-16(使用者發現真實案例後要求):「近期配對」原本寫死只取最新 8 筆、無搜尋
        # 無分頁,配對數量一多,較早建立但仍在輔導中的配對就會被擠出這份清單,讓 Admin 誤以
        # 為配對不見了(實際上資料庫裡好好的)。比照上面 roster 分頁的既有做法補上搜尋＋分頁。
        pairing_q = request.GET.get("pairing_q", "").strip()
        pairing_status = request.GET.get("pairing_status", "")
        pairing_rows = Pairing.objects.select_related("semester", "tutor", "tutee")
        if pairing_q:
            pairing_rows = pairing_rows.filter(
                Q(tutor__username__icontains=pairing_q)
                | Q(tutor__name_zh__icontains=pairing_q)
                | Q(tutor__name_en__icontains=pairing_q)
                | Q(tutee__username__icontains=pairing_q)
                | Q(tutee__name_zh__icontains=pairing_q)
                | Q(tutee__name_en__icontains=pairing_q)
            )
        if pairing_status in {PairingStatus.ACTIVE, PairingStatus.ENDED}:
            pairing_rows = pairing_rows.filter(status=pairing_status)
        pairing_page = Paginator(pairing_rows, 20).get_page(request.GET.get("pairing_page"))

        # 2026-09-11(使用者要求):在待審核列表上附加系辦資格比對名單的提示。純粹是
        # 顯示用的提示,不影響審核結果或任何欄位,Admin 仍要自行按核准/拒絕。
        # 2026-09-24(使用者要求):`list_type` 決定提示文字——NTNU 是「語音通過」,
        # 馬里蘭是「修課名單」,兩者語意不同,不能共用同一句提示。
        pending_qualifications = list(
            QualificationDocument.objects.filter(status=QualificationStatus.PENDING).select_related("tutor")[:8]
        )
        eligibility_list_type_by_student_id = dict(
            DepartmentOralExamPass.objects.filter(
                student_id__in=[document.tutor.username for document in pending_qualifications]
            ).values_list("student_id", "list_type")
        )
        for document in pending_qualifications:
            document.oral_exam_pass_hint_type = eligibility_list_type_by_student_id.get(document.tutor.username)

        # 2026-09-11(使用者要求):Admin 沒有唯一所屬計畫,`user_program(admin)` 一律回傳
        # None,導致最上方共用的「目前學期」小方塊(page-heading 的 .semester-chip,
        # Tutor/Tutee 本來就有的同一個既有 UI 元件)查不到值,顯示「尚未設定」。這裡直接
        # 覆寫成所有合作計畫裡最先開始的一筆啟用中學期,讓 Admin 也能用同一個既有元件看到
        # 目前學期,不需要另外新增一個獨立的顯示區塊。2026-09-16:比照 Tutor/Tutee 的
        # `current_semester` 一併套用 MATCHING_EARLY_OPEN_DAYS 提前開窗,避免配對已經
        # 提前開放時,Admin 自己的畫面卻還顯示「尚未設定」這種不一致的情況。
        current_admin_semester = (
            Semester.objects.filter(
                is_active=True,
                starts_on__lte=today + timedelta(days=MATCHING_EARLY_OPEN_DAYS),
                ends_on__gte=today,
            )
            .order_by("starts_on")
            .first()
        )

        context.update(
            {
                "current_semester": current_admin_semester,
                "roster_total": RosterEntry.objects.count(),
                "registered_total": User.objects.exclude(role=Role.ADMIN).count(),
                "tutor_total": User.objects.filter(role=Role.TUTOR).count(),
                "tutee_total": User.objects.filter(role=Role.TUTEE).count(),
                "online_user_count": count_online_users(),
                "total_login_count": AuditLog.objects.filter(event_type="LOGIN_SUCCESS").count(),
                "pending_qualifications": pending_qualifications,
                "oral_exam_pass_import_form": OralExamPassListImportForm(),
                "qualification_review_history": QualificationDocument.objects.exclude(
                    status=QualificationStatus.PENDING
                ).select_related("tutor", "reviewed_by").order_by("-reviewed_at")[:30],
                "recent_logs": AuditLog.objects.select_related("actor", "target_user")[:8],
                "active_pairing_total": Pairing.objects.filter(status=PairingStatus.ACTIVE).count(),
                "pending_invitation_total": MatchingInvitation.objects.filter(status=InvitationStatus.PENDING).count(),
                "pending_invitations": MatchingInvitation.objects.filter(status=InvitationStatus.PENDING).select_related(
                    "semester", "tutor", "tutee", "initiated_by"
                )[:20],
                "pairing_q": pairing_q,
                "pairing_status": pairing_status,
                "pairing_page": pairing_page,
                "admin_pairing_form": AdminPairingForm(),
                "matching_exclusion_form": AdminMatchingExclusionForm(),
                "active_matching_exclusions": MatchingExclusion.objects.filter(is_active=True).select_related(
                    "semester", "tutor", "tutee", "created_by"
                )[:100],
                "matching_exclusion_history": MatchingExclusion.objects.filter(is_active=False).select_related(
                    "semester", "tutor", "tutee", "created_by", "revoked_by"
                )[:50],
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
                "export_programs": export_programs,
                "export_user_rows": export_user_rows,
                "export_semesters": overview_semesters,
                "roster_import_form": RosterImportForm(),
                "quick_import_programs": PartnerProgram.objects.filter(is_active=True).order_by("name_zh"),
                "class_document_programs": class_document_programs,
                "class_document_rows": class_document_rows,
                "new_class_document_form": ClassDocumentUploadForm(),
                "announcement_rows": announcement_rows,
                "new_announcement_form": AnnouncementForm(),
                "oral_exam_announcement": oral_exam_announcement,
                "oral_exam_form": oral_exam_form,
                "oral_exam_registrations": oral_exam_registrations,
                "oral_exam_scheduled_registrations": oral_exam_scheduled_registrations,
                "roster_q": roster_q,
                "roster_role": roster_role,
                "roster_program": roster_program,
                "roster_claimed": roster_claimed,
                "roster_page": roster_page,
                "roster_programs": PartnerProgram.objects.order_by("name_zh"),
            }
        )
    elif request.user.role == Role.TUTOR:
        tutee_matching_program = user_program(request.user)
        qualification = QualificationDocument.objects.filter(tutor=request.user).first()
        # 2026-09-16(使用者實際回報:登入 NTNU-OIA-TUTOR 卻看不到已成立的配對):原本要求
        # `semester=current_semester`(當下日期須落在學期起訖區間內)才顯示,導致 Admin 把
        # 學期 starts_on 改成未來日期(例如新學期正式開課日)時,已經成立的配對會從本人
        # dashboard 消失,即使配對本身狀態仍是 ACTIVE。使用者確認:已配對的要能先看到,只有
        # 排課本身要等學期開始(那條規則獨立寫在 schedule_classes() 檢查 pairing.semester
        # 的起訖日,不受這裡影響)。因此這裡不再要求配對的學期等於「當下正在進行」的學期,
        # 只要 Pairing.status 仍是 ACTIVE 就視為目前配對。
        pairings = Pairing.objects.filter(
            tutor=request.user, status=PairingStatus.ACTIVE
        ).select_related("tutee")
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
        invitation_history = [
            {
                "status_display": invitation.get_status_display(),
                "status": invitation.status,
                "responded_at": invitation.responded_at,
                "profile": anonymous_tutee_profile(invitation.tutee.tutee_profile),
            }
            for invitation in MatchingInvitation.objects.filter(tutor=request.user)
            .exclude(status=InvitationStatus.PENDING)
            .select_related("tutee__tutee_profile")
            .order_by("-responded_at", "-created_at")[:20]
        ]
        can_match = matching_open and tutor_has_approved_qualification(request.user) and pairings.count() < MAX_ACTIVE_TUTEES_PER_TUTOR
        gender_values = {choice[0] for choice in GENDER_CHOICES if choice[0]}
        overall_level_values = {choice[0] for choice in OVERALL_LEVEL_CHOICES}
        skill_values = {choice[0] for choice in SKILL_CHOICES}
        day_values = {choice[0] for choice in DAYS}
        time_slot_values = {choice[0] for choice in TIME_SLOTS}
        candidate_filters = {
            "gender": _sanitize_choice_value(request.GET.get("tutee_gender", "").strip(), gender_values),
            "overall_level": _sanitize_choice_value(
                request.GET.get("tutee_level", "").strip(), overall_level_values
            ),
            "native_language": _sanitize_free_text_filter(request.GET.get("tutee_language", "").strip()),
            "target_skills": _sanitize_choice_list(request.GET.getlist("tutee_skill"), skill_values),
            "days": _sanitize_choice_list(request.GET.getlist("tutee_day"), day_values),
            "time_slots": _sanitize_choice_list(request.GET.getlist("tutee_slot"), time_slot_values),
        }
        candidates = (
            anonymous_tutee_candidates(semester=current_semester, tutor=request.user, filters=candidate_filters)
            if can_match else []
        )
        pending_tutee_ids = {row["profile"]["user_id"] for row in sent_rows + received_rows}
        for candidate in candidates:
            candidate["pending"] = candidate["user_id"] in pending_tutee_ids
        # 2026-10-03(使用者要求「我的首頁」新增審核進度卡片「如果通過的就不用顯示了」):
        # 只有「還不是通過」才顯示這一行,通過之後整行從卡片上消失,不是顯示「已通過」。
        qualification_progress_status = None
        if qualification is None:
            qualification_progress_status = {"label": "尚未上傳", "label_en": "Not yet uploaded"}
        elif qualification.status == QualificationStatus.PENDING:
            qualification_progress_status = {"label": "審核中", "label_en": "Under review"}
        elif qualification.status == QualificationStatus.REJECTED:
            qualification_progress_status = {"label": "未通過", "label_en": "Not approved"}
        context.update(
            {
                "qualification": qualification,
                "qualification_progress_status": qualification_progress_status,
                "qualification_form": QualificationUploadForm(),
                "active_pairings": pairings,
                "active_pairing_count": pairings.count(),
                "can_match": can_match,
                "tutee_candidates": candidates,
                "tutee_matching_program": tutee_matching_program,
                "tutee_candidate_filters": candidate_filters,
                "tutee_gender_choices": [choice for choice in GENDER_CHOICES if choice[0]],
                "tutee_level_choices": OVERALL_LEVEL_CHOICES,
                "tutee_skill_choices": SKILL_CHOICES,
                "tutee_day_choices": DAYS,
                "tutee_slot_choices": TIME_SLOTS,
                "sent_invitations": sent_rows,
                "received_invitations": received_rows,
                "invitation_history": invitation_history,
                "pairing_release_reason_choices": PairingReleaseReason.choices,
            }
        )
    else:
        # 2026-09-16(使用者要求,同一次修正的 Tutee 對應分支):見上方 TUTOR 分支的說明。
        pairings = Pairing.objects.filter(
            tutee=request.user, status=PairingStatus.ACTIVE
        ).select_related("tutor")
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
        invitation_history = [
            {
                "status_display": invitation.get_status_display(),
                "status": invitation.status,
                "responded_at": invitation.responded_at,
                "profile": anonymous_tutor_profile(invitation.tutor.tutor_profile),
            }
            for invitation in MatchingInvitation.objects.filter(tutee=request.user)
            .exclude(status=InvitationStatus.PENDING)
            .select_related("tutor__tutor_profile")
            .order_by("-responded_at", "-created_at")[:20]
        ]
        can_initiate_invitation = bool(
            request.user.roster_entry
            and request.user.roster_entry.program_id
            and request.user.roster_entry.program.allow_tutee_initiate_invitation
        )
        tutor_gender_values = {choice[0] for choice in GENDER_CHOICES if choice[0]}
        tutor_day_values = {choice[0] for choice in DAYS}
        tutor_time_slot_values = {choice[0] for choice in TIME_SLOTS}
        tutor_candidate_filters = {
            "gender": _sanitize_choice_value(request.GET.get("tutor_gender", "").strip(), tutor_gender_values),
            "native_language": _sanitize_free_text_filter(request.GET.get("tutor_language", "").strip()),
            "days": _sanitize_choice_list(request.GET.getlist("tutor_day"), tutor_day_values),
            "time_slots": _sanitize_choice_list(request.GET.getlist("tutor_slot"), tutor_time_slot_values),
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
                "invitation_history": invitation_history,
                "pairing_release_reason_choices": PairingReleaseReason.choices,
            }
        )
    if request.user.role in {Role.TUTOR, Role.TUTEE}:
        # 2026-10-06(使用者要求「師大外籍生計畫tutor左側欄位新增線上口語考試」):只有
        # 師大外籍生(NTNU)計畫的 Tutor 才看得到這個分頁。一般 Tutor(`roster_entry.program`
        # 為空)在 `user_program()` 既有慣例裡就是回傳 NTNU 這個 PartnerProgram 物件
        # (見第 4.2 節),所以跟「可配對範圍」用同一個函式判斷,不另外寫規則;非 NTNU 的
        # Tutor(例如馬里蘭)與所有 Tutee 皆看不到側邊欄連結,也不會拿到任何公告內容。
        tutor_program = user_program(request.user) if request.user.role == Role.TUTOR else None
        is_ntnu_tutor = bool(tutor_program and tutor_program.code == "NTNU")
        oral_exam_announcement = (
            OralExamAnnouncement.objects.filter(is_published=True).first() if is_ntnu_tutor else None
        )
        # 2026-10-06(使用者要求「開放報名，tutor就可以點擊報名...就可以送出」):
        # 用 announcement.exam_date 這個快照值比對,不是直接拿 announcement 的 FK——
        # 原因見 OralExamRegistration 的模型說明(避免 Admin 之後覆寫同一筆設定造成
        # 舊報名紀錄被誤判成屬於新的一輪)。
        my_oral_exam_registration = (
            OralExamRegistration.objects.filter(
                tutor=request.user, exam_date=oral_exam_announcement.exam_date
            ).first()
            if oral_exam_announcement else None
        )
        oral_exam_registration_form = (
            OralExamRegistrationForm(instance=my_oral_exam_registration) if is_ntnu_tutor else None
        )
        # 2026-10-09(使用者要求「現在每次安排考試最多20人...顯示目前報名人數
        # （X/20）...已經滿了先停止報名」,接著澄清「他們都已經繳費了，所以我才說要
        # 從報名人數開始擋」):算的是「已送出報名」的總數(不分 PENDING/
        # NEEDS_REVISION/CONFIRMED),不是只算已登記(CONFIRMED)人數——報名時就已經
        # 要求繳費,送出就代表已經付過這筆名額的費用,所以上限要卡在「送出」這一步,
        # 不是等 Admin 核對完才卡。
        oral_exam_registered_count = (
            OralExamRegistration.objects.filter(exam_date=oral_exam_announcement.exam_date).count()
            if oral_exam_announcement else 0
        )
        oral_exam_registration_full = oral_exam_registered_count >= ORAL_EXAM_MAX_REGISTRATIONS
        participant_pairings = list(
            Pairing.objects.filter(
                Q(tutor=request.user) | Q(tutee=request.user)
            ).select_related("semester", "tutor", "tutee").order_by("-started_at")
        )
        conversation_pairings = annotate_conversation_summaries(participant_pairings, viewer=request.user)
        # 2026-09-10 (user-requested, after discussion with the department office): the
        # counterpart (whoever did not submit the release request) must be told both while
        # it's pending and once it's resolved — previously a resolved outcome was only
        # visible by noticing the pairing had quietly disappeared. Pending has nothing to
        # acknowledge (it just resolves on its own), so this only tracks unseen outcomes.
        release_notices = list(
            PairingReleaseRequest.objects.filter(
                Q(pairing__tutor=request.user) | Q(pairing__tutee=request.user)
            ).exclude(requested_by=request.user).filter(
                Q(status=PairingReleaseStatus.PENDING)
                | Q(
                    status__in=[
                        PairingReleaseStatus.APPROVED,
                        PairingReleaseStatus.AUTO_APPROVED,
                        PairingReleaseStatus.REJECTED,
                    ],
                    counterpart_acknowledged_at__isnull=True,
                )
            ).select_related("pairing__tutor", "pairing__tutee", "requested_by").order_by("-created_at")
        )
        # 2026-10-03(使用者要求「解除審核如果是人工審核,有留言也要顯示給tutor/tutee看,
        # 左側欄位多一個解除配對結果,顯示所有紀錄,不管人工或自動,以及管理員給的留言」):
        # release_notices 只是「未讀通知」,只給對方看、看過一次(按「我知道了」)就消失,
        # 不是完整歷史。這裡另外提供一份不會消失的完整清單,涵蓋這個人(不論是申請人或對方)
        # 涉及的每一筆解除配對申請,不分目前狀態。審核備註(`review_note`)只有人工審核
        # (APPROVED/REJECTED)才會有內容,AUTO_APPROVED 本來就是空字串,不需要額外判斷
        # 「是否為人工審核」才顯示——有內容就顯示。
        pairing_release_history_full = list(
            PairingReleaseRequest.objects.filter(
                Q(pairing__tutor=request.user) | Q(pairing__tutee=request.user)
            ).select_related("pairing__tutor", "pairing__tutee", "pairing__semester", "requested_by").order_by("-created_at")
        )
        for item in pairing_release_history_full:
            item.viewer_is_requester = item.requested_by_id == request.user.pk
            item.other_party = item.pairing.tutee if item.pairing.tutor_id == request.user.pk else item.pairing.tutor
        participant_filter = Q(pairing__tutor=request.user) if request.user.role == Role.TUTOR else Q(pairing__tutee=request.user)
        class_sessions = ClassSession.objects.filter(participant_filter).select_related(
            "pairing__semester", "pairing__tutor", "pairing__tutee"
        ).prefetch_related("attendances", "class_records", "confirmations", "class_alerts", "class_review")
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
        # 2026-10-03(使用者要求「我的首頁」目前配對/配對概況下方新增審核進度卡片,
        # 隨後再要求「可以點擊卡片然後顯示細節嗎」):只算「已經結束但還不是有效成立」的
        # 課程(未結束的課堂不列入,is_official 已經涵蓋簽到/紀錄未完成、等待雙方確認、
        # 等待管理員審核、待補正、未通過全部這幾種情況,一旦通過就不會再被算進來)。範圍是
        # 這個人所有配對(含已結束的配對),不只目前這組,因為剛結束配對前最後一堂課還沒
        # 走完流程時一樣需要被看見。重用上面已經算好的 all_rows/is_official,不用再查
        # 一次,並順便幫每一筆標上展開列表要顯示的狀態文字與對方姓名。
        pending_class_review_sessions = []
        for session in all_rows:
            if session.status == ClassSessionStatus.CANCELLED or session.ends_at >= now or session.is_official:
                continue
            if (
                session.my_record and session.my_attendance
                and hasattr(session, "class_review") and session.class_review.status != ClassReviewStatus.WAITING
            ):
                status_label = session.class_review.get_status_display()
            elif session.my_record and session.my_attendance:
                status_label = "等待雙方完成 / Waiting for mutual confirmation"
            elif session.my_attendance:
                status_label = "待填紀錄 / Record due"
            else:
                status_label = "待簽到 / Check-in due"
            session.progress_status_label = status_label
            session.progress_counterpart = (
                session.pairing.tutee if request.user.role == Role.TUTOR else session.pairing.tutor
            )
            pending_class_review_sessions.append(session)
        pending_class_review_sessions.sort(key=lambda item: (item.class_date, item.start_time), reverse=True)
        # 課堂通報(自己通報且還是 ACTIVE)直接重用 all_rows 已經 prefetch 好的
        # class_alerts,不用再查一次,點擊項目連去該堂課的詳情頁(通報本身就是在那裡
        # 顯示/處理);異常回報沒有對應的 session 可以重用,另外查一次,點擊項目連去
        # 「異常回報」這個既有分頁(data-dashboard-target,跟側邊欄連結同一套 SPA 切換
        # 機制,不需要額外寫 JS)。
        unresolved_report_items = []
        for session in all_rows:
            for alert in session.class_alerts.all():
                if alert.reporter_id == request.user.pk and alert.status == ClassAlertStatus.ACTIVE:
                    unresolved_report_items.append({
                        "date": session.class_date,
                        "label": f"課堂通報 · {alert.get_reason_display()}",
                        "url": reverse("tutoring:class_detail", args=[session.pk]),
                        "is_tab_link": False,
                    })
        for report in IncidentReport.objects.filter(reporter=request.user, status=IncidentReportStatus.PENDING):
            unresolved_report_items.append({
                "date": timezone.localtime(report.created_at).date(),
                "label": f"異常回報 · {report.get_category_display()}",
                "url": "#incident-reports",
                "is_tab_link": True,
            })
        unresolved_report_items.sort(key=lambda item: item["date"], reverse=True)
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
                "incident_report_form": StandaloneIncidentReportForm(),
                "own_incident_reports": IncidentReport.objects.filter(reporter=request.user).prefetch_related("replies").order_by("-created_at"),
                "release_notices": release_notices,
                "pairing_release_history_full": pairing_release_history_full,
                "pending_class_review_sessions": pending_class_review_sessions,
                "unresolved_report_items": unresolved_report_items,
                "is_ntnu_tutor": is_ntnu_tutor,
                "oral_exam_announcement": oral_exam_announcement,
                "my_oral_exam_registration": my_oral_exam_registration,
                "oral_exam_registration_form": oral_exam_registration_form,
                "oral_exam_registered_count": oral_exam_registered_count,
                "oral_exam_registration_full": oral_exam_registration_full,
                "oral_exam_max_registrations": ORAL_EXAM_MAX_REGISTRATIONS,
            }
        )
    elif request.user.role == Role.ADMIN:
        class_reviews = list(
            ClassReview.objects.select_related(
                "session__pairing__semester", "session__pairing__tutor", "session__pairing__tutee", "reviewed_by"
            ).prefetch_related("session__attendances", "session__class_records", "decisions").order_by("-created_at")
        )
        for review in class_reviews:
            # 2026-10-01(使用者要求「如果是通過/待補正也要接列出所有審核紀錄」):列表裡的
            # 「上一則留言」改從 ClassReviewDecision 歷史表取最新一筆,review_note 現在在
            # WAITING/PENDING 時會被清空,不能再直接拿它當顯示來源。
            decisions = list(review.decisions.all())
            review.latest_decision = decisions[0] if decisions else None
            has_makeup_attendance = any(row.is_makeup for row in review.session.attendances.all())
            has_makeup_record = any(row.is_makeup for row in review.session.class_records.all())
            if has_makeup_attendance and has_makeup_record:
                review.category_label = "補簽到＋補課堂紀錄"
                review.category_label_en = "Attendance + record"
            elif has_makeup_attendance:
                review.category_label = "補簽到"
                review.category_label_en = "Attendance"
            elif has_makeup_record:
                review.category_label = "補課堂紀錄"
                review.category_label_en = "Class record"
            else:
                review.category_label = "一般課程"
                review.category_label_en = "Regular class"
        status_definitions = (
            (ClassReviewStatus.PENDING, "等待管理員核准", "Waiting for admin approval", True),
            (ClassReviewStatus.WAITING, "等待雙方確認", "Waiting for mutual confirmation", False),
            (ClassReviewStatus.APPROVED, "通過", "Approved", False),
            (ClassReviewStatus.REJECTED, "未通過", "Rejected", False),
            (ClassReviewStatus.REVISE, "待補正", "Revise", False),
        )
        # 2026-10-02(使用者要求「比數會越來越多，每個區塊只7筆就換第二頁」):五個狀態
        # 區塊各自獨立分頁,比照 roster_page/pairing_page 既有慣例,用各自的查詢參數
        # (如 pending_page)而非共用一個,翻某一個區塊的頁不會影響其他區塊。預設只展開
        # PENDING,但如果使用者正在某個區塊翻頁(該區塊的頁碼參數出現在網址上),重新整理
        # 後那個區塊要維持展開,不能讓 <details> 收合回去、翻頁翻到一半又看不到結果。
        class_review_sections = []
        for status, label, label_en, is_open in status_definitions:
            page_param = f"{status.lower()}_page"
            rows = [review for review in class_reviews if review.status == status]
            class_review_sections.append({
                "status": status,
                "label": label,
                "label_en": label_en,
                "open": is_open or page_param in request.GET,
                "page_param": page_param,
                "page": Paginator(rows, 7).get_page(request.GET.get(page_param)),
            })
        context["class_review_sections"] = class_review_sections
        context["pending_class_reviews"] = [
            review for review in class_reviews if review.status == ClassReviewStatus.PENDING
        ]
        context["active_class_alerts"] = ClassAlert.objects.filter(
            status=ClassAlertStatus.ACTIVE
        ).select_related("session__pairing__semester", "reporter", "subject")
        context["class_alert_history"] = ClassAlert.objects.filter(
            status=ClassAlertStatus.RESOLVED
        ).select_related("session__pairing__semester", "reporter", "resolved_by")[:30]
        context["pending_incident_reports"] = IncidentReport.objects.filter(
            status=IncidentReportStatus.PENDING
        ).select_related("reporter").prefetch_related("replies")
        context["incident_report_history"] = IncidentReport.objects.filter(
            status=IncidentReportStatus.RESOLVED
        ).select_related("reporter", "resolved_by").prefetch_related("replies")[:30]
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
            .prefetch_related("attendances", "class_records", "confirmations", "class_alerts", "class_review")
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
        review = getattr(session, "class_review", None)
        if review and review.status in {ClassReviewStatus.WAITING, ClassReviewStatus.PENDING, ClassReviewStatus.REJECTED, ClassReviewStatus.REVISE}:
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
    # 2026-09-11(使用者要求):IncidentReport 不再綁定課程/配對,無法再依「是否為該堂課的
    # 參與者」反查;改成只看這位使用者自己送出過的回報。
    context["incident_reports"] = IncidentReport.objects.filter(
        reporter=subject
    ).select_related("resolved_by").order_by("-created_at")[:20]

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


def _profile_context(user):
    context = {"roster": user.roster_entry, "edit_form": None}
    context.update(_role_profile_context(user))
    if user.role == Role.TUTOR:
        context["qualification"] = QualificationDocument.objects.filter(tutor=user).first()
    return context


@login_required
def profile(request):
    """Present the signed-in user's full profile outside the matching workflow."""
    context = _profile_context(request.user)
    role_profile = context["role_profile"]
    if request.user.role == Role.TUTOR and role_profile:
        context["edit_form"] = TutorProfileEditForm(profile=role_profile, user=request.user)
    elif request.user.role == Role.TUTEE and role_profile:
        context["edit_form"] = TuteeProfileEditForm(profile=role_profile, user=request.user)
    elif request.user.role == Role.ADMIN:
        context["edit_form"] = AdminProfileEditForm(user=request.user)
    return render(request, "accounts/profile.html", context)


@login_required
@require_POST
def update_profile(request):
    """On success, redirect back (avoids a resubmission on refresh). On validation
    failure, render the profile page directly with the bound, invalid form instead of
    redirecting — components/form_field.html already renders each field's own errors
    right below it, so this is what actually gets a password error to show up under the
    password field rather than as a single flattened message a user has to go hunting
    for (found 2026-09-10 from real usage: messages.html wasn't even included on this
    page at first, and once it was, a top-of-page/generic message was still easy to miss)."""
    if request.user.role == Role.ADMIN:
        form = AdminProfileEditForm(request.POST, user=request.user)
        if form.is_valid():
            changed_fields, password_changed = form.save()
            if password_changed:
                update_session_auth_hash(request, request.user)
            if changed_fields or password_changed:
                log_event(
                    request,
                    "PROFILE_UPDATED",
                    "更新個人資料 / Profile updated",
                    request.user,
                    {"fields": changed_fields, "password_changed": password_changed},
                )
                messages.success(request, "個人資料已更新。 / Your profile has been updated.")
            else:
                messages.success(request, "沒有欄位變更。 / No changes were made.")
            return redirect(reverse("accounts:profile") + "#edit-profile")
        context = _profile_context(request.user)
        context["edit_form"] = form
        return render(request, "accounts/profile.html", context)

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
        return redirect(reverse("accounts:profile") + "#edit-profile")
    context = _profile_context(request.user)
    context["edit_form"] = form
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


def _private_file_response(file_field, filename, *, inline=False):
    """Shared response shaping for private, permission-gated file downloads (batch 3,
    docs/VULNERABILITY_SCAN_IMPROVEMENTS.md item 6): force download by default (never
    render inline in the browser, which could execute an uploaded HTML/SVG file in the
    app's origin), and tell caches/proxies never to store a copy of someone's private
    document. `inline=True` is only safe for callers whose upload validator already
    restricts the file to formats browsers render harmlessly (PDF/JPG/PNG) — see
    download_qualification(), the only caller that currently opts in."""
    response = FileResponse(file_field.open("rb"), as_attachment=not inline, filename=filename)
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@role_required(Role.TUTOR, Role.TUTEE, Role.ADMIN)
def download_class_document(request, pk):
    if request.user.role == Role.ADMIN:
        document = get_object_or_404(ClassDocument, pk=pk)
    else:
        document = get_object_or_404(ClassDocument, pk=pk, is_active=True)
        if document.program not in visible_class_document_programs(request.user):
            raise Http404
    AuditLog.record(
        actor=request.user, target_user=request.user, event_type="CLASS_DOCUMENT_DOWNLOADED",
        description="下載上課文件 / Class document downloaded",
        metadata={"document_id": document.pk, "program": document.program.code, "title_zh": document.title_zh},
    )
    return _private_file_response(document.file, document.filename)


@role_required(Role.TUTOR, Role.ADMIN)
def download_oral_exam_attachment(request):
    """線上口語考試公告的歷年試題附件下載(2026-10-06 新增,只有一份合併檔案,不是
    一年一個檔案——見 `OralExamAnnouncement` 的模型說明)。比照
    `download_class_document()` 的既有寫法:Admin 永遠能看,其餘角色(這裡只有
    `Role.TUTOR` 會通過上面的 `@role_required`)還要再檢查公告已發佈且本人是 NTNU
    Tutor,跟 Tutor 能不能看到這則公告本身的規則完全一致。"""
    announcement = OralExamAnnouncement.objects.first()
    if announcement is None or not announcement.attachment_file:
        raise Http404
    if request.user.role != Role.ADMIN:
        if not announcement.is_published:
            raise Http404
        tutor_program = user_program(request.user)
        if not (tutor_program and tutor_program.code == "NTNU"):
            raise Http404
    AuditLog.record(
        actor=request.user, target_user=request.user, event_type="ORAL_EXAM_ATTACHMENT_DOWNLOADED",
        description="下載線上口語考試附件 / Oral exam attachment downloaded",
        metadata={"years": announcement.attachment_years},
    )
    return _private_file_response(announcement.attachment_file, announcement.attachment_filename)


@role_required(Role.TUTOR)
@require_POST
def upload_qualification(request):
    current = QualificationDocument.objects.filter(tutor=request.user).first()
    # 2026-09-08 師大資中弱點掃描發現的第二個真實 500(見
    # docs/VULNERABILITY_SCAN_REPORT_2026-09-08_ACTION_PLAN.md 應用程式錯誤分類),經
    # codex review 進一步指出原本的修法還不夠:重新送審時若送出的表單根本沒有 "file"
    # 這個欄位(例如殘缺的 multipart 送出 file[]=...,或單純忘記選檔案),Django
    # FileField.clean() 會依既有慣例回退使用 instance 上的舊檔案讓 form.is_valid() 仍為
    # True——若照這個結果繼續送出,會在沒有任何新證據的情況下,把已核准/已拒絕的文件
    # 狀態重置回 PENDING、清空審核備註與審核人員,等同讓 Tutor 靠著送一個空白表單就能
    # 撤銷 Admin 的審核結果。改成直接檢查 request.FILES,沒有真的上傳新檔案就在表單驗證
    # 之前拒絕,不建立/不修改任何欄位(原檔案、審核狀態、留言皆維持原樣)。
    if "file" not in request.FILES:
        # 2026-09-11(codex review):這是手動組出的 messages.error(),不會經過
        # accounts/forms.py::add_form_classes() 幫表單欄位統一設定的
        # error_messages["required"](該處刻意維持中文單語,是全站既有慣例,見
        # CLAUDE.md 第 7 節),所以這裡要自己明確寫成雙語,不能只複製那組慣例的中文字串。
        messages.error(request, "此欄位為必填欄位。 / This field is required.")
        return redirect(reverse("accounts:dashboard") + "#qualification")
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
    return redirect(reverse("accounts:dashboard") + "#qualification")


@login_required
def download_qualification(request, pk):
    document = get_object_or_404(QualificationDocument, pk=pk)
    if request.user.role != Role.ADMIN and document.tutor_id != request.user.pk:
        raise Http404
    is_preview = request.GET.get("intent") == "preview"
    AuditLog.record(
        actor=request.user, target_user=request.user,
        event_type="QUALIFICATION_DOCUMENT_PREVIEWED" if is_preview else "QUALIFICATION_DOCUMENT_DOWNLOADED",
        description="預覽口語能力證明 / Oral proficiency document previewed" if is_preview
        else "下載口語能力證明 / Oral proficiency document downloaded",
        metadata={"document_id": document.pk, "tutor_id": document.tutor_id},
    )
    # Safe to render inline: validate_qualification_file() restricts uploads to
    # PDF/JPG/PNG only, none of which execute as scripts in the browser.
    return _private_file_response(document.file, document.original_filename, inline=is_preview)


@role_required(Role.ADMIN)
@require_POST
@transaction.atomic
def review_qualification(request, pk):
    """2026-10-09(使用者要求線上口語考試「考試名單」也能標記口語是否通過,直接重用
    這個既有 view,不另外寫一套——使用者原話「如果按通過就代表口語能力證明直接通過」,
    這就是口語能力審核本身):`next=oral-exam` 讓呼叫端(考試名單卡片)導回「線上口語
    考試」分頁,不是預設的「口語能力審核」分頁,比照 `tutoring:review_class` 既有的
    `next` 參數寫法。"""
    document = get_object_or_404(QualificationDocument.objects.select_for_update(), pk=pk)
    action = request.POST.get("action")
    if action not in {"approve", "reject", "revert"}:
        return HttpResponseBadRequest("Invalid review action")
    redirect_target = reverse("accounts:dashboard") + (
        "#oral-exam" if request.POST.get("next") == "oral-exam" else "#qualifications"
    )
    if action == "revert":
        document.status = QualificationStatus.PENDING
        document.review_note = ""
        document.reviewed_by = None
        document.reviewed_at = None
        document.save()
        log_event(
            request,
            "QUALIFICATION_REVIEW_REVERTED",
            "口語能力證明審核結果已撤回，回到待審核 / Oral proficiency review reverted to pending",
            document.tutor,
        )
        messages.success(request, "已撤回審核結果，回到待審核。 / Review result reverted to pending.")
        return redirect(redirect_target)
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
    return redirect(redirect_target)


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
def import_oral_exam_pass_list(request):
    """2026-09-11(使用者要求):比對系辦「碩士生修業概況一覽表」的語音欄位,只作為
    口語能力審核頁面的輔助提示(見 dashboard() 的 pending_qualifications 標記),不會
    自動核准/拒絕任何 QualificationDocument——那一律仍由 Admin 手動決定。"""
    redirect_target = reverse("accounts:dashboard") + "#qualifications"
    form = OralExamPassListImportForm(request.POST, request.FILES)
    if not form.is_valid():
        for errors in form.errors.values():
            for error in errors:
                messages.error(request, error)
        return redirect(redirect_target)

    uploaded_file = form.cleaned_data["file"]
    list_type = form.cleaned_data["list_type"]
    try:
        result = import_department_oral_exam_pass_list(uploaded_file, admin=request.user, list_type=list_type)
    except OralExamPassListImportError as exc:
        messages.error(request, str(exc))
        return redirect(redirect_target)

    log_event(
        request,
        "ORAL_EXAM_PASS_LIST_IMPORTED",
        f"匯入系辦資格比對名單（{list_type}），比對到 {result.matched_count} 位 / "
        f"Imported department eligibility list ({list_type}), matched {result.matched_count}",
        metadata={
            "list_type": list_type,
            "matched_count": result.matched_count,
            "created_count": result.created_count,
            "sheets_used": result.sheets_used,
            "filename": uploaded_file.name,
        },
    )
    messages.success(
        request,
        f"已比對 {result.matched_count} 位符合資格的學號（新增 {result.created_count} 筆）。 / "
        f"Matched {result.matched_count} eligible student ID(s) ({result.created_count} newly added).",
    )
    return redirect(redirect_target)


@role_required(Role.ADMIN)
@require_POST
def save_announcement(request, pk=None):
    """公告欄項目建立/編輯共用同一個 view(比照 4.10 節 save_class_document() 的既有寫法)。"""
    redirect_target = reverse("accounts:dashboard") + "#announcements"
    instance = get_object_or_404(Announcement, pk=pk) if pk else None
    form = AnnouncementForm(request.POST, instance=instance, prefix=f"announcement-{pk}" if pk else None)
    if not form.is_valid():
        for errors in form.errors.values():
            for error in errors:
                messages.error(request, error)
        return redirect(redirect_target)

    announcement = form.save(commit=False)
    if instance is None:
        announcement.created_by = request.user
    announcement.save()
    log_event(
        request,
        "ANNOUNCEMENT_UPDATED" if instance else "ANNOUNCEMENT_CREATED",
        "更新公告欄項目 / Announcement updated" if instance else "新增公告欄項目 / Announcement created",
        metadata={"announcement_id": announcement.pk},
    )
    messages.success(request, "公告已儲存。 / Announcement saved.")
    return redirect(redirect_target)


@role_required(Role.ADMIN)
@require_POST
def delete_announcement(request, pk):
    announcement = get_object_or_404(Announcement, pk=pk)
    announcement_id = announcement.pk
    announcement.delete()
    log_event(
        request,
        "ANNOUNCEMENT_DELETED",
        "刪除公告欄項目 / Announcement deleted",
        metadata={"announcement_id": announcement_id},
    )
    messages.success(request, "公告已刪除。 / Announcement deleted.")
    return redirect(reverse("accounts:dashboard") + "#announcements")


@role_required(Role.ADMIN)
@require_POST
def save_oral_exam_announcement(request):
    """師大外籍生(NTNU)線上口語考試公告的建立/編輯/發佈/取消發佈共用同一個 view
    (2026-10-06 新增,使用者要求)。只保留「目前這一次」設定,`instance` 一律是
    `OralExamAnnouncement.objects.first()`(可能是 `None`,代表第一次填寫);`action`
    欄位決定這次送出是要發佈還是取消發佈,跟日期欄位本身的編輯共用同一個表單,因為
    「取消發佈」按鈕就在同一個 `<form>` 裡,`request.POST` 已經包含目前表單上的日期值。
    """
    redirect_target = reverse("accounts:dashboard") + "#oral-exam"
    instance = OralExamAnnouncement.objects.first()
    form = OralExamAnnouncementForm(request.POST, instance=instance)
    if not form.is_valid():
        for errors in form.errors.values():
            for error in errors:
                messages.error(request, error)
        return redirect(redirect_target)

    announcement = form.save(commit=False)
    # 2026-10-06(使用者要求「附件年份...可以上傳檔案」,隨後澄清「那三個年份只是顯示用
    # ...附件都是三年合併成一個檔案」):檔案只有一份(三年合併考題),跟三個年份欄位彼此
    # 獨立——年份只用來組公告文字,不是一年一個檔案。這次送出沒有附加新檔案時維持既有
    # 檔案不變(只改日期/年份不必重新上傳同一份合併考題);附加了新檔案則直接取代舊檔案。
    uploaded_file = request.FILES.get("attachment_file")
    if uploaded_file:
        try:
            validate_class_document_file(uploaded_file)
        except ValidationError as error:
            for message in error.messages:
                messages.error(request, message)
            return redirect(redirect_target)
        announcement.attachment_file = uploaded_file
        announcement.attachment_filename = uploaded_file.name
    action = request.POST.get("action")
    if action == "publish":
        announcement.is_published = True
    elif action == "unpublish":
        announcement.is_published = False
    announcement.updated_by = request.user
    announcement.save()
    log_event(
        request,
        "ORAL_EXAM_ANNOUNCEMENT_PUBLISHED" if announcement.is_published else "ORAL_EXAM_ANNOUNCEMENT_UNPUBLISHED",
        "線上口語考試公告已發佈 / Oral exam announcement published"
        if announcement.is_published
        else "線上口語考試公告已取消發佈 / Oral exam announcement unpublished",
        metadata={"exam_date": str(announcement.exam_date), "registration_deadline": str(announcement.registration_deadline)},
    )
    messages.success(
        request,
        "口語考試公告已發佈。 / Oral exam announcement published."
        if announcement.is_published
        else "口語考試公告已取消發佈。 / Oral exam announcement unpublished.",
    )
    return redirect(redirect_target)


@role_required(Role.TUTOR)
@require_POST
def submit_oral_exam_registration(request):
    """NTNU Tutor 報名線上口語考試(2026-10-06 新增,使用者要求「如果開放報名，tutor
    就可以點擊報名，完成兩個欄位 1. 選3個時間段 2. 上傳檔案(繳費紀錄) 就可以送出」)。
    報名截止前重新送出會更新(覆蓋)前一次,`instance` 一律抓這位 Tutor 對這一輪考試
    (以 `announcement.exam_date` 這個快照值比對)已有的那一筆,不存在則是 `None`。
    """
    redirect_target = reverse("accounts:dashboard") + "#oral-exam"
    announcement = OralExamAnnouncement.objects.first()
    tutor_program = user_program(request.user)
    if not announcement or not announcement.is_published or not (tutor_program and tutor_program.code == "NTNU"):
        raise Http404
    if not announcement.is_registration_open:
        messages.error(request, "報名已截止。 / Registration has closed.")
        return redirect(redirect_target)
    existing = OralExamRegistration.objects.filter(tutor=request.user, exam_date=announcement.exam_date).first()
    # 2026-10-07(使用者要求「如果admin檢查可以，狀態就顯示已登記，然後tutor介面就不能
    # 再更改時間段了」):Admin 人工核對完成後按「登記」,這筆報名就鎖定,Tutor 不能再
    # 透過這個 view 更新時段或繳費紀錄——比照 4.6 節 `ClassReview.APPROVED` 鎖定課堂
    # 紀錄的既有慣例,伺服器端這道檢查才是真正把關,畫面上也會同步不顯示表單。
    if existing and existing.is_confirmed:
        messages.error(
            request,
            "此報名已由管理員登記完成，無法再修改。 / This registration has already been confirmed by an administrator and can no longer be changed.",
        )
        return redirect(redirect_target)
    # 2026-10-09(使用者要求「現在每次安排考試最多20人...已經滿了先停止報名」,接著
    # 澄清「如果讓他們報名...他們都已經繳費了，所以我才說要從報名人數開始擋」):只擋
    # 全新報名(`existing` 為 None)——已經送出過的 Tutor(不論 PENDING/NEEDS_REVISION)
    # 本來就不是在跟別人搶名額,維持可以繼續編輯自己原本那一筆。**算的是「已送出報名」
    # 的總數,不分 PENDING/NEEDS_REVISION/CONFIRMED**——報名時就要求繳費,送出就代表
    # 已經付過這筆名額的費用,若只擋已登記(CONFIRMED)人數,等 Admin 核對完才發現超額,
    # 多繳費的人等於白白浪費,所以上限要卡在「送出」這一步。
    if not existing and OralExamRegistration.objects.filter(
        exam_date=announcement.exam_date,
    ).count() >= ORAL_EXAM_MAX_REGISTRATIONS:
        messages.error(
            request,
            f"報名已達上限（{ORAL_EXAM_MAX_REGISTRATIONS} 人），暫停開放新報名。 / "
            f"Registration is full ({ORAL_EXAM_MAX_REGISTRATIONS} max) — new sign-ups are paused.",
        )
        return redirect(redirect_target)
    form = OralExamRegistrationForm(request.POST, request.FILES, instance=existing)
    if not form.is_valid():
        for errors in form.errors.values():
            for error in errors:
                messages.error(request, error)
        return redirect(redirect_target)
    registration = form.save(commit=False)
    registration.tutor = request.user
    registration.exam_date = announcement.exam_date
    if "payment_proof" in request.FILES:
        try:
            validate_class_document_file(request.FILES["payment_proof"])
        except ValidationError as error:
            for message in error.messages:
                messages.error(request, message)
            return redirect(redirect_target)
        registration.payment_proof_filename = request.FILES["payment_proof"].name
    registration.save()
    log_event(
        request,
        "ORAL_EXAM_REGISTRATION_SUBMITTED",
        "線上口語考試報名已送出 / Oral exam registration submitted",
        metadata={"exam_date": str(registration.exam_date)},
    )
    messages.success(request, "報名已送出。 / Registration submitted.")
    return redirect(redirect_target)


@role_required(Role.ADMIN)
@require_POST
def review_oral_exam_registration(request, pk):
    """Admin 人工核對報名後按「登記」或「補件」(2026-10-06 新增「登記」,2026-10-07
    使用者要求「登記狀態也加個撤回功能好了，以及「補件」按鈕和可以紀錄留言」擴充成
    這個統一的 view,比照 `review_qualification()` 用單一 `action` 參數分流決定的
    既有寫法,不是每種決定各開一個 view)。「登記」(`CONFIRMED`)後這筆報名就鎖定,
    Tutor 不能再更改時段(見 `submit_oral_exam_registration()` 的鎖定檢查);
    「補件」(`NEEDS_REVISION`)則刻意維持可編輯,讓 Tutor 看到留言後能補件重新送出。
    沒有審核人員身分限制,任何 Admin 都可以操作,與本專案其餘審核類操作的既有慣例一致
    (核准/拒絕、標記已紀錄等都不做逐筆歸屬限制)。"""
    registration = get_object_or_404(OralExamRegistration, pk=pk)
    action = request.POST.get("action")
    if action == "confirm":
        registration.review_status = OralExamRegistrationReviewStatus.CONFIRMED
        event_type, description = "ORAL_EXAM_REGISTRATION_CONFIRMED", "線上口語考試報名已登記 / Oral exam registration confirmed"
        success_message = "已標記為已登記。 / Marked as confirmed."
    elif action == "revise":
        registration.review_status = OralExamRegistrationReviewStatus.NEEDS_REVISION
        event_type = "ORAL_EXAM_REGISTRATION_NEEDS_REVISION"
        description = "線上口語考試報名要求補件 / Oral exam registration marked as needing additional documents"
        success_message = "已標記為補件，老師會看到您留的訊息。 / Marked as needing additional documents."
    else:
        raise Http404
    registration.review_note = request.POST.get("note", "").strip()
    registration.reviewed_by = request.user
    registration.reviewed_at = timezone.now()
    registration.save(update_fields=["review_status", "review_note", "reviewed_by", "reviewed_at"])
    log_event(
        request, event_type, description, target_user=registration.tutor,
        metadata={"registration_id": registration.pk, "exam_date": str(registration.exam_date)},
    )
    messages.success(request, success_message)
    return redirect(reverse("accounts:dashboard") + "#oral-exam")


@role_required(Role.ADMIN)
@require_POST
def revert_oral_exam_registration(request, pk):
    """Admin 誤按「登記」或「補件」時撤回(2026-10-07 新增,使用者要求),比照口語能力
    審核撤回的既有慣例:退回 `PENDING`、清空留言與核對人員/時間。**若撤回的是
    `CONFIRMED`,一併清掉 `exam_time`/`exam_order`**——這個人已經不算登記成功,
    不該繼續留在「考試名單」卡片裡,不用等下一次按「安排考試」才會消失。"""
    registration = get_object_or_404(OralExamRegistration, pk=pk)
    previous_status = registration.review_status
    registration.review_status = OralExamRegistrationReviewStatus.PENDING
    registration.review_note = ""
    registration.reviewed_by = None
    registration.reviewed_at = None
    registration.exam_time = None
    registration.exam_order = None
    registration.save(
        update_fields=["review_status", "review_note", "reviewed_by", "reviewed_at", "exam_time", "exam_order"],
    )
    log_event(
        request, "ORAL_EXAM_REGISTRATION_REVERTED", "線上口語考試報名核對已撤回 / Oral exam registration review reverted",
        target_user=registration.tutor,
        metadata={"registration_id": registration.pk, "previous_status": previous_status},
    )
    messages.success(request, "已撤回，這筆報名改回尚未核對狀態。 / Reverted — this registration is pending review again.")
    return redirect(reverse("accounts:dashboard") + "#oral-exam")


@role_required(Role.ADMIN)
@require_POST
def schedule_oral_exam(request):
    """Admin 按「安排考試」後,依目前所有已登記報名的可口試時段排出考試順序表
    (2026-10-07 新增,使用者要求「下方新增一個卡片「考試名單」...把已登記的tutor，
    根據他們的時間組合排列...考試順序」)。排法見
    `accounts/services.py::schedule_oral_exam_registrations()`;每次按都會整批
    重算覆蓋,不是疊加。"""
    redirect_target = reverse("accounts:dashboard") + "#oral-exam"
    announcement = OralExamAnnouncement.objects.first()
    if not announcement:
        raise Http404
    scheduled, unscheduled = schedule_oral_exam_registrations(announcement.exam_date)
    log_event(
        request,
        "ORAL_EXAM_SCHEDULED",
        "線上口語考試名單已安排 / Oral exam schedule arranged",
        metadata={"exam_date": str(announcement.exam_date), "scheduled": len(scheduled), "unscheduled": len(unscheduled)},
    )
    if unscheduled:
        messages.error(
            request,
            f"已排出 {len(scheduled)} 位，但有 {len(unscheduled)} 位時段互相衝突無法排入，請確認他們的可口試時段。 / "
            f"Scheduled {len(scheduled)}, but {len(unscheduled)} couldn't be placed due to conflicting time slots.",
        )
    else:
        messages.success(request, f"已安排 {len(scheduled)} 位的考試順序。 / Scheduled {len(scheduled)} exam slots.")
    return redirect(redirect_target)


@role_required(Role.ADMIN)
@require_POST
def save_oral_exam_meet_link(request, pk):
    """Admin(助教)幫「考試名單」裡的每一位填上口試用的視訊連結(2026-10-09 新增,
    使用者要求「可以讓助教放上google meet連結」)。刻意不限定網域——Admin 可能改用
    別的視訊工具(例如 Zoom),用通用的 URL 欄位比硬性要求 meet.google.com 更有彈性。"""
    registration = get_object_or_404(OralExamRegistration, pk=pk)
    meet_link = request.POST.get("meet_link", "").strip()
    if meet_link:
        try:
            URLValidator(schemes=["http", "https"])(meet_link)
        except ValidationError:
            messages.error(request, "請輸入有效的網址（需以 http:// 或 https:// 開頭）。 / Please enter a valid URL (starting with http:// or https://).")
            return redirect(reverse("accounts:dashboard") + "#oral-exam")
    registration.meet_link = meet_link
    registration.save(update_fields=["meet_link"])
    messages.success(request, "視訊連結已儲存。 / Meeting link saved.")
    return redirect(reverse("accounts:dashboard") + "#oral-exam")


@login_required
def download_oral_exam_payment_proof(request, pk):
    """Tutor 報名時上傳的繳費紀錄下載(2026-10-06 新增)。Admin 永遠能看(核對有沒有
    繳費);本人也能看自己上傳過的內容;其餘任何人都不行,包含其他 Tutor。"""
    registration = get_object_or_404(OralExamRegistration, pk=pk)
    if request.user.role != Role.ADMIN and registration.tutor_id != request.user.pk:
        raise Http404
    AuditLog.record(
        actor=request.user, target_user=registration.tutor, event_type="ORAL_EXAM_PAYMENT_PROOF_DOWNLOADED",
        description="下載線上口語考試繳費紀錄 / Oral exam payment proof downloaded",
        metadata={"registration_id": registration.pk},
    )
    return _private_file_response(registration.payment_proof, registration.payment_proof_filename)


@login_required
@require_POST
def mark_announcements_read(request):
    """由 `static/js/dashboard.js` 在使用者切到「公告欄」分頁時以 fetch 呼叫(2026-09-25
    新增,使用者要求「使用者要點進來看過這個提示才會不見」)。純粹更新這位使用者的
    `AnnouncementReadState.last_viewed_at`,不寫 AuditLog——這是使用者端的已讀狀態,
    不是需要稽核的行政操作,比照私訊「開啟對話即標記已讀」的既有慣例(不記錄稽核)。"""
    AnnouncementReadState.objects.update_or_create(
        user=request.user, defaults={"last_viewed_at": timezone.now()}
    )
    return JsonResponse({"ok": True})


@login_required
@require_POST
def mark_dashboard_section_read(request, section):
    """2026-10-03(使用者要求):跟 `mark_announcements_read()` 同樣的機制,但一個使用者
    要分別追蹤多個分類(口語能力證明/輔導時數/異常回報),所以用 `section` 這個路徑參數
    區分要更新哪一筆 `DashboardReadState`,而不是像公告欄那樣每人固定一筆。"""
    if section not in DashboardSection.values:
        raise Http404
    DashboardReadState.objects.update_or_create(
        user=request.user, section=section, defaults={"last_viewed_at": timezone.now()}
    )
    return JsonResponse({"ok": True})


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
            "updated_count": result.updated_count,
            "updated_student_ids": result.updated_ids,
            "skipped_existing_count": len(result.skipped_existing_ids),
            "skipped_invalid_count": len(result.skipped_invalid),
            "filename": uploaded_file.name,
        },
    )
    success_text = f"「{category_label}」已新增 {result.created_count} 筆學號。 / Added {result.created_count} student ID(s) to {category_label}."
    if result.updated_count:
        success_text += (
            f" 已補上 {result.updated_count} 筆既有名冊的身分別。 / "
            f"Filled identity categories for {result.updated_count} existing roster record(s)."
        )
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


class _FakeSecurityQuestions:
    """Presents the same interface as SecurityQuestionAnswer for a student ID that has no
    real account or security questions, so the recovery flow can render an
    indistinguishable question form and reach the same "verification failed" outcome
    without ever revealing that the account doesn't exist (item 4.4,
    docs/VULNERABILITY_SCAN_IMPROVEMENTS.md).

    The 3 decoy questions are deterministic per student ID (seeded hash, not Python's
    global random state) so repeated lookups of the same ID show the same questions
    instead of changing every request — a change on every request would itself be a
    distinguishing signal an attacker could use to tell fake from real. check_answers()
    always runs the same number of password-hash comparisons as the real implementation
    so both code paths do roughly the same amount of work; this is a best-effort timing
    mitigation, not a guarantee against a sufficiently precise timing attack (same caveat
    already documented for the PDF copy-protection feature in CLAUDE.md).
    """

    _DECOY_HASH = make_password("recovery-enumeration-decoy")

    def __init__(self, student_id):
        choices = SecurityQuestionAnswer.ACTIVE_QUESTION_CHOICES
        digest = hashlib.sha256(student_id.encode()).digest()
        indices = list(range(len(choices)))
        random.Random(int.from_bytes(digest, "big")).shuffle(indices)
        self._labels = [choices[index][1] for index in indices[:3]]

    def get_question_1_display(self):
        return self._labels[0]

    def get_question_2_display(self):
        return self._labels[1]

    def get_question_3_display(self):
        return self._labels[2]

    def check_answers(self, answers):
        for value in answers:
            check_password(SecurityQuestionAnswer.normalize_answer(value), self._DECOY_HASH)
        return False


def recover_account(request):
    if request.user.is_authenticated:
        return redirect("accounts:dashboard")
    lookup_form = RecoveryLookupForm(request.POST or None)
    answer_form = None
    student_id = ""
    if request.method == "POST" and lookup_form.is_valid():
        student_id = lookup_form.cleaned_data["student_id"]

        # Two throttle layers (docs/VULNERABILITY_SCAN_IMPROVEMENTS.md batch 5), both
        # covering the lookup step (viewing the question form) and the verify step
        # (submitting answers) together: an IP+student_id key (5/15min) catches repeated
        # attempts from one source, and a student_id-only key (20/15min) catches a slow
        # attack against one account spread across many IPs. Checked and incremented
        # before the real/fake account branch below, so probing many nonexistent IDs
        # can't dodge the same rate limit a real attempt would hit.
        throttle_keys = [
            (f"recovery:{client_ip(request)}:{student_id}", 5),
            (f"recovery_id:{student_id}", 20),
        ]
        if any_throttled(throttle_keys):
            messages.error(request, "嘗試次數過多，請 15 分鐘後再試。 / Too many attempts. Please try again in 15 minutes.")
            return render(
                request, "accounts/recover.html",
                {"lookup_form": lookup_form, "answer_form": None, "student_id": student_id},
            )
        throttle_key_names = [key for key, _limit in throttle_keys]
        register_failures(throttle_key_names)

        # username is already normalized to uppercase by RecoveryLookupForm.clean_student_id();
        # __iexact is defensive in depth in case a stored username were ever not uppercase.
        user = User.objects.filter(username__iexact=student_id, is_active=True).first()
        real_questions = SecurityQuestionAnswer.objects.filter(user=user).first() if user else None
        account_exists = bool(user and real_questions)
        # Real or fake, `questions` always has the same interface below — the view never
        # branches on account_exists again until after check_answers() has already run.
        questions = real_questions or _FakeSecurityQuestions(student_id)

        is_verification = request.POST.get("action") == "verify"
        answer_form = RecoveryVerificationForm(request.POST if is_verification else None, questions=questions)
        if not is_verification or not answer_form.is_valid():
            return render(
                request, "accounts/recover.html",
                {"lookup_form": lookup_form, "answer_form": answer_form, "student_id": student_id},
            )

        answers = [answer_form.cleaned_data[f"answer_{index}"] for index in range(1, 4)]
        # Always call check_answers(), even for a nonexistent account, before looking at
        # account_exists — this keeps the fake path doing the same password-hash work as
        # the real path instead of short-circuiting past it.
        answers_match = questions.check_answers(answers)
        verified = account_exists and answers_match
        if verified:
            request.session["recovery_user_id"] = user.pk
            request.session["recovery_verified_at"] = timezone.now().isoformat()
            clear_throttles(throttle_key_names)
            log_event(request, "RECOVERY_VERIFIED", "安全問題驗證成功 / Security questions verified", user)
            return redirect("accounts:set_recovered_password")
        log_event(request, "RECOVERY_FAILED", "帳號恢復驗證失敗 / Account recovery verification failed")
        messages.error(request, "資料無法驗證，請重新確認或洽系辦。 / We could not verify the information. Please check again or contact the office.")
    return render(
        request, "accounts/recover.html",
        {"lookup_form": lookup_form, "answer_form": answer_form, "student_id": student_id},
    )


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
