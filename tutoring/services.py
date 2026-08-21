from datetime import datetime, timedelta
from decimal import Decimal
import uuid

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.utils import timezone

from accounts.models import AuditLog, EducationLevel, PartnerProgram, Role, User

from .models import (
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
    TuteeProfile,
    TutorProfile,
    Attendance,
    ClassConfirmation,
    ClassAlert,
    ClassAlertReason,
    ClassAlertStatus,
    ClassDocument,
    ClassRecord,
    ClassSession,
    ClassSessionStatus,
    ConfirmationStatus,
    IncidentReport,
    IncidentReportCategory,
    IncidentReportStatus,
    MakeupReview,
    MakeupReviewStatus,
)


INVITATION_VALID_DAYS = 5
MAX_ACTIVE_TUTEES_PER_TUTOR = 2
MAX_PENDING_INVITATIONS_PER_USER = 3
ALLOWED_DURATIONS = {Decimal("0.5"), Decimal("1.0"), Decimal("1.5"), Decimal("2.0")}
MAX_WEEKLY_PAIRING_HOURS = Decimal("2.0")
MAX_SEMESTER_PAIRING_HOURS = Decimal("32.0")
MAX_SEMESTER_TUTOR_HOURS = Decimal("64.0")
MAX_MAKEUP_PER_TYPE = 5
PAIRING_AUTO_RELEASE_HOURS = 48

LEVEL_LABELS = {
    "UNKNOWN": "不知道 / Unknown",
    "N": "TOCFL N",
    "A1": "TOCFL A1",
    "A2": "TOCFL A2",
    "B1": "TOCFL B1",
    "B2": "TOCFL B2",
    "C1": "TOCFL C1",
    "C2": "TOCFL C2",
    **{f"HSK{level}": f"HSK {level}" for level in range(1, 10)},
}
LEARNING_DURATION_LABELS = {
    "LT_3_MONTHS": "3 個月以下 / Less than 3 months",
    "3_TO_6_MONTHS": "3 個月～半年 / 3–6 months",
    "6_TO_12_MONTHS": "半年～1 年 / 6–12 months",
    "1_TO_2_YEARS": "1～2 年 / 1–2 years",
    "GT_2_YEARS": "2 年以上 / More than 2 years",
}
SKILL_LABELS = {
    "LISTENING": "聽力 / Listening",
    "SPEAKING": "口說 / Speaking",
    "READING": "閱讀 / Reading",
    "WRITING": "寫作 / Writing",
}
DAY_LABELS = {
    "MON": "週一 / Mon",
    "TUE": "週二 / Tue",
    "WED": "週三 / Wed",
    "THU": "週四 / Thu",
    "FRI": "週五 / Fri",
    "SAT": "週六 / Sat",
    "SUN": "週日 / Sun",
}


def active_semester(program=None):
    """The currently running period (today within start/end) for a given partner program.

    `program=None` looks up the legacy shared period (Semester.program IS NULL) — the only
    kind that existed before per-program periods (2026-08), so this is still the right call
    for any pairing/user that isn't scoped to a specific program yet. When a real `program` is
    passed, a period scoped to that exact program takes priority; if none is currently running,
    this falls back to an active legacy shared period so programs without their own dedicated
    period yet keep working exactly as before.
    """
    today = timezone.localdate()
    current = Semester.objects.filter(is_active=True, starts_on__lte=today, ends_on__gte=today)
    if program is not None:
        specific = current.filter(program=program).order_by("starts_on").first()
        if specific:
            return specific
    return current.filter(program__isnull=True).order_by("starts_on").first()


def user_program(user):
    """The partner program a user is scoped to.

    Every Tutee has a program (required by RosterEntry.clean()). A Tutor only has an
    explicit one if they're on that program's own tutor roster (see
    tutor_can_serve_program() and MEETING_CHANGE_REQUIREMENTS_2026-08-04.md item 4) —
    an "ordinary" tutor with no roster program implicitly serves NTNU, so this resolves
    to the real NTNU PartnerProgram for them rather than returning bare None. Returning
    None there used to make active_semester(program=user_program(tutor)) silently look up
    the legacy shared period instead of an NTNU-scoped one, so an NTNU-specific semester
    an Admin just created would apply to NTNU tutees but not to ordinary NTNU tutors.
    """
    if user.role not in {Role.TUTEE, Role.TUTOR} or not user.roster_entry_id:
        return None
    program = user.roster_entry.program
    if program is not None or user.role == Role.TUTEE:
        return program
    return PartnerProgram.objects.filter(code="NTNU").first()


def tutor_can_serve_program(tutor, program):
    """Whether a tutor may see or pair with tutees belonging to `program`.

    Ordinary tutors (no program on their own roster entry) serve the default/legacy pool —
    today that's exactly the NTNU tutees, since every other tutee-facing program requires its
    own tutor roster. A tutor explicitly listed on a program's tutor roster (RosterEntry.program
    set on a TUTOR row, e.g. Maryland's course roster) may only serve that same program; for
    Maryland specifically they must also be a bachelor's student, since the language-exchange
    course is bachelor-only even if the roster entry were ever miskept (item 4).
    """
    roster_program = tutor.roster_entry.program if tutor.roster_entry_id else None
    if roster_program is None:
        return program is None or program.code == "NTNU"
    if program is None or roster_program.code != program.code:
        return False
    if roster_program.code == "MARYLAND" and tutor.roster_entry.education_level != EducationLevel.BACHELOR:
        return False
    return True


def export_users_for_program(program, role=None):
    """Users available to the Admin export for one partner program.

    Tutees belong to the program through their roster entry. Tutors use the same eligibility
    rule as matching, so an ordinary Tutor appears under NTNU while a program-specific Tutor
    appears only under that program. Returning a queryset keeps the export builders and audit
    count queries lazy and composable.
    """
    users = User.objects.exclude(role=Role.ADMIN).select_related(
        "roster_entry", "roster_entry__program"
    ).order_by("username")
    if role == Role.TUTEE:
        return users.filter(role=Role.TUTEE, roster_entry__program=program)

    tutors = users.filter(role=Role.TUTOR)
    tutor_ids = [tutor.pk for tutor in tutors if tutor_can_serve_program(tutor, program)]
    if role == Role.TUTOR:
        return users.filter(pk__in=tutor_ids)

    return users.filter(
        Q(pk__in=tutor_ids) | Q(role=Role.TUTEE, roster_entry__program=program)
    ).distinct()


