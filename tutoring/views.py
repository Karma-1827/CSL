from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from accounts.models import AuditLog, Role, User

from .forms import (
    AdminPairingForm, ClassAlertForm, ClassRecordForm, HoursDownloadForm, IncidentReportForm, PairingMessageForm,
    RescheduleClassForm, ScheduleClassForm, SemesterCreateForm, SemesterSettingsForm,
)
from .models import (
    ClassAlert, ClassAlertStatus, ClassSession, IncidentReport,
    Pairing, PairingMessage, PairingStatus, Semester,
)
from .reporting import (
    build_excel_xlsx,
    build_export_csv,
    build_export_pdf,
    build_hours_pdf,
    hour_report_data,
    user_has_hour_records,
)
from .services import (
    SKILL_LABELS,
    cancel_class,
    cancel_class_alert,
    cancel_invitation,
    check_in,
    class_is_valid,
    confirm_counterpart,
    create_admin_pairing,
    respond_to_invitation,
    reschedule_class,
    report_class_alert,
    resolve_class_alert,
    resolve_incident_report,
    review_pairing_release_request,
    review_makeup,
    schedule_classes,
    send_invitation,
    submit_incident_report,
    submit_pairing_release_request,
    submit_class_record,
)


def _show_validation_error(request, error):
    messages.error(request, " ".join(error.messages))


@login_required
@require_POST
def save_semester(request, pk=None):
    if request.user.role != Role.ADMIN:
        raise Http404
    instance = get_object_or_404(Semester, pk=pk) if pk else None
    form_class = SemesterSettingsForm if instance else SemesterCreateForm
    form = form_class(request.POST, instance=instance, prefix=f"semester-{pk}" if pk else None)
    if form.is_valid():
        semester = form.save(commit=False)
        if instance is None:
            semester.is_active = True
        semester.save()
        form.save_m2m()
        AuditLog.record(
            actor=request.user,
            event_type="SEMESTER_UPDATED" if instance else "SEMESTER_CREATED",
            description="更新學期設定 / Semester settings saved",
            metadata={"semester_id": semester.pk},
        )
        messages.success(request, "學期設定已儲存。 / Semester settings saved.")
    else:
        for errors in form.errors.values():
            for error in errors:
                messages.error(request, error)
    return redirect(f"{reverse('accounts:dashboard')}#semesters")


@login_required
@require_POST
def archive_semester(request, pk):
    if request.user.role != Role.ADMIN:
        raise Http404
    semester = get_object_or_404(Semester, pk=pk, is_active=True)
    if semester.ends_on >= timezone.localdate():
        messages.error(request, "學期結束後才能刪除設定。 / Settings can be removed after the semester ends.")
    else:
        semester.is_active = False
        semester.save(update_fields=["is_active"])
        AuditLog.record(
            actor=request.user,
            event_type="SEMESTER_ARCHIVED",
            description="刪除過期學期設定 / Expired semester setting removed",
            metadata={"semester_id": semester.pk},
        )
        messages.success(request, "學期設定已刪除，歷史時數資料仍會保留。 / Setting removed; hour records were preserved.")
    return redirect(f"{reverse('accounts:dashboard')}#semesters")


@login_required
@require_POST
def delete_semester(request, pk):
    if request.user.role != Role.ADMIN:
        raise Http404
    semester = get_object_or_404(Semester, pk=pk)
    if Pairing.objects.filter(semester=semester).exists():
        messages.error(
            request,
            "此學期已有配對資料，無法刪除，請改用編輯修改日期。 / "
            "This semester already has pairings and cannot be deleted; use edit instead.",
        )
    else:
        semester_id = semester.pk
        semester.delete()
        AuditLog.record(
            actor=request.user,
            event_type="SEMESTER_DELETED",
            description="刪除學期設定（尚無配對資料） / Semester setting deleted (no pairings yet)",
            metadata={"semester_id": semester_id},
        )
        messages.success(request, "學期設定已刪除。 / Semester setting deleted.")
    return redirect(f"{reverse('accounts:dashboard')}#semesters")


