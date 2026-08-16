from datetime import datetime, time, timedelta
from pathlib import Path
import uuid

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone

from accounts.models import PartnerProgram, Role, User


MAX_IMAGE_DIMENSION_PX = 6000
MAX_PDF_PAGES = 500
_OOXML_EXTENSIONS = {".docx", ".pptx", ".xlsx"}
_LEGACY_OFFICE_EXTENSIONS = {".doc", ".ppt", ".xls"}
_OLE_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def _validate_image_content(upload):
    """Batch 6 item 1 (docs/VULNERABILITY_SCAN_IMPROVEMENTS.md): reject anything that
    isn't actually a decodable image, not just files with a .jpg/.png extension — e.g. an
    HTML or script file renamed to bypass the extension check. Also caps resolution as a
    decompression-bomb guard, on top of Pillow's own built-in MAX_IMAGE_PIXELS warning
    threshold, since a small file can still declare an enormous pixel count.
    """
    from PIL import Image, UnidentifiedImageError

    upload.seek(0)
    try:
        with Image.open(upload) as image:
            image.verify()
    except (UnidentifiedImageError, OSError, ValueError) as error:
        raise ValidationError(
            "圖片檔案已損毀或不是有效的圖片。 / The image file is corrupted or not a valid image."
        ) from error
    finally:
        upload.seek(0)
    # verify() leaves the Image object unusable for further reads, so reopen fresh to
    # check dimensions (verify() alone doesn't expose a reliable, always-populated .size).
    with Image.open(upload) as image:
        width, height = image.size
    upload.seek(0)
    if width > MAX_IMAGE_DIMENSION_PX or height > MAX_IMAGE_DIMENSION_PX:
        raise ValidationError(
            f"圖片尺寸過大，長寬不可超過 {MAX_IMAGE_DIMENSION_PX}px。 / "
            f"Image dimensions must not exceed {MAX_IMAGE_DIMENSION_PX}px."
        )


def _validate_pdf_content(upload):
    """Checks the file header and that pypdf can actually parse it and enumerate its
    pages. This is a best-effort check, not a sandboxed parse: a maliciously crafted PDF
    could still make pypdf spend excessive CPU/memory while resolving its page tree before
    this function's own page-count check ever runs. Full protection would need parsing in
    an isolated, resource-limited subprocess, which is out of scope here (no VM/process
    isolation infrastructure exists yet) — the size cap on all three upload types (500 KB
    to 10 MB) bounds how much a legitimate file can contain and limits how elaborate such
    an attack payload can be.
    """
    upload.seek(0)
    header = upload.read(5)
    upload.seek(0)
    if header != b"%PDF-":
        raise ValidationError("檔案不是有效的 PDF。 / The file is not a valid PDF.")
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        page_count = len(PdfReader(upload).pages)
    except (PdfReadError, ValueError, OSError) as error:
        raise ValidationError(
            "PDF 檔案已損毀或無法解析。 / The PDF file is corrupted or unreadable."
        ) from error
    finally:
        upload.seek(0)
    if page_count > MAX_PDF_PAGES:
        raise ValidationError(
            f"PDF 頁數不可超過 {MAX_PDF_PAGES} 頁。 / The PDF must not exceed {MAX_PDF_PAGES} pages."
        )


def _validate_office_content(upload, extension):
    """OOXML formats (.docx/.pptx/.xlsx) are ZIP archives with a required manifest entry;
    legacy formats (.doc/.ppt/.xls) are OLE2 compound files with a fixed magic header.
    Checking these catches a renamed non-Office file even though, unlike PDF/image, this
    doesn't fully validate the internal document structure.
    """
    import zipfile

    upload.seek(0)
    if extension in _OOXML_EXTENSIONS:
        try:
            with zipfile.ZipFile(upload) as archive:
                names = archive.namelist()
        except zipfile.BadZipFile as error:
            raise ValidationError(
                "檔案不是有效的 Office 文件。 / The file is not a valid Office document."
            ) from error
        finally:
            upload.seek(0)
        if "[Content_Types].xml" not in names:
            raise ValidationError("檔案不是有效的 Office 文件。 / The file is not a valid Office document.")
    else:
        header = upload.read(8)
        upload.seek(0)
        if header != _OLE_SIGNATURE:
            raise ValidationError("檔案不是有效的 Office 文件。 / The file is not a valid Office document.")