def visible_class_document_programs(user):
    """Partner programs whose class documents `user` may see (item 5).

    Reuses the same eligibility rules already used for candidate browsing and invitations
    so "who can see documents" never drifts from "who belongs to this program": a Tutee's
    single program comes from their roster entry (user_program()); a Tutor's eligibility is
    checked against every program with the feature enabled via tutor_can_serve_program(),
    which also covers "ordinary tutors implicitly serve NTNU" and the Maryland bachelor's
    restriction — not just tutors with an explicit roster program.
    """
    if user.role == Role.TUTEE:
        program = user_program(user)
        return [program] if program and program.class_documents_enabled else []
    if user.role == Role.TUTOR:
        return [
            program for program in PartnerProgram.objects.filter(class_documents_enabled=True)
            if tutor_can_serve_program(user, program)
        ]
    return []


def visible_class_documents(user):
    programs = visible_class_document_programs(user)
    if not programs:
        return ClassDocument.objects.none()
    return ClassDocument.objects.filter(
        program__in=programs, is_active=True
    ).select_related("program", "semester")


def _six_months_before(value):
    """Return the same day six months earlier, clamped to that month's end."""
    import calendar

    month_index = value.year * 12 + value.month - 1 - 6
    year, month_zero_based = divmod(month_index, 12)
    month = month_zero_based + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def archive_expired_semesters(*, today=None):
    """Archive old settings while keeping linked classes and hour records."""
    today = today or timezone.localdate()
    cutoff = _six_months_before(today)
    return Semester.objects.filter(is_active=True, ends_on__lt=cutoff).update(is_active=False)


def synchronize_matching_state():
    now = timezone.now()
    expired_invitations = MatchingInvitation.objects.filter(
        status=InvitationStatus.PENDING, expires_at__lte=now
    ).update(
        status=InvitationStatus.EXPIRED, responded_at=now
    )
    auto_releases = process_pending_pairing_releases(now=now)
    archived_semesters = archive_expired_semesters(today=timezone.localdate())
    ending_pairing_ids = list(
        Pairing.objects.filter(
            status=PairingStatus.ACTIVE, semester__ends_on__lt=timezone.localdate()
        ).values_list("pk", flat=True)
    )
    ended_pairings = Pairing.objects.filter(pk__in=ending_pairing_ids).update(
        status=PairingStatus.ENDED, ended_at=now, end_reason="SEMESTER_END"
    )
    PairingReleaseRequest.objects.filter(
        pairing_id__in=ending_pairing_ids,
        status=PairingReleaseStatus.PENDING,
    ).update(
        status=PairingReleaseStatus.AUTO_APPROVED,
        reviewed_at=now,
        review_note="學期已結束，系統自動結束配對。 / Automatically ended with the semester.",
        updated_at=now,
    )
    return {
        "expired_invitations": expired_invitations,
        "ended_pairings": ended_pairings,
        "auto_releases": auto_releases,
        "archived_semesters": archived_semesters,
    }


def _cancel_unfinished_classes_for_pairing(*, pairing, actor, now):
    sessions = ClassSession.objects.select_for_update().filter(
        pairing=pairing,
        status=ClassSessionStatus.SCHEDULED,
    )
    cancelled = 0
    for session in sessions:
        if session.ends_at <= now:
            continue
        session.status = ClassSessionStatus.CANCELLED
        session.cancellation_reason = "配對已解除 / Pairing released"
        session.cancelled_by = actor
        session.cancelled_at = now
        session.save(
            update_fields=["status", "cancellation_reason", "cancelled_by", "cancelled_at", "updated_at"]
        )
        cancelled += 1
    return cancelled


def _end_pairing_for_release(*, release_request, actor, now):
    pairing = Pairing.objects.select_for_update().get(pk=release_request.pairing_id)
    if pairing.status != PairingStatus.ACTIVE:
        raise ValidationError("此配對已經結束。 / This pairing has already ended.")
    pairing.status = PairingStatus.ENDED
    pairing.ended_at = now
    pairing.end_reason = f"RELEASE:{release_request.reason}"
    pairing.save(update_fields=["status", "ended_at", "end_reason"])
    _cancel_unfinished_classes_for_pairing(pairing=pairing, actor=actor, now=now)
    return pairing


@transaction.atomic
def submit_pairing_release_request(*, pairing_id, requester, reason, note="", now=None):
    synchronize_matching_state()
    now = now or timezone.now()
    pairing = Pairing.objects.select_for_update().select_related("semester", "tutor", "tutee").get(pk=pairing_id)
    if pairing.status != PairingStatus.ACTIVE:
        raise ValidationError("只有進行中的配對可以申請解除。 / Only an active pairing can be released.")
    if requester.pk not in {pairing.tutor_id, pairing.tutee_id}:
        raise ValidationError("您不是這筆配對的參與者。 / You are not a participant in this pairing.")
    if reason not in PairingReleaseReason.values:
        raise ValidationError("請選擇解除原因。 / Select a release reason.")
    note = note.strip()
    if reason in {PairingReleaseReason.CONDUCT, PairingReleaseReason.OTHER} and not note:
        raise ValidationError("此原因必須補充說明。 / A note is required for this reason.")
    if PairingReleaseRequest.objects.filter(
        pairing=pairing, status=PairingReleaseStatus.PENDING
    ).exists():
        raise ValidationError("此配對已有等待處理的解除申請。 / A release request is already pending.")
    auto_resolve_at = (
        now + timedelta(hours=PAIRING_AUTO_RELEASE_HOURS)
        if reason in {
            PairingReleaseReason.NO_SHOW,
            PairingReleaseReason.UNREACHABLE,
            PairingReleaseReason.SCHEDULE_CONFLICT,
        }
        else None
    )
    release_request = PairingReleaseRequest(
        pairing=pairing,
        requested_by=requester,
        reason=reason,
        reason_note=note,
        auto_resolve_at=auto_resolve_at,
    )
    release_request.full_clean()
    release_request.save()
    AuditLog.record(
        actor=requester,
        target_user=pairing.tutee if requester.pk == pairing.tutor_id else pairing.tutor,
        event_type="PAIRING_RELEASE_REQUESTED",
        description="提出解除配對申請 / Pairing release requested",
        metadata={"pairing_id": pairing.pk, "request_id": release_request.pk, "reason": reason},
    )
    return release_request