def _pairing_for_participant(user, pk):
    pairing = get_object_or_404(
        Pairing.objects.select_related("semester", "tutor", "tutee"), pk=pk
    )
    if user.pk not in {pairing.tutor_id, pairing.tutee_id}:
        raise Http404
    return pairing


@login_required
@require_http_methods(["GET", "POST"])
def pairing_messages(request, pk):
    pairing = _pairing_for_participant(request.user, pk)
    counterpart = pairing.tutee if request.user.pk == pairing.tutor_id else pairing.tutor
    PairingMessage.objects.filter(pairing=pairing, read_at__isnull=True).exclude(sender=request.user).update(
        read_at=timezone.now()
    )
    form = PairingMessageForm(request.POST or None)
    if request.method == "POST":
        if pairing.status != PairingStatus.ACTIVE:
            messages.error(request, "已結束的配對只能查看歷史訊息。 / Ended pairings are read-only.")
        elif form.is_valid():
            row = form.save(commit=False)
            row.pairing, row.sender = pairing, request.user
            row.full_clean()
            row.save()
            return redirect("tutoring:pairing_messages", pk=pairing.pk)
    conversations = Pairing.objects.filter(
        Q(tutor=request.user) | Q(tutee=request.user)
    ).select_related("tutor", "tutee", "semester").order_by("-started_at")
    return render(request, "tutoring/messages.html", {
        "pairing": pairing, "counterpart": counterpart, "message_form": form,
        "message_rows": pairing.messages.select_related("sender"), "conversations": conversations,
    })


@login_required
@require_POST
def download_hours(request):
    if not user_has_hour_records(request.user):
        raise Http404
    form = HoursDownloadForm(request.POST, user=request.user)
    if not form.is_valid():
        for errors in form.errors.values():
            for error in errors:
                messages.error(request, error)
        return redirect(f"{reverse('accounts:dashboard')}#hours")
    data = hour_report_data(
        request.user, form.cleaned_data["starts_on"], form.cleaned_data["ends_on"],
        program=form.cleaned_data.get("program"),
    )
    try:
        content = build_hours_pdf(
            data,
            version=form.cleaned_data["version"],
            detail_fields=form.cleaned_data.get("detail_fields", []),
            program=form.cleaned_data.get("program"),
            language=form.cleaned_data["language"],
        )
    except ValidationError as error:
        _show_validation_error(request, error)
        return redirect(f"{reverse('accounts:dashboard')}#hours")
    is_preview = request.POST.get("intent") == "preview"
    disposition = "inline" if is_preview else "attachment"
    response = HttpResponse(content, content_type="application/pdf")
    response["Content-Disposition"] = (
        f'{disposition}; filename="MPTS-certificate-{request.user.username}'
        f'-{form.cleaned_data["language"]}-{data["ends_on"]}.pdf"'
    )
    AuditLog.record(
        actor=request.user, target_user=request.user,
        event_type="HOURS_PDF_PREVIEWED" if is_preview else "HOURS_PDF_DOWNLOADED",
        description="預覽輔導時數紀錄 / Hours record previewed" if is_preview else "下載輔導時數紀錄 / Hours record downloaded",
        metadata={
            "starts_on": str(data["starts_on"]), "ends_on": str(data["ends_on"]),
            "hours": str(data["total"]), "version": form.cleaned_data["version"],
            "detail_fields": form.cleaned_data.get("detail_fields", []),
            "language": form.cleaned_data["language"],
        },
    )
    return response


