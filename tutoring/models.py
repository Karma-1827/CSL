from datetime import datetime, time, timedelta
from pathlib import Path

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone

from accounts.models import PartnerProgram, Role, User


def _validate_upload(upload, *, max_bytes, size_label):
    allowed = {".pdf", ".jpg", ".jpeg", ".png"}
    extension = Path(upload.name).suffix.lower()
    if extension not in allowed:
        raise ValidationError("僅接受 PDF、JPG、PNG。 / Only PDF, JPG, and PNG files are accepted.")
    if upload.size > max_bytes:
        raise ValidationError(f"檔案不可超過 {size_label}。 / File size must not exceed {size_label}.")


def validate_qualification_file(upload):
    _validate_upload(upload, max_bytes=1_000_000, size_label="1 MB")


def validate_class_record_attachment(upload):
    _validate_upload(upload, max_bytes=500_000, size_label="500 KB")


class QualificationStatus(models.TextChoices):
    NOT_SUBMITTED = "NOT_SUBMITTED", "未提交 / Not submitted"
    PENDING = "PENDING", "待審核 / Pending review"
    APPROVED = "APPROVED", "已通過 / Approved"
    REJECTED = "REJECTED", "需補件 / Revision required"


class QualificationDocument(models.Model):
    tutor = models.OneToOneField(User, on_delete=models.CASCADE, related_name="qualification")
    file = models.FileField(
        "口語能力證明 / Oral proficiency document",
        upload_to="qualifications/%Y/%m/",
        validators=[validate_qualification_file],
    )
    original_filename = models.CharField(max_length=255)
    status = models.CharField(max_length=16, choices=QualificationStatus.choices, default=QualificationStatus.PENDING)
    review_note = models.TextField("審核備註 / Review note", blank=True)
    reviewed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="reviewed_qualifications"
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        verbose_name = "口語能力證明 / Oral proficiency document"
        verbose_name_plural = "口語能力證明 / Oral proficiency documents"

    def clean(self):
        if self.tutor_id and self.tutor.role != Role.TUTOR:
            raise ValidationError("只有 Tutor 可以提交口語能力證明。 / Only tutors may submit oral proficiency documents.")


class Semester(models.Model):
    name_zh = models.CharField("學期名稱 / Semester name", max_length=80)
    name_en = models.CharField("英文名稱 / English name", max_length=100)
    starts_on = models.DateField("開始日期 / Start date")
    ends_on = models.DateField("結束日期 / End date")
    is_active = models.BooleanField("啟用 / Enabled", default=True)

    class Meta:
        ordering = ["-starts_on"]
        verbose_name = "學期 / Semester"
        verbose_name_plural = "學期 / Semesters"
        constraints = []

    def clean(self):
        if self.starts_on and self.ends_on and self.starts_on > self.ends_on:
            raise ValidationError("學期結束日不可早於開始日。 / End date cannot be before start date.")
        if self.is_active and self.starts_on and self.ends_on:
            overlap = Semester.objects.filter(
                is_active=True, starts_on__lte=self.ends_on, ends_on__gte=self.starts_on
            ).exclude(pk=self.pk)
            if overlap.exists():
                raise ValidationError("啟用中的學期日期不可重疊。 / Enabled semester dates cannot overlap.")
            today = timezone.localdate()
            enabled_non_past = Semester.objects.filter(is_active=True, ends_on__gte=today).exclude(pk=self.pk).count()
            if self.ends_on >= today and enabled_non_past >= 3:
                raise ValidationError("目前與未來最多設定三個學期。 / Configure at most three current and future semesters.")

    @property
    def lifecycle_status(self):
        if not self.is_active:
            return "DISABLED"
        today = timezone.localdate()
        if today < self.starts_on:
            return "FUTURE"
        if today > self.ends_on:
            return "PAST"
        return "CURRENT"

    @property
    def makeup_deadline_at(self):
        value = datetime.combine(self.ends_on + timedelta(days=1), time(23, 59, 59))
        return timezone.make_aware(value, timezone.get_current_timezone())

    @property
    def hours_download_at(self):
        value = datetime.combine(self.ends_on + timedelta(days=3), time.min)
        return timezone.make_aware(value, timezone.get_current_timezone())

    @property
    def is_hours_downloadable(self):
        return timezone.now() >= self.hours_download_at

    def __str__(self):
        return f"{self.name_zh} / {self.name_en}"