@transaction.atomic
def review_pairing_release_request(*, request_id, admin, approve, note="", now=None):
    if admin.role != Role.ADMIN:
        raise ValidationError("只有管理員可以審核解除申請。 / Only an administrator may review releases.")
    now = now or timezone.now()
    release_request = PairingReleaseRequest.objects.select_for_update().select_related(
        "pairing__tutor", "pairing__tutee", "requested_by"
    ).get(pk=request_id)
    if release_request.status != PairingReleaseStatus.PENDING:
        raise ValidationError("此解除申請已完成處理。 / This release request has already been processed.")
    if approve:
        _end_pairing_for_release(release_request=release_request, actor=admin, now=now)
        release_request.status = PairingReleaseStatus.APPROVED
    else:
        release_request.status = PairingReleaseStatus.REJECTED
    release_request.reviewed_by = admin
    release_request.reviewed_at = now
    release_request.review_note = note.strip()
    release_request.save(
        update_fields=["status", "reviewed_by", "reviewed_at", "review_note", "updated_at"]
    )
    AuditLog.record(
        actor=admin,
        target_user=release_request.requested_by,
        event_type="PAIRING_RELEASE_APPROVED" if approve else "PAIRING_RELEASE_REJECTED",
        description=(
            "核准解除配對 / Pairing release approved"
            if approve
            else "未核准解除配對 / Pairing release rejected"
        ),
        metadata={"pairing_id": release_request.pairing_id, "request_id": release_request.pk},
    )
    return release_request


@transaction.atomic
def process_pending_pairing_releases(*, now=None):
    now = now or timezone.now()
    release_requests = PairingReleaseRequest.objects.select_for_update().select_related(
        "pairing__tutor", "pairing__tutee", "requested_by"
    ).filter(
        status=PairingReleaseStatus.PENDING,
        auto_resolve_at__isnull=False,
        auto_resolve_at__lte=now,
        pairing__status=PairingStatus.ACTIVE,
    )
    processed = 0
    for release_request in release_requests:
        _end_pairing_for_release(release_request=release_request, actor=release_request.requested_by, now=now)
        release_request.status = PairingReleaseStatus.AUTO_APPROVED
        release_request.reviewed_at = now
        release_request.review_note = "管理員 48 小時內未處理，系統依原因自動解除。 / Automatically released after 48 hours."
        release_request.save(update_fields=["status", "reviewed_at", "review_note", "updated_at"])
        AuditLog.record(
            actor=None,
            target_user=release_request.requested_by,
            event_type="PAIRING_RELEASE_AUTO_APPROVED",
            description="系統自動解除配對 / Pairing automatically released",
            metadata={"pairing_id": release_request.pairing_id, "request_id": release_request.pk},
        )
        processed += 1
    return processed


def _validate_matching_window(semester):
    today = timezone.localdate()
    if not semester or not semester.is_active:
        raise ValidationError("目前沒有開放配對的學期。 / Matching is not open for a semester.")
    if today < semester.starts_on:
        raise ValidationError("本學期尚未開放配對。 / Matching has not opened for this semester.")
    if today > semester.ends_on:
        raise ValidationError("本學期的配對期間已結束。 / The matching period has ended.")


def tutor_has_approved_qualification(tutor):
    return QualificationDocument.objects.filter(tutor=tutor, status=QualificationStatus.APPROVED).exists()


def tutor_has_capacity(tutor, semester):
    return Pairing.objects.filter(
        semester=semester, tutor=tutor, status=PairingStatus.ACTIVE
    ).count() < MAX_ACTIVE_TUTEES_PER_TUTOR


def _tutee_can_initiate_invitation(tutee):
    return bool(
        tutee.roster_entry
        and tutee.roster_entry.program_id
        and tutee.roster_entry.program.allow_tutee_initiate_invitation
    )


def _pending_invitation_count(user, semester):
    return MatchingInvitation.objects.filter(
        Q(tutor=user) | Q(tutee=user), semester=semester, status=InvitationStatus.PENDING
    ).count()


@transaction.atomic
def send_invitation(*, initiator, tutor_id, tutee_id):
    synchronize_matching_state()
    tutor = User.objects.select_for_update().get(pk=tutor_id, role=Role.TUTOR, is_active=True)
    tutee = User.objects.select_for_update().get(pk=tutee_id, role=Role.TUTEE, is_active=True)
    current = active_semester(program=user_program(tutee))
    semester = Semester.objects.select_for_update().filter(pk=current.pk).first() if current else None
    _validate_matching_window(semester)
    if initiator.pk not in {tutor.pk, tutee.pk}:
        raise ValidationError("您不是這筆邀請的參與者。 / You are not a participant in this invitation.")
    if initiator.pk == tutee.pk and not _tutee_can_initiate_invitation(tutee):
        raise ValidationError("此 Tutee 類別不能主動邀請 Tutor。 / This tutee type cannot initiate invitations.")
    if not tutor_can_serve_program(tutor, user_program(tutee)):
        raise ValidationError(
            "此 Tutor 不在該計畫的修課名單中，無法配對。 / This tutor is not on that program's course roster and cannot be matched."
        )
    if not tutor_has_approved_qualification(tutor):
        raise ValidationError("Tutor 尚未通過口語能力審查。 / The tutor's oral proficiency has not been approved.")
    if not tutor_has_capacity(tutor, semester):
        raise ValidationError("Tutor 本學期已有兩位 Tutee。 / The tutor already has two active tutees.")
    if Pairing.objects.filter(semester=semester, tutee=tutee, status=PairingStatus.ACTIVE).exists():
        raise ValidationError("Tutee 本學期已有 Tutor。 / The tutee already has an active tutor.")
    if Pairing.objects.filter(semester=semester, tutor=tutor, tutee=tutee).exists():
        raise ValidationError("本學期雙方已曾配對，無法再次配對。 / This pair cannot rematch in the same semester.")
    if MatchingInvitation.objects.filter(
        semester=semester, tutor=tutor, tutee=tutee, status=InvitationStatus.PENDING
    ).exists():
        raise ValidationError("雙方已有一筆等待回覆的邀請。 / A pending invitation already exists.")
    if _pending_invitation_count(tutor, semester) >= MAX_PENDING_INVITATIONS_PER_USER:
        raise ValidationError("此 Tutor 待回覆邀請已達上限。 / This tutor has reached the pending invitation limit.")
    if _pending_invitation_count(tutee, semester) >= MAX_PENDING_INVITATIONS_PER_USER:
        raise ValidationError("此 Tutee 待回覆邀請已達上限。 / This tutee has reached the pending invitation limit.")
    return MatchingInvitation.objects.create(
        semester=semester,
        tutor=tutor,
        tutee=tutee,
        initiated_by=initiator,
        expires_at=timezone.now() + timedelta(days=INVITATION_VALID_DAYS),
    )