@login_required
@require_POST
def export_excel(request):
    if request.user.role != Role.ADMIN:
        raise Http404
    scope = request.POST.get("scope", "all")
    users = User.objects.exclude(role=Role.ADMIN).select_related("roster_entry").order_by("username")
    if scope == "selected":
        ids = request.POST.getlist("user_ids")
        if not ids:
            messages.error(request, "請至少選擇一位使用者。 / Select at least one user.")
            return redirect(f"{reverse('accounts:dashboard')}#export")
        users = users.filter(pk__in=ids)
    period_mode = request.POST.get("period_mode", "semester")
    starts_on = ends_on = None
    semester = None
    if period_mode == "semester":
        semester = Semester.objects.filter(pk=request.POST.get("semester_id")).first()
        if not semester:
            messages.error(request, "請選擇學期。 / Select a semester.")
            return redirect(f"{reverse('accounts:dashboard')}#export")
        starts_on, ends_on = semester.starts_on, semester.ends_on
    elif period_mode == "range":
        try:
            starts_on = date.fromisoformat(request.POST.get("starts_on", ""))
            ends_on = date.fromisoformat(request.POST.get("ends_on", ""))
        except ValueError:
            messages.error(request, "請填寫完整日期範圍。 / Enter a complete date range.")
            return redirect(f"{reverse('accounts:dashboard')}#export")
        if starts_on > ends_on:
            messages.error(request, "開始日期不可晚於結束日期。 / Start date cannot be after end date.")
            return redirect(f"{reverse('accounts:dashboard')}#export")
    else:
        messages.error(request, "請選擇匯出期間。 / Select an export period.")
        return redirect(f"{reverse('accounts:dashboard')}#export")
    file_format = request.POST.get("file_format", "xlsx")
    if file_format == "csv":
        content = build_export_csv(users, starts_on=starts_on, ends_on=ends_on)
        content_type = "text/csv"
    elif file_format == "pdf":
        content = build_export_pdf(users, starts_on=starts_on, ends_on=ends_on)
        content_type = "application/pdf"
    else:
        file_format = "xlsx"
        content = build_excel_xlsx(users, starts_on=starts_on, ends_on=ends_on)
        content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    response = HttpResponse(content, content_type=content_type)
    response["Content-Disposition"] = f'attachment; filename="MPTS-export-{timezone.localdate()}.{file_format}"'
    AuditLog.record(
        actor=request.user, event_type="ADMIN_EXCEL_EXPORTED",
        description="匯出輔導資料 / Tutoring data exported", metadata={
            "scope": scope, "users": users.count(), "period_mode": period_mode,
            "semester_id": semester.pk if semester else None,
            "starts_on": str(starts_on), "ends_on": str(ends_on), "file_format": file_format,
        },
    )
    return response


@login_required
@require_POST
def invite_tutee(request, user_id):
    if request.user.role != Role.TUTOR:
        raise Http404
    try:
        send_invitation(initiator=request.user, tutor_id=request.user.pk, tutee_id=user_id)
    except (ValidationError, ObjectDoesNotExist) as error:
        _show_validation_error(request, error)
    else:
        messages.success(request, "邀請已送出，對方需於五天內回覆。 / Invitation sent and will expire in five days.")
    return redirect("accounts:dashboard")


@login_required
@require_POST
def invite_tutor(request, user_id):
    if request.user.role != Role.TUTEE:
        raise Http404
    try:
        send_invitation(initiator=request.user, tutor_id=user_id, tutee_id=request.user.pk)
    except (ValidationError, ObjectDoesNotExist) as error:
        _show_validation_error(request, error)
    else:
        messages.success(request, "邀請已送出，對方需於五天內回覆。 / Invitation sent and will expire in five days.")
    return redirect("accounts:dashboard")


@login_required
@require_POST
def respond_invitation(request, pk):
    action = request.POST.get("action")
    if action not in {"accept", "reject"}:
        raise Http404
    try:
        pairing = respond_to_invitation(invitation_id=pk, responder=request.user, accept=action == "accept")
    except (ValidationError, ObjectDoesNotExist) as error:
        _show_validation_error(request, error)
    else:
        if pairing:
            messages.success(request, "已建立輔導配對！ / Tutoring match created!")
        else:
            messages.success(request, "已婉拒邀請。 / Invitation declined.")
    return redirect("accounts:dashboard")