class Gender(models.TextChoices):
    MALE = "MALE", "男 / Male"
    FEMALE = "FEMALE", "女 / Female"
    NON_BINARY = "NON_BINARY", "非二元 / Non-binary"
    PREFER_NOT_TO_SAY = "UNDISCLOSED", "不願透露 / Prefer not to say"


class TutorProfile(models.Model):
    tutor = models.OneToOneField(User, on_delete=models.CASCADE, related_name="tutor_profile")
    gender = models.CharField("性別 / Gender", max_length=16, choices=Gender.choices)
    native_language = models.CharField("母語 / Native language", max_length=80)
    nationality = models.CharField("國籍 / Nationality", max_length=80)
    department = models.CharField("系所 / Department", max_length=150, default="華語文教學系")
    level_listening = models.PositiveSmallIntegerField("聽力教學 / Listening", default=0)
    level_speaking = models.PositiveSmallIntegerField("口說教學 / Speaking", default=0)
    level_reading = models.PositiveSmallIntegerField("閱讀教學 / Reading", default=0)
    level_writing = models.PositiveSmallIntegerField("寫作教學 / Writing", default=0)
    teaching_notes = models.TextField("教學簡介 / Teaching notes", blank=True)
    available_days = models.JSONField("可配合星期 / Available days", default=list)
    available_time_slots = models.JSONField("可配合時段 / Available time slots", default=list)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Tutor 個人檔案 / Tutor profile"
        verbose_name_plural = "Tutor 個人檔案 / Tutor profiles"

    def clean(self):
        if self.tutor_id and self.tutor.role != Role.TUTOR:
            raise ValidationError("只有 Tutor 可以建立 Tutor 檔案。 / Only tutors may have a tutor profile.")
        scores = [self.level_listening, self.level_speaking, self.level_reading, self.level_writing]
        if any(score < 0 or score > 5 for score in scores):
            raise ValidationError("能力自評須介於 0 到 5。 / Skill ratings must be between 0 and 5.")


class TuteeProfile(models.Model):
    tutee = models.OneToOneField(User, on_delete=models.CASCADE, related_name="tutee_profile")
    gender = models.CharField("性別 / Gender", max_length=16, choices=Gender.choices)
    native_language = models.CharField("母語 / Native language", max_length=80)
    nationality = models.CharField("國籍 / Nationality", max_length=80)
    department = models.CharField("系所 / Department", max_length=150)
    overall_level = models.CharField("整體華語程度 / Overall Chinese level", max_length=50)
    learning_duration = models.CharField("華語學習時間 / Learning duration", max_length=80, blank=True)
    level_listening = models.PositiveSmallIntegerField("聽力 / Listening", default=3)
    level_speaking = models.PositiveSmallIntegerField("口說 / Speaking", default=3)
    level_reading = models.PositiveSmallIntegerField("閱讀 / Reading", default=3)
    level_writing = models.PositiveSmallIntegerField("寫作 / Writing", default=3)
    target_skills = models.JSONField("希望加強項目 / Target skills", default=list)
    skills_to_improve = models.TextField("學習需求 / Learning needs", blank=True)
    preferred_days = models.JSONField("偏好星期 / Preferred days", default=list)
    preferred_time_slots = models.JSONField("偏好時段 / Preferred time slots", default=list)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Tutee 個人檔案 / Tutee profile"
        verbose_name_plural = "Tutee 個人檔案 / Tutee profiles"

    def clean(self):
        if self.tutee_id and self.tutee.role != Role.TUTEE:
            raise ValidationError("只有 Tutee 可以建立 Tutee 檔案。 / Only tutees may have a tutee profile.")
        scores = [self.level_listening, self.level_speaking, self.level_reading, self.level_writing]
        if any(score < 1 or score > 5 for score in scores):
            raise ValidationError("能力自評須介於 1 到 5。 / Skill ratings must be between 1 and 5.")


class InvitationStatus(models.TextChoices):
    PENDING = "PENDING", "等待回覆 / Pending"
    ACCEPTED = "ACCEPTED", "已接受 / Accepted"
    REJECTED = "REJECTED", "已拒絕 / Declined"
    CANCELLED = "CANCELLED", "已取消 / Cancelled"
    EXPIRED = "EXPIRED", "已過期 / Expired"


class PairingStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "輔導中 / Active"
    ENDED = "ENDED", "已結束 / Ended"