@transaction.atomic
def respond_to_invitation(*, invitation_id, responder, accept):
    synchronize_matching_state()
    invitation = MatchingInvitation.objects.select_for_update().select_related(
        "semester", "tutor", "tutee"
    ).get(pk=invitation_id)
    if invitation.status != InvitationStatus.PENDING or invitation.expires_at <= timezone.now():
        raise ValidationError("此邀請已無法回覆。 / This invitation can no longer be answered.")
    recipient_id = invitation.tutee_id if invitation.initiated_by_id == invitation.tutor_id else invitation.tutor_id
    if responder.pk != recipient_id:
        raise ValidationError("只有收件人可以回覆此邀請。 / Only the recipient may answer this invitation.")
    now = timezone.now()
    if not accept:
        invitation.status = InvitationStatus.REJECTED
        invitation.responded_at = now
        invitation.save(update_fields=["status", "responded_at", "updated_at"])
        return None
    _validate_matching_window(invitation.semester)
    list(User.objects.select_for_update().filter(pk__in=[invitation.tutor_id, invitation.tutee_id]))
    if not tutor_has_approved_qualification(invitation.tutor):
        raise ValidationError("Tutor 尚未通過口語能力審查。 / The tutor's oral proficiency has not been approved.")
    if not tutor_has_capacity(invitation.tutor, invitation.semester):
        raise ValidationError("Tutor 的配對名額已滿。 / The tutor no longer has matching capacity.")
    if Pairing.objects.filter(
        semester=invitation.semester, tutee=invitation.tutee, status=PairingStatus.ACTIVE
    ).exists():
        raise ValidationError("Tutee 已和其他 Tutor 配對。 / The tutee is already paired with another tutor.")
    if Pairing.objects.filter(
        semester=invitation.semester, tutor=invitation.tutor, tutee=invitation.tutee
    ).exists():
        raise ValidationError("本學期雙方已曾配對。 / This pair has already matched this semester.")
    pairing = Pairing.objects.create(
        semester=invitation.semester,
        tutor=invitation.tutor,
        tutee=invitation.tutee,
        invitation=invitation,
    )
    invitation.status = InvitationStatus.ACCEPTED
    invitation.responded_at = now
    invitation.save(update_fields=["status", "responded_at", "updated_at"])
    MatchingInvitation.objects.filter(
        semester=invitation.semester,
        tutee=invitation.tutee,
        status=InvitationStatus.PENDING,
    ).exclude(pk=invitation.pk).update(status=InvitationStatus.CANCELLED, responded_at=now)
    if not tutor_has_capacity(invitation.tutor, invitation.semester):
        MatchingInvitation.objects.filter(
            semester=invitation.semester,
            tutor=invitation.tutor,
            status=InvitationStatus.PENDING,
        ).exclude(pk=invitation.pk).update(status=InvitationStatus.CANCELLED, responded_at=now)
    return pairing


@transaction.atomic
def cancel_invitation(*, invitation_id, actor):
    synchronize_matching_state()
    invitation = MatchingInvitation.objects.select_for_update().get(pk=invitation_id)
    if invitation.initiated_by_id != actor.pk:
        raise ValidationError("只有發起人可以取消邀請。 / Only the initiator may cancel the invitation.")
    if invitation.status != InvitationStatus.PENDING:
        raise ValidationError("此邀請已無法取消。 / This invitation can no longer be cancelled.")
    invitation.status = InvitationStatus.CANCELLED
    invitation.responded_at = timezone.now()
    invitation.save(update_fields=["status", "responded_at", "updated_at"])


# One extra active tutee, admin-assigned pairings only, and never for NTNU (item 12): the normal
# self-service invite/accept flow (tutor_has_capacity) is untouched and still caps every tutor at
# MAX_ACTIVE_TUTEES_PER_TUTOR regardless of program.
ADMIN_PAIRING_EXTRA_CAPACITY = 1


def tutor_has_admin_pairing_capacity(tutor, semester, program):
    """Whether Admin may create one more active pairing for this tutor in this semester.

    NTNU keeps the standard cap even through this path — the extra slot only exists for
    non-NTNU partner programs, since NTNU should never be over-matched by this feature
    (MEETING_CHANGE_REQUIREMENTS_2026-08-04.md item 12).
    """
    count = Pairing.objects.filter(semester=semester, tutor=tutor, status=PairingStatus.ACTIVE).count()
    limit = MAX_ACTIVE_TUTEES_PER_TUTOR
    if program is not None and program.code != "NTNU":
        limit += ADMIN_PAIRING_EXTRA_CAPACITY
    return count < limit


@transaction.atomic
def create_admin_pairing(*, admin, tutor_id, tutee_id, semester_id):
    """Admin builds a pairing directly, skipping the invitation handshake entirely (item 12).

    First-stage scope: no extra reason field, no new per-program hour caps (those still fall
    back to the existing weekly/semester/tutor limits — see MAX_WEEKLY_PAIRING_HOURS etc.).
    The only capacity change is the one extra non-NTNU slot from
    tutor_has_admin_pairing_capacity(); every other eligibility rule (role, active status,
    program roster, existing active tutor, no repeat pairing) is identical to the normal flow so
    this can't be used to sneak in a pairing that browsing/inviting would have refused anyway.
    """
    if admin.role != Role.ADMIN:
        raise ValidationError("只有管理員可以使用此功能。 / Only administrators may use this feature.")
    synchronize_matching_state()
    tutor = User.objects.select_for_update().get(pk=tutor_id, role=Role.TUTOR, is_active=True)
    tutee = User.objects.select_for_update().get(pk=tutee_id, role=Role.TUTEE, is_active=True)
    semester = Semester.objects.select_for_update().get(pk=semester_id)
    tutee_program = user_program(tutee)
    if not tutor_can_serve_program(tutor, tutee_program):
        raise ValidationError(
            "此 Tutor 不在該計畫的修課名單中，無法配對。 / This tutor is not on that program's course roster and cannot be matched."
        )
    if not tutor_has_approved_qualification(tutor):
        raise ValidationError("Tutor 尚未通過口語能力審查。 / The tutor's oral proficiency has not been approved.")
    if not tutor_has_admin_pairing_capacity(tutor, semester, tutee_program):
        raise ValidationError("此 Tutor 本學期配對名額已滿。 / The tutor has no remaining matching capacity this semester.")
    if Pairing.objects.filter(semester=semester, tutee=tutee, status=PairingStatus.ACTIVE).exists():
        raise ValidationError("Tutee 本學期已有 Tutor。 / The tutee already has an active tutor.")
    if Pairing.objects.filter(semester=semester, tutor=tutor, tutee=tutee).exists():
        raise ValidationError("本學期雙方已曾配對，無法再次配對。 / This pair cannot rematch in the same semester.")
    pairing = Pairing(semester=semester, tutor=tutor, tutee=tutee, created_by=admin)
    pairing.full_clean()
    pairing.save()
    AuditLog.record(
        actor=admin,
        target_user=tutee,
        event_type="ADMIN_PAIRING_CREATED",
        description="Admin 手動建立配對 / Pairing created directly by admin",
        metadata={"pairing_id": pairing.pk, "tutor": tutor.username, "tutee": tutee.username, "semester_id": semester.pk},
    )
    return pairing