@login_required
@require_POST
def cancel_pending_invitation(request, pk):
    try:
        cancel_invitation(invitation_id=pk, actor=request.user)
    except (ValidationError, ObjectDoesNotExist) as error:
        _show_validation_error(request, error)
    else:
        messages.success(request, "邀請已取消。 / Invitation cancelled.")
    return redirect("accounts:dashboard")


@login_required
@require_POST
def create_pairing(request):
    if request.user.role != Role.ADMIN:
        raise Http404
    form = AdminPairingForm(request.POST)
    if not form.is_valid():
        for errors in form.errors.values():
            for error in errors:
                messages.error(request, error)
        return redirect(f"{reverse('accounts:dashboard')}#matching")
    try:
        create_admin_pairing(
            admin=request.user,
            tutor_id=form.cleaned_data["tutor"].pk,
            tutee_id=form.cleaned_data["tutee"].pk,
            semester_id=form.cleaned_data["semester"].pk,
        )
    except (ValidationError, ObjectDoesNotExist) as error:
        _show_validation_error(request, error)
    else:
        messages.success(request, "已建立配對。 / Pairing created.")
    return redirect(f"{reverse('accounts:dashboard')}#matching")


@login_required
@require_POST
def request_pairing_release(request, pk):
    if request.user.role not in {Role.TUTOR, Role.TUTEE}:
        raise Http404
    try:
        release_request = submit_pairing_release_request(
            pairing_id=pk,
            requester=request.user,
            reason=request.POST.get("reason", ""),
            note=request.POST.get("note", ""),
        )
    except (ValidationError, ObjectDoesNotExist) as error:
        _show_validation_error(request, error)
    else:
        if release_request.auto_resolve_at:
            messages.success(
                request,
                "解除申請已送出；若管理員 48 小時內未處理，系統將自動解除。\n"
                "Your request was submitted and will be released automatically after 48 hours if not reviewed.",
            )
        else:
            messages.success(
                request,
                "解除申請已送出，需由管理員審核。 / Your release request is awaiting administrator review.",
            )
    return redirect(f"{reverse('accounts:dashboard')}#overview")


@login_required
@require_POST
def review_pairing_release(request, pk):
    if request.user.role != Role.ADMIN:
        raise Http404
    action = request.POST.get("action")
    if action not in {"approve", "reject"}:
        raise Http404
    try:
        review_pairing_release_request(
            request_id=pk,
            admin=request.user,
            approve=action == "approve",
            note=request.POST.get("note", ""),
        )
    except (ValidationError, ObjectDoesNotExist) as error:
        _show_validation_error(request, error)
    else:
        messages.success(request, "解除申請已完成處理。 / Pairing release request reviewed.")
    return redirect(f"{reverse('accounts:dashboard')}#pairing-releases")


@login_required
@require_POST
def schedule_class(request):
    if request.user.role != Role.TUTOR:
        raise Http404
    form = ScheduleClassForm(request.POST, tutor=request.user)
    if not form.is_valid():
        for errors in form.errors.values():
            for error in errors:
                messages.error(request, error)
        return redirect("accounts:dashboard")
    try:
        sessions = schedule_classes(
            tutor=request.user,
            pairing=form.cleaned_data["pairing"],
            class_date=form.cleaned_data["class_date"],
            start_time=form.cleaned_data["start_time"],
            duration=form.cleaned_data["duration"],
            repeat_until=form.cleaned_data["repeat_until"] if form.cleaned_data["repeat_weekly"] else None,
        )
    except (ValidationError, ObjectDoesNotExist) as error:
        _show_validation_error(request, error)
    else:
        messages.success(request, f"已排入 {len(sessions)} 堂課。 / {len(sessions)} class(es) scheduled.")
    return redirect("accounts:dashboard")