def _validate_upload(upload, *, max_bytes, size_label, allowed_extensions=None, allowed_label="PDF、JPG、PNG"):
    allowed = allowed_extensions or {".pdf", ".jpg", ".jpeg", ".png"}
    extension = Path(upload.name).suffix.lower()
    if extension not in allowed:
        raise ValidationError(f"僅接受 {allowed_label}。 / Only {allowed_label} files are accepted.")
    if upload.size > max_bytes:
        raise ValidationError(f"檔案不可超過 {size_label}。 / File size must not exceed {size_label}.")
    if extension in {".jpg", ".jpeg", ".png"}:
        _validate_image_content(upload)
    elif extension == ".pdf":
        _validate_pdf_content(upload)
    elif extension in _OOXML_EXTENSIONS | _LEGACY_OFFICE_EXTENSIONS:
        _validate_office_content(upload, extension)


def validate_qualification_file(upload):
    _validate_upload(upload, max_bytes=1_000_000, size_label="1 MB")


def validate_class_record_attachment(upload):
    _validate_upload(upload, max_bytes=500_000, size_label="500 KB")


def validate_class_document_file(upload):
    _validate_upload(
        upload, max_bytes=10_000_000, size_label="10 MB",
        allowed_extensions={".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".jpg", ".jpeg", ".png"},
        allowed_label="PDF、Word、PowerPoint、Excel、JPG、PNG",
    )


def _uuid_upload_path(directory, filename):
    """Randomize the on-disk filename for newly uploaded private files (batch 3,
    docs/VULNERABILITY_SCAN_IMPROVEMENTS.md) so stored paths aren't predictable/
    enumerable from the original filename. The human-readable original name is kept
    separately (original_filename / original_attachment_filename) for display and
    Content-Disposition; historical rows saved before this change keep their old,
    name-derived paths untouched since this only affects new saves going forward.
    """
    extension = Path(filename).suffix.lower()
    return f"{directory}/{timezone.now():%Y/%m}/{uuid.uuid4().hex}{extension}"


def qualification_upload_to(instance, filename):
    return _uuid_upload_path("qualifications", filename)


def class_record_attachment_upload_to(instance, filename):
    return _uuid_upload_path("class_record_attachments", filename)


def class_document_upload_to(instance, filename):
    return _uuid_upload_path("class_documents", filename)


class QualificationStatus(models.TextChoices):
    NOT_SUBMITTED = "NOT_SUBMITTED", "未提交 / Not submitted"
    PENDING = "PENDING", "待審核 / Pending review"
    APPROVED = "APPROVED", "已通過 / Approved"
    REJECTED = "REJECTED", "需補件 / Revision required"


class QualificationDocument(models.Model):
    tutor = models.OneToOneField(User, on_delete=models.CASCADE, related_name="qualification")
    file = models.FileField(
        "口語能力證明 / Oral proficiency document",
        upload_to=qualification_upload_to,
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
    # NULL = legacy shared period, predating per-program scoping (2026-08). Kept so existing
    # Semester rows and every Pairing/ClassSession that already references them keep working
    # without a data migration. New periods created going forward should always set a program;
    # the create/edit forms enforce this even though the model field itself stays optional to
    # preserve that legacy path (see CLAUDE.md 4.2 and MEETING_CHANGE_REQUIREMENTS item 15).
    program = models.ForeignKey(
        PartnerProgram, on_delete=models.PROTECT, null=True, blank=True,
        related_name="semesters", verbose_name="合作計畫 / Partner program",
    )
    # Explicit per-user opt-in. Empty (the common case, and always true for legacy rows) means
    # "open to every eligible account for this program" — matching today's behavior exactly —
    # rather than forcing Admin to hand-pick every user before a period can be used.
    applicable_users = models.ManyToManyField(
        User, blank=True, related_name="applicable_semesters", verbose_name="適用對象 / Applicable users",
    )

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
                is_active=True, program=self.program, starts_on__lte=self.ends_on, ends_on__gte=self.starts_on
            ).exclude(pk=self.pk)
            if overlap.exists():
                raise ValidationError(
                    "同一合作計畫的啟用期間不可重疊。 / Enabled periods for the same program cannot overlap."
                )

    def validate_applicable_users(self, users):
        """Validate a candidate set of users for the applicable_users M2M before saving.

        Takes an explicit iterable rather than reading self.applicable_users.all(), since a
        many-to-many field can't be queried until the instance has a primary key but forms need
        to validate the submitted selection before save() ever runs.
        """
        invalid = [
            user for user in users
            if user.role not in {Role.TUTOR, Role.TUTEE}
            or not user.is_active
            or (
                self.program_id
                and user.role == Role.TUTEE
                and (not user.roster_entry_id or user.roster_entry.program_id != self.program_id)
            )
        ]
        if invalid:
            names = "、".join(user.username for user in invalid)
            raise ValidationError(
                f"適用對象必須是有效帳號,且 Tutee 須符合此計畫名冊資格:{names}。 / "
                f"Applicable users must be active accounts, and tutees must belong to this program's roster: {names}."
            )

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
    # Set only for pairings created directly by Admin (see tutoring/services.py::
    # create_admin_pairing(), MEETING_CHANGE_REQUIREMENTS_2026-08-04.md item 12). NULL for the
    # ordinary invite/accept flow — this field's only purpose is to mark "Admin built this
    # pairing without going through mutual invitation", per the requirement doc.
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="admin_created_pairings",
        verbose_name="Admin 建立者 / Created by (admin)",
    )

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
    content = models.TextField("課堂內容 / Class content", max_length=500)
    reflection = models.TextField("學習成果與回饋 / Outcome and reflection")
    skills_practiced = models.JSONField("授課類型 / Skills practiced", default=list, blank=True)
    remarks = models.TextField("備註 / Remarks", max_length=500, blank=True)
    attachment = models.FileField(
        "附件 / Attachment",
        upload_to=class_record_attachment_upload_to,
        blank=True,
        validators=[validate_class_record_attachment],
    )
    original_attachment_filename = models.CharField(max_length=255, blank=True)
    evidence_links = models.JSONField(
        "佐證連結 / Evidence links", default=list, blank=True,
        help_text="雙方課堂紀錄皆使用佐證連結。 / Evidence links are required for both participants.",
    )
    submitted_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_makeup = models.BooleanField("補課堂紀錄 / Makeup class record", default=False)
    makeup_reason = models.TextField("補登原因 / Makeup reason", blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["session", "author"], name="one_record_per_person")]

    def save(self, *args, **kwargs):
        if self.attachment and not self.attachment._committed and not self.original_attachment_filename:
            self.original_attachment_filename = Path(self.attachment.name).name
        super().save(*args, **kwargs)

    @property
    def attachment_filename(self):
        if not self.attachment:
            return ""
        return self.original_attachment_filename or Path(self.attachment.name).name


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