def anonymous_tutee_candidates(*, semester, tutor, filters=None):
    if not semester:
        return []
    filters = filters or {}
    blocked_tutees = Pairing.objects.filter(semester=semester).filter(
        Q(status=PairingStatus.ACTIVE) | Q(tutor=tutor)
    ).values_list("tutee_id", flat=True)
    queryset = TuteeProfile.objects.exclude(tutee_id__in=blocked_tutees).order_by("tutee_id")
    tutor_roster_program = tutor.roster_entry.program if tutor.roster_entry_id else None
    if tutor_roster_program is None:
        queryset = queryset.filter(tutee__roster_entry__program__code="NTNU")
    elif (
        tutor_roster_program.code == "MARYLAND"
        and tutor.roster_entry.education_level != EducationLevel.BACHELOR
    ):
        queryset = queryset.none()
    else:
        queryset = queryset.filter(tutee__roster_entry__program=tutor_roster_program)
    gender = filters.get("gender")
    if gender:
        queryset = queryset.filter(gender=gender)
    overall_level = filters.get("overall_level")
    if overall_level:
        queryset = queryset.filter(overall_level=overall_level)
    native_language = filters.get("native_language")
    if native_language:
        queryset = queryset.filter(native_language=native_language)
    target_skills = filters.get("target_skills") or []
    days = filters.get("days") or []
    time_slots = filters.get("time_slots") or []
    profiles = [
        profile for profile in queryset
        if (not target_skills or all(skill in profile.target_skills for skill in target_skills))
        and (not days or any(day in profile.preferred_days for day in days))
        and (not time_slots or any(slot in profile.preferred_time_slots for slot in time_slots))
    ]
    return [anonymous_tutee_profile(profile) for profile in profiles]


def anonymous_tutee_profile(profile):
    return {
        "user_id": profile.tutee_id,
        "gender": profile.get_gender_display(),
        "native_language": profile.native_language,
        "nationality": profile.nationality,
        "overall_level": LEVEL_LABELS.get(profile.overall_level, profile.overall_level),
        "target_skills": [SKILL_LABELS.get(skill, skill) for skill in profile.target_skills],
        "learning_duration": LEARNING_DURATION_LABELS.get(profile.learning_duration, profile.learning_duration),
        "notes": profile.skills_to_improve,
        "days": [DAY_LABELS.get(day, day) for day in profile.preferred_days],
        "time_slots": profile.preferred_time_slots,
    }


def anonymous_tutor_candidates(*, semester, tutee, filters=None):
    if not semester:
        return []
    filters = filters or {}
    previous_tutors = Pairing.objects.filter(semester=semester, tutee=tutee).values_list("tutor_id", flat=True)
    full_tutors = Pairing.objects.filter(semester=semester, status=PairingStatus.ACTIVE).values("tutor_id").annotate(
        total=Count("id")
    ).filter(total__gte=MAX_ACTIVE_TUTEES_PER_TUTOR).values_list("tutor_id", flat=True)
    approved = QualificationDocument.objects.filter(status=QualificationStatus.APPROVED).values_list(
        "tutor_id", flat=True
    )
    queryset = TutorProfile.objects.filter(tutor_id__in=approved).exclude(
        Q(tutor_id__in=previous_tutors) | Q(tutor_id__in=full_tutors)
    ).order_by("tutor_id")
    tutee_program = tutee.roster_entry.program if tutee.roster_entry_id else None
    if tutee_program and tutee_program.code == "MARYLAND":
        queryset = queryset.filter(
            tutor__roster_entry__program__code="MARYLAND",
            tutor__roster_entry__education_level=EducationLevel.BACHELOR,
        )
    elif tutee_program and tutee_program.code != "NTNU":
        queryset = queryset.filter(tutor__roster_entry__program=tutee_program)
    else:
        queryset = queryset.filter(
            Q(tutor__roster_entry__program__isnull=True) | Q(tutor__roster_entry__program__code="NTNU")
        )
    gender = filters.get("gender")
    if gender:
        queryset = queryset.filter(gender=gender)
    native_language = filters.get("native_language")
    if native_language:
        queryset = queryset.filter(native_language=native_language)
    days = filters.get("days") or []
    time_slots = filters.get("time_slots") or []
    profiles = [
        profile for profile in queryset
        if (not days or any(day in profile.available_days for day in days))
        and (not time_slots or any(slot in profile.available_time_slots for slot in time_slots))
    ]
    return [anonymous_tutor_profile(profile) for profile in profiles]


def anonymous_tutor_profile(profile):
    return {
        "user_id": profile.tutor_id,
        "gender": profile.get_gender_display(),
        "native_language": profile.native_language,
        "nationality": profile.nationality,
        "levels": [
            {"label": "聽力教學", "label_en": "Listening", "score": profile.level_listening},
            {"label": "口說教學", "label_en": "Speaking", "score": profile.level_speaking},
            {"label": "閱讀教學", "label_en": "Reading", "score": profile.level_reading},
            {"label": "寫作教學", "label_en": "Writing", "score": profile.level_writing},
        ],
        "notes": profile.teaching_notes,
        "days": [DAY_LABELS.get(day, day) for day in profile.available_days],
        "time_slots": profile.available_time_slots,
    }