def _session_for_user(user, pk):
    queryset = ClassSession.objects.select_related(
        "pairing__semester", "pairing__tutor", "pairing__tutee"
    ).prefetch_related("attendances", "class_records", "confirmations")
    session = get_object_or_404(queryset, pk=pk)
    if user.role != Role.ADMIN and user.pk not in {session.pairing.tutor_id, session.pairing.tutee_id}:
        raise Http404
    return session


@login_required
@require_http_methods(["GET", "POST"])
def class_detail(request, pk):
    session = _session_for_user(request.user, pk)
    if request.user.role == Role.ADMIN:
        tutor_attendance = next(
            (row for row in session.attendances.all() if row.participant_id == session.pairing.tutor_id), None
        )
        tutee_attendance = next(
            (row for row in session.attendances.all() if row.participant_id == session.pairing.tutee_id), None
        )
        tutor_record = next(
            (row for row in session.class_records.all() if row.author_id == session.pairing.tutor_id), None
        )
        tutee_record = next(
            (row for row in session.class_records.all() if row.author_id == session.pairing.tutee_id), None
        )
        tutor_confirmation = next(
            (row for row in session.confirmations.all() if row.reviewer_id == session.pairing.tutor_id), None
        )
        tutee_confirmation = next(
            (row for row in session.confirmations.all() if row.reviewer_id == session.pairing.tutee_id), None
        )
        for record in (tutor_record, tutee_record):
            if record:
                record.skill_labels = [SKILL_LABELS.get(skill, skill) for skill in record.skills_practiced]
        return render(
            request,
            "tutoring/admin_class_detail.html",
            {
                "session": session,
                "tutor_attendance": tutor_attendance,
                "tutee_attendance": tutee_attendance,
                "tutor_record": tutor_record,
                "tutee_record": tutee_record,
                "tutor_confirmation": tutor_confirmation,
                "tutee_confirmation": tutee_confirmation,
                "makeup_review": getattr(session, "makeup_review", None),
                "is_valid_class": class_is_valid(session),
            },
        )
    counterpart = session.pairing.tutee if request.user.pk == session.pairing.tutor_id else session.pairing.tutor
    own_record = next((row for row in session.class_records.all() if row.author_id == request.user.pk), None)
    counterpart_record = next((row for row in session.class_records.all() if row.author_id == counterpart.pk), None)
    if counterpart_record:
        counterpart_record.skill_labels = [SKILL_LABELS.get(skill, skill) for skill in counterpart_record.skills_practiced]
    own_attendance = next((row for row in session.attendances.all() if row.participant_id == request.user.pk), None)
    counterpart_attendance = next((row for row in session.attendances.all() if row.participant_id == counterpart.pk), None)
    own_confirmation = next((row for row in session.confirmations.all() if row.reviewer_id == request.user.pk), None)
    own_alert = ClassAlert.objects.filter(
        session=session, reporter=request.user, status=ClassAlertStatus.ACTIVE
    ).first()
    own_incident_reports = IncidentReport.objects.filter(session=session, reporter=request.user)
    now = timezone.now()
    form = ClassRecordForm(request.POST or None, request.FILES or None, instance=own_record)
    reschedule_form = RescheduleClassForm(
        session=session,
        initial={
            "class_date": session.class_date,
            "start_time": session.start_time,
            "duration": str(session.duration),
            "scope": "single",
        },
    )
    if request.method == "POST" and form.is_valid():
        try:
            submit_class_record(
                session_id=session.pk,
                author=request.user,
                data=form.cleaned_data,
                reason=request.POST.get("makeup_reason", ""),
            )
        except ValidationError as error:
            _show_validation_error(request, error)
        else:
            messages.success(request, "課堂紀錄已儲存。 / Class record saved.")
            return redirect("tutoring:class_detail", pk=pk)
    return render(
        request,
        "tutoring/class_detail.html",
        {
            "session": session,
            "counterpart": counterpart,
            "record_form": form,
            "reschedule_form": reschedule_form,
            "own_record": own_record,
            "counterpart_record": counterpart_record,
            "own_attendance": own_attendance,
            "counterpart_attendance": counterpart_attendance,
            "own_confirmation": own_confirmation,
            "own_alert": own_alert,
            "alert_form": ClassAlertForm(),
            "own_incident_reports": own_incident_reports,
            "incident_report_form": IncidentReportForm(),
            "checkin_requires_makeup_reason": now > session.ends_at + timedelta(minutes=30),
            "record_requires_makeup_reason": own_record is None and now > session.ends_at + timedelta(hours=24),
            "alert_window_open": session.starts_at <= now <= session.ends_at,
            "is_valid_class": class_is_valid(session),
        },
    )