class ClassDocument(models.Model):
    """Admin-uploaded reference material scoped to a partner program and, optionally, a
    specific semester (e.g. syllabi or session handouts for a language-exchange course).
    See MEETING_CHANGE_REQUIREMENTS_2026-08-04.md item 5. Visibility is driven entirely by
    PartnerProgram.class_documents_enabled plus the same tutor_can_serve_program()/
    user_program() eligibility rules used for candidate browsing and invitations, so a new
    program can opt in without any code change."""

    program = models.ForeignKey(PartnerProgram, on_delete=models.PROTECT, related_name="class_documents")
    semester = models.ForeignKey(
        Semester, on_delete=models.SET_NULL, null=True, blank=True, related_name="class_documents",
        verbose_name="適用學期 / Applicable semester",
        help_text="留空表示適用此計畫所有學期。 / Leave blank to apply to every semester of this program.",
    )
    title_zh = models.CharField("中文標題 / Chinese title", max_length=200)
    title_en = models.CharField("英文標題 / English title", max_length=200)
    file = models.FileField(
        "檔案 / File", upload_to=class_document_upload_to, validators=[validate_class_document_file],
    )
    original_filename = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField("啟用 / Active", default=True)
    uploaded_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )
    uploaded_at = models.DateTimeField("上傳時間 / Uploaded at", auto_now_add=True)

    class Meta:
        ordering = ["-uploaded_at"]
        verbose_name = "上課文件 / Class document"
        verbose_name_plural = "上課文件 / Class documents"

    def __str__(self):
        return f"{self.program.code} - {self.title_zh}"

    def save(self, *args, **kwargs):
        if self.file and not self.file._committed and not self.original_filename:
            self.original_filename = Path(self.file.name).name
        super().save(*args, **kwargs)

    @property
    def filename(self):
        if not self.file:
            return ""
        return self.original_filename or Path(self.file.name).name