class MatchingInvitation(models.Model):
    semester = models.ForeignKey(Semester, on_delete=models.PROTECT, related_name="matching_invitations")
    tutor = models.ForeignKey(User, on_delete=models.PROTECT, related_name="tutor_invitations")
    tutee = models.ForeignKey(User, on_delete=models.PROTECT, related_name="tutee_invitations")
    initiated_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="sent_matching_invitations")
    status = models.CharField(max_length=12, choices=InvitationStatus.choices, default=InvitationStatus.PENDING)
    expires_at = models.DateTimeField("邀請到期時間 / Invitation expiry")
    responded_at = models.DateTimeField("回覆時間 / Responded at", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "配對邀請 / Matching invitation"
        verbose_name_plural = "配對邀請 / Matching invitations"
        constraints = [
            models.UniqueConstraint(
                fields=["semester", "tutor", "tutee"],
                condition=Q(status=InvitationStatus.PENDING),
                name="unique_pending_invitation_per_pair",
            )
        ]

    def clean(self):
        if self.tutor_id and self.tutor.role != Role.TUTOR:
            raise ValidationError({"tutor": "邀請的 Tutor 身分不正確。 / Invalid tutor role."})
        if self.tutee_id and self.tutee.role != Role.TUTEE:
            raise ValidationError({"tutee": "邀請的 Tutee 身分不正確。 / Invalid tutee role."})
        if self.initiated_by_id and self.initiated_by_id not in {self.tutor_id, self.tutee_id}:
            raise ValidationError({"initiated_by": "發起人必須是邀請雙方之一。 / Initiator must be one of the participants."})


class Pairing(models.Model):
    semester = models.ForeignKey(Semester, on_delete=models.PROTECT, related_name="pairings")
    tutor = models.ForeignKey(User, on_delete=models.PROTECT, related_name="tutor_pairings")
    tutee = models.ForeignKey(User, on_delete=models.PROTECT, related_name="tutee_pairings")
    invitation = models.OneToOneField(
        MatchingInvitation, on_delete=models.PROTECT, related_name="pairing", null=True, blank=True
    )
    status = models.CharField(max_length=8, choices=PairingStatus.choices, default=PairingStatus.ACTIVE)
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    end_reason = models.CharField("結束原因 / End reason", max_length=80, blank=True)

    class Meta:
        ordering = ["-started_at"]
        verbose_name = "輔導配對 / Pairing"
        verbose_name_plural = "輔導配對 / Pairings"
        constraints = [
            models.UniqueConstraint(
                fields=["semester", "tutor", "tutee"],
                name="unique_pair_per_semester",
            ),
            models.UniqueConstraint(
                fields=["semester", "tutee"],
                condition=Q(status=PairingStatus.ACTIVE),
                name="one_active_tutor_per_tutee_semester",
            ),
        ]

    def clean(self):
        if self.tutor_id and self.tutor.role != Role.TUTOR:
            raise ValidationError({"tutor": "配對的 Tutor 身分不正確。 / Invalid tutor role."})
        if self.tutee_id and self.tutee.role != Role.TUTEE:
            raise ValidationError({"tutee": "配對的 Tutee 身分不正確。 / Invalid tutee role."})

    def __str__(self):
        return f"{self.semester}: {self.tutor.username} - {self.tutee.username}"

    @property
    def pending_release_request(self):
        return self.release_requests.filter(status=PairingReleaseStatus.PENDING).first()


class PairingMessage(models.Model):
    pairing = models.ForeignKey(Pairing, on_delete=models.PROTECT, related_name="messages")
    sender = models.ForeignKey(User, on_delete=models.PROTECT, related_name="sent_pairing_messages")
    body = models.TextField("訊息 / Message", max_length=2000)
    read_at = models.DateTimeField("閱讀時間 / Read at", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "pk"]
        verbose_name = "配對私訊 / Pairing message"
        verbose_name_plural = "配對私訊 / Pairing messages"
        indexes = [models.Index(fields=["pairing", "created_at"])]

    def clean(self):
        if self.pairing_id and self.sender_id not in {self.pairing.tutor_id, self.pairing.tutee_id}:
            raise ValidationError("私訊者必須是配對雙方之一。 / The sender must belong to the pairing.")

    def __str__(self):
        return f"{self.pairing} · {self.sender.username} · {self.created_at:%Y-%m-%d %H:%M}"


class PairingReleaseReason(models.TextChoices):
    NO_SHOW = "NO_SHOW", "老師或學生未出席 / Teacher or student repeatedly absent"
    UNREACHABLE = "UNREACHABLE", "老師或學生失去聯絡 / Teacher or student unreachable"
    SCHEDULE_CONFLICT = "SCHEDULE_CONFLICT", "雙方時間無法配合 / Schedule conflict"
    CONDUCT = "CONDUCT", "態度或行為問題 / Conduct or behavior concern"
    OTHER = "OTHER", "其他原因 / Other"


class PairingReleaseStatus(models.TextChoices):
    PENDING = "PENDING", "等待管理員處理 / Pending admin review"
    APPROVED = "APPROVED", "管理員已核准 / Approved by admin"
    AUTO_APPROVED = "AUTO_APPROVED", "系統自動解除 / Automatically released"
    REJECTED = "REJECTED", "管理員未核准 / Rejected by admin"


class PairingReleaseRequest(models.Model):
    pairing = models.ForeignKey(Pairing, on_delete=models.PROTECT, related_name="release_requests")
    requested_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="pairing_release_requests")
    reason = models.CharField("解除原因 / Release reason", max_length=24, choices=PairingReleaseReason.choices)
    reason_note = models.TextField("申請說明 / Request note", blank=True)
    status = models.CharField(
        "處理狀態 / Review status",
        max_length=16,
        choices=PairingReleaseStatus.choices,
        default=PairingReleaseStatus.PENDING,
    )
    auto_resolve_at = models.DateTimeField("自動解除時間 / Automatic release time", null=True, blank=True)
    reviewed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_pairing_release_requests",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.TextField("審核備註 / Review note", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "解除配對申請 / Pairing release request"
        verbose_name_plural = "解除配對申請 / Pairing release requests"
        constraints = [
            models.UniqueConstraint(
                fields=["pairing"],
                condition=Q(status=PairingReleaseStatus.PENDING),
                name="one_pending_release_request_per_pairing",
            )
        ]

    @property
    def is_auto_eligible(self):
        return self.reason in {
            PairingReleaseReason.NO_SHOW,
            PairingReleaseReason.UNREACHABLE,
            PairingReleaseReason.SCHEDULE_CONFLICT,
        }

    def clean(self):
        if self.requested_by_id and self.pairing_id:
            if self.requested_by_id not in {self.pairing.tutor_id, self.pairing.tutee_id}:
                raise ValidationError("申請人必須是配對雙方之一。 / Requester must be one of the paired users.")

    def __str__(self):
        return f"{self.pairing} · {self.get_reason_display()}"