@login_required
@require_POST
def class_check_in(request, pk):
    _session_for_user(request.user, pk)
    try:
        attendance = check_in(
            session_id=pk, participant=request.user, reason=request.POST.get("makeup_reason", "")
        )
    except (ValidationError, ObjectDoesNotExist) as error:
        _show_validation_error(request, error)
    else:
        label = "補簽到已送出" if attendance.is_makeup else "簽到完成"
        messages.success(request, f"{label}。 / Check-in submitted.")
    return redirect("tutoring:class_detail", pk=pk)


@login_required
@require_POST
def class_confirm(request, pk):
    _session_for_user(request.user, pk)
    status = request.POST.get("status", "")
    try:
        confirm_counterpart(
            session_id=pk, reviewer=request.user, status=status, note=request.POST.get("note", "")
        )
    except (ValidationError, ObjectDoesNotExist) as error:
        _show_validation_error(request, error)
    else:
        messages.success(request, "確認結果已送出。 / Confirmation submitted.")
    return redirect("tutoring:class_detail", pk=pk)


@login_required
@require_POST
def class_cancel(request, pk):
    _session_for_user(request.user, pk)
    try:
        cancel_class(session_id=pk, actor=request.user, reason=request.POST.get("reason", ""))
    except (ValidationError, ObjectDoesNotExist) as error:
        _show_validation_error(request, error)
    else:
        messages.success(request, "課程已取消，時數額度已釋放。 / Class cancelled and reserved hours released.")
    return redirect("accounts:dashboard")


@login_required
@require_POST
def class_reschedule(request, pk):
    session = _session_for_user(request.user, pk)
    if request.user.role != Role.TUTOR:
        raise Http404
    form = RescheduleClassForm(request.POST, session=session)
    if not form.is_valid():
        for errors in form.errors.values():
            for error in errors:
                messages.error(request, error)
        return redirect("tutoring:class_detail", pk=pk)
    try:
        rows = reschedule_class(
            session_id=session.pk,
            tutor=request.user,
            class_date=form.cleaned_data["class_date"],
            start_time=form.cleaned_data["start_time"],
            duration=form.cleaned_data["duration"],
            scope=form.cleaned_data["scope"],
        )
    except (ValidationError, ObjectDoesNotExist) as error:
        _show_validation_error(request, error)
    else:
        messages.success(request, f"已更新 {len(rows)} 堂課。 / {len(rows)} class(es) updated.")
    return redirect("tutoring:class_detail", pk=pk)


@login_required
@require_POST
def makeup_review(request, pk):
    if request.user.role != Role.ADMIN:
        raise Http404
    try:
        review_makeup(
            session_id=pk,
            admin=request.user,
            approve=request.POST.get("action") == "approve",
            note=request.POST.get("note", ""),
        )
    except (ValidationError, ObjectDoesNotExist) as error:
        _show_validation_error(request, error)
    else:
        messages.success(request, "補登審核已完成。 / Makeup review completed.")
    if request.POST.get("next") == "detail":
        return redirect("tutoring:class_detail", pk=pk)
    return redirect("accounts:dashboard")