def annotate_conversation_summaries(pairings, *, viewer):
    """Attach last_message/last_activity_at/unread_count to each pairing, sorted by most recent activity."""
    pairings = list(pairings)
    for pairing in pairings:
        last_message = pairing.messages.select_related("sender").order_by("-created_at", "-pk").first()
        pairing.last_message = last_message
        pairing.last_activity_at = last_message.created_at if last_message else pairing.started_at
        pairing.unread_count = pairing.messages.filter(read_at__isnull=True).exclude(sender=viewer).count()
    return sorted(pairings, key=lambda pairing: pairing.last_activity_at, reverse=True)


def _participants(session):
    return {session.pairing.tutor_id, session.pairing.tutee_id}


def _counterpart(session, user):
    if user.pk == session.pairing.tutor_id:
        return session.pairing.tutee
    if user.pk == session.pairing.tutee_id:
        return session.pairing.tutor
    raise ValidationError("您不是這堂課的參與者。 / You are not a participant in this class.")


def _scheduled_hours(queryset):
    return queryset.exclude(status=ClassSessionStatus.CANCELLED).aggregate(total=Sum("duration"))["total"] or Decimal("0")


def _validate_schedule_quota(*, pairing, class_date, duration, exclude_session=None, exclude_session_ids=None):
    sessions = ClassSession.objects.select_for_update().exclude(status=ClassSessionStatus.CANCELLED)
    if exclude_session:
        sessions = sessions.exclude(pk=exclude_session.pk)
    if exclude_session_ids:
        sessions = sessions.exclude(pk__in=exclude_session_ids)
    week_start = class_date - timedelta(days=class_date.weekday())
    week_end = week_start + timedelta(days=6)
    if _scheduled_hours(sessions.filter(pairing=pairing, class_date__range=(week_start, week_end))) + duration > MAX_WEEKLY_PAIRING_HOURS:
        raise ValidationError("同一組每週排課不可超過 2 小時。 / A pair may schedule at most 2 hours per week.")
    if _scheduled_hours(sessions.filter(pairing=pairing, pairing__semester=pairing.semester)) + duration > MAX_SEMESTER_PAIRING_HOURS:
        raise ValidationError("同一組每學期排課不可超過 32 小時。 / A pair may schedule at most 32 hours per semester.")
    if _scheduled_hours(sessions.filter(pairing__tutor=pairing.tutor, pairing__semester=pairing.semester)) + duration > MAX_SEMESTER_TUTOR_HOURS:
        raise ValidationError("老師每學期排課不可超過 64 小時。 / A teacher may schedule at most 64 hours per semester.")


@transaction.atomic
def schedule_classes(*, tutor, pairing, class_date, start_time, duration, repeat_until=None, now=None):
    pairing = Pairing.objects.select_for_update().select_related("semester", "tutor", "tutee").get(pk=pairing.pk)
    if tutor.pk != pairing.tutor_id or pairing.status != PairingStatus.ACTIVE:
        raise ValidationError("只有目前配對的老師可以排課。 / Only the currently paired teacher may schedule classes.")
    duration = Decimal(str(duration))
    now = now or timezone.now()
    if duration not in ALLOWED_DURATIONS:
        raise ValidationError("課程時數須為 0.5、1、1.5 或 2 小時。 / Duration must be 0.5, 1, 1.5, or 2 hours.")
    if start_time.minute % 5 != 0 or start_time.second:
        raise ValidationError("開始時間請以 5 分鐘為單位。 / Start time must use five-minute increments.")
    if class_date < pairing.semester.starts_on or class_date > pairing.semester.ends_on:
        raise ValidationError("上課日期須在本學期內。 / The class date must be within the semester.")
    first_start = timezone.make_aware(datetime.combine(class_date, start_time), timezone.get_current_timezone())
    if first_start <= now:
        raise ValidationError("新課程必須安排在未來。 / A new class must be scheduled in the future.")
    if repeat_until and repeat_until < class_date:
        raise ValidationError("重複結束日不可早於第一堂課。 / Repeat end cannot precede the first class.")
    final_date = min(repeat_until or class_date, pairing.semester.ends_on)
    dates = []
    cursor = class_date
    while cursor <= final_date:
        dates.append(cursor)
        cursor += timedelta(days=7)
    group = uuid.uuid4() if len(dates) > 1 else None
    created = []
    for date_value in dates:
        _validate_schedule_quota(pairing=pairing, class_date=date_value, duration=duration)
        session = ClassSession(
            pairing=pairing,
            class_date=date_value,
            start_time=start_time,
            duration=duration,
            recurrence_group=group,
            created_by=tutor,
        )
        session.full_clean()
        session.save()
        created.append(session)
    return created


@transaction.atomic
def cancel_class(*, session_id, actor, reason):
    session = ClassSession.objects.select_for_update().select_related("pairing__semester").get(pk=session_id)
    if actor.pk != session.pairing.tutor_id:
        raise ValidationError("只有老師可以取消課程。 / Only the teacher may cancel a class.")
    if session.status == ClassSessionStatus.CANCELLED:
        raise ValidationError("此課程已取消。 / This class is already cancelled.")
    now = timezone.now()
    if session.attendances.exists() or session.class_records.exists():
        raise ValidationError("已有簽到或課堂紀錄，請洽管理員處理。 / Contact an administrator because activity already exists.")
    if now > session.ends_at + timedelta(days=21):
        raise ValidationError("課程結束超過三週，無法取消。 / A class cannot be cancelled more than three weeks later.")
    session.status = ClassSessionStatus.CANCELLED
    session.cancellation_reason = reason.strip()
    session.cancelled_by = actor
    session.cancelled_at = now
    session.save(update_fields=["status", "cancellation_reason", "cancelled_by", "cancelled_at", "updated_at"])
    return session