class ClassSessionStatus(models.TextChoices):
    SCHEDULED = "SCHEDULED", "已排課 / Scheduled"
    CANCELLED = "CANCELLED", "已取消 / Cancelled"


class ClassSession(models.Model):
    DURATION_CHOICES = [
        (0.5, "0.5 小時 / hour"),
        (1, "1 小時 / hour"),
        (1.5, "1.5 小時 / hours"),
        (2, "2 小時 / hours"),
    ]

    pairing = models.ForeignKey(Pairing, on_delete=models.PROTECT, related_name="class_sessions")
    class_date = models.DateField("上課日期 / Class date")
    start_time = models.TimeField("開始時間 / Start time")
    duration = models.DecimalField(
        "時數 / Duration", max_digits=2, decimal_places=1, choices=DURATION_CHOICES
    )
    recurrence_group = models.UUIDField(null=True, blank=True, db_index=True)
    status = models.CharField(max_length=12, choices=ClassSessionStatus.choices, default=ClassSessionStatus.SCHEDULED)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="created_class_sessions")
    cancellation_reason = models.TextField("取消原因 / Cancellation reason", blank=True)
    cancelled_by = models.ForeignKey(
        User, on_delete=models.PROTECT, null=True, blank=True, related_name="cancelled_class_sessions"
    )
    cancelled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["class_date", "start_time"]
        verbose_name = "課程 / Class session"
        verbose_name_plural = "課程 / Class sessions"
        constraints = [
            models.CheckConstraint(
                condition=Q(duration__in=[0.5, 1, 1.5, 2]), name="valid_class_session_duration"
            )
        ]

    @property
    def starts_at(self):
        value = datetime.combine(self.class_date, self.start_time)
        return timezone.make_aware(value, timezone.get_current_timezone())

    @property
    def ends_at(self):
        return self.starts_at + timedelta(hours=float(self.duration))

    @property
    def week_starts_on(self):
        return self.class_date - timedelta(days=self.class_date.weekday())

    def clean(self):
        if self.pairing_id:
            if self.class_date < self.pairing.semester.starts_on or self.class_date > self.pairing.semester.ends_on:
                raise ValidationError("上課日期須在本學期內。 / The class date must be within the semester.")
            if self.created_by_id and self.created_by_id != self.pairing.tutor_id:
                raise ValidationError("只有配對老師可以排課。 / Only the paired teacher may schedule classes.")

    def __str__(self):
        return f"{self.class_date} {self.start_time:%H:%M} · {self.pairing}"