@login_required
@require_POST
def class_alert(request, pk):
    _session_for_user(request.user, pk)
    form = ClassAlertForm(request.POST)
    if not form.is_valid():
        for errors in form.errors.values():
            for error in errors:
                messages.error(request, error)
        return redirect("tutoring:class_detail", pk=pk)
    try:
        report_class_alert(
            session_id=pk,
            reporter=request.user,
            reason=form.cleaned_data["reason"],
            note=form.cleaned_data["note"],
        )
    except (ValidationError, ObjectDoesNotExist) as error:
        _show_validation_error(request, error)
    else:
        messages.success(request, "課堂通報已送交管理員。 / Class alert sent to the administrator.")
    return redirect("tutoring:class_detail", pk=pk)


@login_required
@require_POST
def cancel_alert(request, pk, alert_id):
    _session_for_user(request.user, pk)
    try:
        cancel_class_alert(alert_id=alert_id, reporter=request.user)
    except (ValidationError, ObjectDoesNotExist) as error:
        _show_validation_error(request, error)
    else:
        messages.success(request, "課堂通報已取消。 / Class alert cancelled.")
    return redirect("tutoring:class_detail", pk=pk)


@login_required
@require_POST
def resolve_alert(request, alert_id):
    if request.user.role != Role.ADMIN:
        raise Http404
    try:
        alert = resolve_class_alert(alert_id=alert_id, admin=request.user, note=request.POST.get("note", ""))
    except (ValidationError, ObjectDoesNotExist) as error:
        _show_validation_error(request, error)
    else:
        AuditLog.record(
            actor=request.user,
            event_type="CLASS_ALERT_RESOLVED",
            description="課堂通報已紀錄 / Class alert logged",
            metadata={"alert_id": alert.pk},
        )
        messages.success(request, "課堂通報已標記為已紀錄。 / Class alert marked as logged.")
    return redirect(f"{reverse('accounts:dashboard')}#class-alerts")


@login_required
@require_POST
def incident_report(request, pk):
    _session_for_user(request.user, pk)
    form = IncidentReportForm(request.POST)
    if not form.is_valid():
        for errors in form.errors.values():
            for error in errors:
                messages.error(request, error)
        return redirect("tutoring:class_detail", pk=pk)
    try:
        report = submit_incident_report(
            session_id=pk,
            reporter=request.user,
            category=form.cleaned_data["category"],
            content=form.cleaned_data["content"],
        )
    except (ValidationError, ObjectDoesNotExist) as error:
        _show_validation_error(request, error)
    else:
        AuditLog.record(
            actor=request.user,
            event_type="INCIDENT_REPORT_SUBMITTED",
            description="送出異常回報 / Incident report submitted",
            metadata={"report_id": report.pk, "session_id": pk, "category": report.category},
        )
        messages.success(request, "異常回報已送出。 / Incident report submitted.")
    return redirect("tutoring:class_detail", pk=pk)


@login_required
@require_POST
def resolve_incident_report_view(request, report_id):
    if request.user.role != Role.ADMIN:
        raise Http404
    try:
        report = resolve_incident_report(
            report_id=report_id, admin=request.user, note=request.POST.get("note", "")
        )
    except (ValidationError, ObjectDoesNotExist) as error:
        _show_validation_error(request, error)
    else:
        AuditLog.record(
            actor=request.user,
            event_type="INCIDENT_REPORT_RESOLVED",
            description="異常回報已紀錄 / Incident report logged",
            metadata={"report_id": report.pk},
        )
        messages.success(request, "異常回報已標記為已紀錄。 / Incident report marked as logged.")
    return redirect(f"{reverse('accounts:dashboard')}#incident-reports")