@transaction.atomic
def reschedule_class(*, session_id, tutor, class_date, start_time, duration, scope="single", now=None):
    now = now or timezone.now()
    session = ClassSession.objects.select_for_update().select_related("pairing__semester", "pairing__tutor").get(pk=session_id)
    if tutor.pk != session.pairing.tutor_id or session.status != ClassSessionStatus.SCHEDULED:
        raise ValidationError("只有配對老師可以修改未取消的課程。 / Only the paired teacher may edit a scheduled class.")
    if session.attendances.exists() or session.class_records.exists():
        raise ValidationError("已有簽到或課堂紀錄，請洽管理員處理。 / Contact an administrator because activity already exists.")
    if now > session.ends_at + timedelta(days=21):
        raise ValidationError("課程結束超過三週，無法修改。 / A class cannot be edited more than three weeks later.")
    duration = Decimal(str(duration))
    if duration not in ALLOWED_DURATIONS or start_time.minute % 5 != 0 or start_time.second:
        raise ValidationError("請選擇有效時數，開始時間須以 5 分鐘為單位。 / Select a valid duration and a start time in five-minute increments.")
    new_start = timezone.make_aware(datetime.combine(class_date, start_time), timezone.get_current_timezone())
    if new_start <= now:
        raise ValidationError("修改後的課程必須安排在未來。 / A rescheduled class must be in the future.")
    targets = [session]
    if scope == "following" and session.recurrence_group:
        targets = list(
            ClassSession.objects.select_for_update().filter(
                recurrence_group=session.recurrence_group,
                class_date__gte=session.class_date,
                status=ClassSessionStatus.SCHEDULED,
            ).order_by("class_date", "start_time")
        )
        if any(target.attendances.exists() or target.class_records.exists() for target in targets):
            raise ValidationError("後續課程已有活動紀錄，請改為只修改這堂。 / A later class already has activity; edit this class only.")
    target_ids = [target.pk for target in targets]
    day_shift = class_date - session.class_date
    updated = []
    for target in targets:
        target_date = target.class_date + day_shift
        if target_date > target.pairing.semester.ends_on or target_date < target.pairing.semester.starts_on:
            raise ValidationError("修改後的日期超出本學期。 / A changed date falls outside the semester.")
        _validate_schedule_quota(
            pairing=target.pairing,
            class_date=target_date,
            duration=duration,
            exclude_session_ids=target_ids,
        )
        target.class_date = target_date
        target.start_time = start_time
        target.duration = duration
        target.full_clean()
        target.save(update_fields=["class_date", "start_time", "duration", "updated_at"])
        updated.append(target)
        target_ids.remove(target.pk)
    return updated


def _makeup_count(*, user, semester, model):
    return model.objects.filter(
        **{"participant" if model is Attendance else "author": user},
        session__pairing__semester=semester,
        is_makeup=True,
    ).count()


@transaction.atomic
def check_in(*, session_id, participant, reason="", now=None):
    now = now or timezone.now()
    session = ClassSession.objects.select_for_update().select_related("pairing__semester", "pairing__tutor", "pairing__tutee").get(pk=session_id)
    _counterpart(session, participant)
    if session.status != ClassSessionStatus.SCHEDULED:
        raise ValidationError("已取消的課程無法簽到。 / A cancelled class cannot be checked into.")
    if Attendance.objects.filter(session=session, participant=participant).exists():
        raise ValidationError("您已完成簽到。 / You have already checked in.")
    if now < session.starts_at - timedelta(minutes=10):
        raise ValidationError("上課前 10 分鐘才開放簽到。 / Check-in opens 10 minutes before class.")
    if now > session.pairing.semester.makeup_deadline_at:
        raise ValidationError("已超過補簽到截止時間。 / The makeup check-in deadline has passed.")
    is_makeup = now > session.ends_at + timedelta(minutes=30)
    if is_makeup:
        if not reason.strip():
            raise ValidationError("補簽到請填寫原因。 / A reason is required for makeup check-in.")
        if _makeup_count(user=participant, semester=session.pairing.semester, model=Attendance) >= MAX_MAKEUP_PER_TYPE:
            raise ValidationError("本學期補簽到已達 5 次上限。 / The semester limit of five makeup check-ins has been reached.")
    attendance = Attendance.objects.create(
        session=session, participant=participant, signed_at=now, is_makeup=is_makeup, makeup_reason=reason.strip()
    )
    if is_makeup:
        MakeupReview.objects.get_or_create(session=session)
    return attendance


@transaction.atomic
def submit_class_record(*, session_id, author, data, reason="", now=None):
    now = now or timezone.now()
    session = ClassSession.objects.select_for_update().select_related("pairing__semester", "pairing__tutor", "pairing__tutee").get(pk=session_id)
    _counterpart(session, author)
    if session.status != ClassSessionStatus.SCHEDULED:
        raise ValidationError("已取消的課程無法提交紀錄。 / A cancelled class cannot receive records.")
    if now < session.starts_at:
        raise ValidationError("課程開始後才可提交課堂紀錄。 / Class records open when class begins.")
    existing = ClassRecord.objects.filter(session=session, author=author).first()
    is_makeup = now > session.ends_at + timedelta(hours=24)
    if now > session.pairing.semester.makeup_deadline_at:
        raise ValidationError("已超過補課堂紀錄截止時間。 / The makeup record deadline has passed.")
    if is_makeup and not existing:
        if not reason.strip():
            raise ValidationError("補課堂紀錄請填寫原因。 / A reason is required for a makeup record.")
        if _makeup_count(user=author, semester=session.pairing.semester, model=ClassRecord) >= MAX_MAKEUP_PER_TYPE:
            raise ValidationError("本學期補課堂紀錄已達 5 次上限。 / The semester limit of five makeup records has been reached.")
    record, _ = ClassRecord.objects.update_or_create(
        session=session,
        author=author,
        defaults={**data, "is_makeup": existing.is_makeup if existing else is_makeup, "makeup_reason": existing.makeup_reason if existing else reason.strip()},
    )
    if record.is_makeup:
        review, _ = MakeupReview.objects.get_or_create(session=session)
        if review.status in {MakeupReviewStatus.APPROVED, MakeupReviewStatus.REJECTED}:
            review.status = MakeupReviewStatus.WAITING
            review.reviewed_by = None
            review.review_note = ""
            review.reviewed_at = None
            review.save(update_fields=["status", "reviewed_by", "review_note", "reviewed_at", "updated_at"])
    ClassConfirmation.objects.filter(session=session, subject=author).delete()
    return record


def _sync_makeup_review(session):
    has_makeup = session.attendances.filter(is_makeup=True).exists() or session.class_records.filter(is_makeup=True).exists()
    if not has_makeup:
        return
    review, _ = MakeupReview.objects.get_or_create(session=session)
    confirmed = session.confirmations.filter(
        status=ConfirmationStatus.CONFIRMED, attendance_confirmed=True, record_confirmed=True
    ).count() == 2
    target = MakeupReviewStatus.PENDING if confirmed else MakeupReviewStatus.WAITING
    if review.status not in {MakeupReviewStatus.APPROVED, MakeupReviewStatus.REJECTED} and review.status != target:
        review.status = target
        review.save(update_fields=["status", "updated_at"])