class Attendance(models.Model):
    session = models.ForeignKey(ClassSession, on_delete=models.CASCADE, related_name="attendances")
    participant = models.ForeignKey(User, on_delete=models.PROTECT, related_name="class_attendances")
    signed_at = models.DateTimeField()
    is_makeup = models.BooleanField("補簽到 / Makeup check-in", default=False)
    makeup_reason = models.TextField("補登原因 / Makeup reason", blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["session", "participant"], name="one_attendance_per_person")]


class ClassRecord(models.Model):
    session = models.ForeignKey(ClassSession, on_delete=models.CASCADE, related_name="class_records")
    author = models.ForeignKey(User, on_delete=models.PROTECT, related_name="class_records")
    location = models.CharField("上課地點 / Location", max_length=150)
    topic = models.CharField("課堂主題 / Topic", max_length=200)
    content = models.TextField("課堂內容 / Class content", max_length=2000)
    reflection = models.TextField("學習成果與回饋 / Outcome and reflection")
    skills_practiced = models.JSONField("授課類型 / Skills practiced", default=list, blank=True)
    remarks = models.TextField("備註 / Remarks", max_length=2000, blank=True)
    attachment = models.FileField(
        "附件 / Attachment",
        upload_to="class_record_attachments/%Y/%m/",
        blank=True,
        validators=[validate_class_record_attachment],
    )
    submitted_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_makeup = models.BooleanField("補課堂紀錄 / Makeup class record", default=False)
    makeup_reason = models.TextField("補登原因 / Makeup reason", blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["session", "author"], name="one_record_per_person")]

    @property
    def attachment_filename(self):
        return Path(self.attachment.name).name if self.attachment else ""


class ConfirmationStatus(models.TextChoices):
    CONFIRMED = "CONFIRMED", "確認無誤 / Confirmed"
    REVISION = "REVISION", "請對方修改 / Revision requested"
    ISSUE = "ISSUE", "回報問題 / Report issue"


class ClassConfirmation(models.Model):
    session = models.ForeignKey(ClassSession, on_delete=models.CASCADE, related_name="confirmations")
    reviewer = models.ForeignKey(User, on_delete=models.PROTECT, related_name="class_confirmations")
    subject = models.ForeignKey(User, on_delete=models.PROTECT, related_name="received_class_confirmations")
    attendance_confirmed = models.BooleanField(default=False)
    record_confirmed = models.BooleanField(default=False)
    status = models.CharField(max_length=12, choices=ConfirmationStatus.choices)
    note = models.TextField("說明 / Note", blank=True)
    confirmed_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["session", "reviewer"], name="one_confirmation_per_reviewer")]


class MakeupReviewStatus(models.TextChoices):
    WAITING = "WAITING", "等待雙方確認 / Waiting for mutual confirmation"
    PENDING = "PENDING", "待管理員審核 / Pending admin review"
    APPROVED = "APPROVED", "已核准 / Approved"
    REJECTED = "REJECTED", "未核准 / Rejected"