@transaction.atomic
def confirm_counterpart(*, session_id, reviewer, status, note=""):
    session = ClassSession.objects.select_for_update().select_related("pairing__tutor", "pairing__tutee").get(pk=session_id)
    subject = _counterpart(session, reviewer)
    if status not in ConfirmationStatus.values:
        raise ValidationError("確認狀態不正確。 / Invalid confirmation status.")
    if not Attendance.objects.filter(session=session, participant=subject).exists() or not ClassRecord.objects.filter(session=session, author=subject).exists():
        raise ValidationError("對方尚未完成簽到與課堂紀錄。 / The other participant has not completed attendance and record.")
    if status != ConfirmationStatus.CONFIRMED and not note.strip():
        raise ValidationError("請說明需要修改或回報的問題。 / Please describe the revision or issue.")
    confirmation, _ = ClassConfirmation.objects.update_or_create(
        session=session,
        reviewer=reviewer,
        defaults={
            "subject": subject,
            "attendance_confirmed": status == ConfirmationStatus.CONFIRMED,
            "record_confirmed": status == ConfirmationStatus.CONFIRMED,
            "status": status,
            "note": note.strip(),
        },
    )
    _sync_makeup_review(session)
    return confirmation


def class_is_valid(session):
    if session.status != ClassSessionStatus.SCHEDULED:
        return False
    if session.attendances.count() != 2 or session.class_records.count() != 2:
        return False
    if session.confirmations.filter(
        status=ConfirmationStatus.CONFIRMED, attendance_confirmed=True, record_confirmed=True
    ).count() != 2:
        return False
    has_makeup = session.attendances.filter(is_makeup=True).exists() or session.class_records.filter(is_makeup=True).exists()
    return not has_makeup or (
        hasattr(session, "makeup_review") and session.makeup_review.status == MakeupReviewStatus.APPROVED
    )


@transaction.atomic
def review_makeup(*, session_id, admin, approve, note=""):
    if admin.role != Role.ADMIN:
        raise ValidationError("只有管理員可以審核補登。 / Only administrators may review makeup entries.")
    review = MakeupReview.objects.select_for_update().select_related("session").get(session_id=session_id)
    if review.status != MakeupReviewStatus.PENDING:
        raise ValidationError("此補登尚未進入可審核狀態。 / This makeup entry is not ready for review.")
    review.status = MakeupReviewStatus.APPROVED if approve else MakeupReviewStatus.REJECTED
    review.reviewed_by = admin
    review.review_note = note.strip()
    review.reviewed_at = timezone.now()
    review.save(update_fields=["status", "reviewed_by", "review_note", "reviewed_at", "updated_at"])
    return review


@transaction.atomic
def report_class_alert(*, session_id, reporter, reason, note="", now=None):
    now = now or timezone.now()
    session = ClassSession.objects.select_for_update().select_related(
        "pairing__tutor", "pairing__tutee"
    ).get(pk=session_id)
    subject = _counterpart(session, reporter)
    if session.status != ClassSessionStatus.SCHEDULED:
        raise ValidationError("已取消的課程無法通報。 / A cancelled class cannot be reported.")
    if reason not in ClassAlertReason.values:
        raise ValidationError("請選擇通報原因。 / Select an alert reason.")
    if now < session.starts_at or now > session.ends_at:
        raise ValidationError("課堂通報僅於上課時間內開放。 / Class alerts are available only during class time.")
    if ClassAlert.objects.filter(session=session, reporter=reporter, status=ClassAlertStatus.ACTIVE).exists():
        raise ValidationError("您已有一筆待處理的課堂通報。 / You already have an active class alert.")
    if reason == ClassAlertReason.OTHER and not note.strip():
        raise ValidationError("選擇其他緊急狀況時請填寫說明。 / Add a note when selecting another urgent issue.")
    return ClassAlert.objects.create(
        session=session, reporter=reporter, subject=subject, reason=reason, note=note.strip()
    )


@transaction.atomic
def cancel_class_alert(*, alert_id, reporter):
    alert = ClassAlert.objects.select_for_update().get(pk=alert_id)
    if alert.reporter_id != reporter.pk or alert.status != ClassAlertStatus.ACTIVE:
        raise ValidationError("此課堂通報無法取消。 / This class alert cannot be cancelled.")
    alert.status = ClassAlertStatus.CANCELLED
    alert.cancelled_at = timezone.now()
    alert.save(update_fields=["status", "cancelled_at"])
    return alert


@transaction.atomic
def resolve_class_alert(*, alert_id, admin, note=""):
    if admin.role != Role.ADMIN:
        raise ValidationError("只有管理員可以處理課堂通報。 / Only administrators may resolve class alerts.")
    alert = ClassAlert.objects.select_for_update().get(pk=alert_id)
    if alert.status != ClassAlertStatus.ACTIVE:
        raise ValidationError("此課堂通報已無法標記為已處理。 / This class alert can no longer be resolved.")
    alert.status = ClassAlertStatus.RESOLVED
    alert.resolved_by = admin
    alert.resolved_at = timezone.now()
    alert.resolution_note = note.strip()
    alert.save(update_fields=["status", "resolved_by", "resolved_at", "resolution_note"])
    return alert


@transaction.atomic
def submit_incident_report(*, session_id, reporter, category, content):
    session = ClassSession.objects.select_for_update().select_related(
        "pairing__tutor", "pairing__tutee"
    ).get(pk=session_id)
    _counterpart(session, reporter)
    if category not in IncidentReportCategory.values:
        raise ValidationError("請選擇回報分類。 / Select a report category.")
    content = content.strip()
    if not content:
        raise ValidationError("請填寫回報內容。 / Report content is required.")
    return IncidentReport.objects.create(
        session=session, reporter=reporter, category=category, content=content
    )


@transaction.atomic
def resolve_incident_report(*, report_id, admin, note=""):
    if admin.role != Role.ADMIN:
        raise ValidationError("只有管理員可以處理異常回報。 / Only administrators may resolve incident reports.")
    report = IncidentReport.objects.select_for_update().get(pk=report_id)
    if report.status != IncidentReportStatus.PENDING:
        raise ValidationError("此異常回報已處理過。 / This incident report has already been resolved.")
    report.status = IncidentReportStatus.RESOLVED
    report.resolved_by = admin
    report.resolved_at = timezone.now()
    report.resolution_note = note.strip()
    report.save(update_fields=["status", "resolved_by", "resolved_at", "resolution_note"])
    return report