class MakeupReview(models.Model):
    session = models.OneToOneField(ClassSession, on_delete=models.CASCADE, related_name="makeup_review")
    status = models.CharField(max_length=12, choices=MakeupReviewStatus.choices, default=MakeupReviewStatus.WAITING)
    reviewed_by = models.ForeignKey(
        User, on_delete=models.PROTECT, null=True, blank=True, related_name="reviewed_makeup_requests"
    )
    review_note = models.TextField("審核備註 / Review note", blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class ClassAlertStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "待處理 / Active"
    CANCELLED = "CANCELLED", "已取消 / Cancelled"
    RESOLVED = "RESOLVED", "已紀錄 / Logged"


class ClassAlertReason(models.TextChoices):
    CANNOT_REACH = "CANNOT_REACH", "聯絡不到對方 / Cannot reach the other participant"
    ABSENT = "ABSENT", "對方未出席 / The other participant is absent"
    SCHEDULE_ISSUE = "SCHEDULE_ISSUE", "上課時間或地點有問題 / Schedule or location issue"
    OTHER = "OTHER", "其他緊急狀況 / Other urgent issue"


class ClassAlert(models.Model):
    session = models.ForeignKey(ClassSession, on_delete=models.CASCADE, related_name="class_alerts")
    reporter = models.ForeignKey(User, on_delete=models.PROTECT, related_name="reported_class_alerts")
    subject = models.ForeignKey(User, on_delete=models.PROTECT, related_name="received_class_alerts")
    reason = models.CharField("通報原因 / Alert reason", max_length=20, choices=ClassAlertReason.choices)
    note = models.TextField("通報說明 / Alert note", blank=True)
    status = models.CharField(max_length=12, choices=ClassAlertStatus.choices, default=ClassAlertStatus.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        User, on_delete=models.PROTECT, null=True, blank=True, related_name="resolved_class_alerts"
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution_note = models.TextField("紀錄備註 / Log note", blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["session", "reporter"],
                condition=Q(status=ClassAlertStatus.ACTIVE),
                name="one_active_class_alert_per_reporter",
            )
        ]
        verbose_name = "課堂通報 / Class alert"
        verbose_name_plural = "課堂通報 / Class alerts"


class IncidentReportStatus(models.TextChoices):
    PENDING = "PENDING", "待處理 / Pending"
    RESOLVED = "RESOLVED", "已紀錄 / Logged"


class IncidentReportCategory(models.TextChoices):
    STUDENT_ABSENT = "STUDENT_ABSENT", "學生缺席 / Student absent"
    TUTOR_ABSENT = "TUTOR_ABSENT", "老師缺席 / Tutor absent"
    VENUE_ISSUE = "VENUE_ISSUE", "場地問題 / Venue issue"
    LEARNING_PROGRESS = "LEARNING_PROGRESS", "學習進度問題 / Learning progress issue"
    SAFETY = "SAFETY", "人身安全 / Safety concern"
    OTHER = "OTHER", "其他 / Other"


class IncidentReport(models.Model):
    session = models.ForeignKey(ClassSession, on_delete=models.CASCADE, related_name="incident_reports")
    reporter = models.ForeignKey(User, on_delete=models.PROTECT, related_name="reported_incident_reports")
    category = models.CharField("分類 / Category", max_length=20, choices=IncidentReportCategory.choices)
    content = models.TextField("回報內容 / Report content")
    status = models.CharField(max_length=12, choices=IncidentReportStatus.choices, default=IncidentReportStatus.PENDING)
    resolved_by = models.ForeignKey(
        User, on_delete=models.PROTECT, null=True, blank=True, related_name="resolved_incident_reports"
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution_note = models.TextField("紀錄備註 / Log note", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "異常回報 / Incident report"
        verbose_name_plural = "異常回報 / Incident reports"


class HourAdjustment(models.Model):
    """Manual credit for hours not captured by a real ClassSession (e.g. paper records
    predating this system). Additive only, never itemized on the official certificate PDF
    (see CLAUDE.md 4.9) — it only raises the printed total."""

    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name="hour_adjustments")
    semester = models.ForeignKey(Semester, on_delete=models.PROTECT, related_name="hour_adjustments")
    program = models.ForeignKey(PartnerProgram, on_delete=models.PROTECT, related_name="hour_adjustments")
    hours = models.DecimalField("調整時數 / Adjustment hours", max_digits=4, decimal_places=1)
    reason = models.TextField("調整原因 / Reason")
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="created_hour_adjustments")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "時數調整紀錄 / Hour adjustment"
        verbose_name_plural = "時數調整紀錄 / Hour adjustments"

    def clean(self):
        if self.hours is not None and self.hours <= 0:
            raise ValidationError({"hours": "調整時數必須大於 0，只能用來加註歷史時數。 / Adjustment hours must be greater than zero; this can only add hours."})
        if self.user_id and self.user.role not in {Role.TUTOR, Role.TUTEE}:
            raise ValidationError("只能為老師或學生新增時數調整。 / Adjustments can only be made for a Tutor or Tutee account.")

    def __str__(self):
        return f"{self.user.username} +{self.hours} 小時 ({self.semester})"
