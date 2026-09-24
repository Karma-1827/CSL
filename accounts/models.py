import logging

from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.models import AbstractUser, UserManager
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

logger = logging.getLogger("csl.audit")


class Role(models.TextChoices):
    ADMIN = "ADMIN", "管理員 / Admin"
    TUTOR = "TUTOR", "老師 / Teacher"
    TUTEE = "TUTEE", "學生 / Student"


class EducationLevel(models.TextChoices):
    BACHELOR = "BACHELOR", "大學 / Bachelor's"
    MASTER = "MASTER", "碩士 / Master's"
    DOCTORAL = "DOCTORAL", "博士 / Doctoral"
    NOT_APPLICABLE = "NA", "不適用 / Not applicable"


class IdentityCategory(models.TextChoices):
    LOCAL = "LOCAL", "本地生 / Domestic student"
    OVERSEAS = "OVERSEAS", "僑生 / Overseas Chinese student"
    HONG_KONG_MACAO = "HONG_KONG_MACAO", "港澳生 / Hong Kong and Macao student"
    MAINLAND = "MAINLAND", "陸生 / Mainland Chinese student"
    INTERNATIONAL = "INTERNATIONAL", "外籍生 / International student"


class AccountStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "啟用 / Active"
    SUSPENDED = "SUSPENDED", "停用 / Suspended"


class CSLUserManager(UserManager):
    def create_superuser(self, username, email=None, password=None, **extra_fields):
        extra_fields.setdefault("role", Role.ADMIN)
        extra_fields.setdefault("account_status", AccountStatus.ACTIVE)
        return super().create_superuser(username, email, password, **extra_fields)


class PartnerProgram(models.Model):
    code = models.CharField("代碼 / Code", max_length=20, unique=True)
    name_zh = models.CharField("中文名稱 / Chinese name", max_length=100)
    name_en = models.CharField("英文名稱 / English name", max_length=150)
    is_active = models.BooleanField("啟用中 / Active", default=True)
    allow_tutee_initiate_invitation = models.BooleanField(
        "Tutee 可主動邀請 Tutor / Tutee can initiate invitations", default=False
    )
    tutee_can_download_hours = models.BooleanField(
        "Tutee 可下載時數證明 / Tutee can download hour certificates", default=False
    )
    class_documents_enabled = models.BooleanField(
        "開放上課文件 / Class documents enabled", default=False,
        help_text=(
            "開啟後，此計畫符合資格的 Tutor/Tutee 才會在選單看到「上課文件」並能查看已啟用的文件。 / "
            "When enabled, eligible Tutors/Tutees of this program see the \"Class documents\" menu "
            "item and can view active documents."
        ),
    )
    tutee_certificate_filename = models.CharField(
        "Tutee 證明模板檔名 / Tutee certificate template filename", max_length=150, blank=True,
        help_text="檔名需已存在於 tutoring/resources/certificate_templates/。多個計畫可共用同一份底圖。",
    )
    tutee_certificate_title_zh = models.CharField(
        "Tutee 證明標題(中) / Tutee certificate title (Chinese)", max_length=50, blank=True
    )
    tutee_certificate_title_en = models.CharField(
        "Tutee 證明標題(英) / Tutee certificate title (English)", max_length=100, blank=True
    )
    tutee_certificate_plan_name = models.CharField(
        "Tutee 證明計畫名稱(中) / Tutee certificate plan name (Chinese)", max_length=100, blank=True
    )
    tutee_certificate_plan_name_en = models.CharField(
        "Tutee 證明計畫名稱(英) / Tutee certificate plan name (English)", max_length=150, blank=True
    )
    tutee_certificate_activity_text = models.CharField(
        "Tutee 證明活動描述(中) / Tutee certificate activity text (Chinese)", max_length=200, blank=True
    )
    tutee_certificate_activity_text_en = models.CharField(
        "Tutee 證明活動描述(英) / Tutee certificate activity text (English)", max_length=300, blank=True
    )
    tutor_certificate_filename = models.CharField(
        "Tutor 證明模板檔名 / Tutor certificate template filename", max_length=150, blank=True,
        help_text="檔名需已存在於 tutoring/resources/certificate_templates/。多個計畫可共用同一份底圖。",
    )
    tutor_certificate_title_zh = models.CharField(
        "Tutor 證明標題(中) / Tutor certificate title (Chinese)", max_length=50, blank=True
    )
    tutor_certificate_title_en = models.CharField(
        "Tutor 證明標題(英) / Tutor certificate title (English)", max_length=100, blank=True
    )
    tutor_certificate_plan_name = models.CharField(
        "Tutor 證明計畫名稱(中) / Tutor certificate plan name (Chinese)", max_length=100, blank=True
    )
    tutor_certificate_plan_name_en = models.CharField(
        "Tutor 證明計畫名稱(英) / Tutor certificate plan name (English)", max_length=150, blank=True
    )
    tutor_certificate_activity_text = models.CharField(
        "Tutor 證明活動描述(中) / Tutor certificate activity text (Chinese)", max_length=200, blank=True
    )
    tutor_certificate_activity_text_en = models.CharField(
        "Tutor 證明活動描述(英) / Tutor certificate activity text (English)", max_length=300, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name_zh"]
        verbose_name = "合作計畫 / Partner program"
        verbose_name_plural = "合作計畫 / Partner programs"

    def __str__(self):
        return f"{self.name_zh} ({self.code})"


class RosterEntry(models.Model):
    student_id = models.CharField("學號 / Student ID", max_length=24, unique=True)
    name_zh = models.CharField(
        "中文姓名 / Chinese name", max_length=100, blank=True,
        help_text="匯入時可留空，由使用者註冊時自行填寫。",
    )
    name_en = models.CharField("英文姓名 / English name", max_length=150, blank=True)
    role = models.CharField("身分 / Role", max_length=10, choices=Role.choices)
    education_level = models.CharField(
        "學制 / Degree level", max_length=12, choices=EducationLevel.choices, default=EducationLevel.NOT_APPLICABLE
    )
    identity_category = models.CharField(
        "學生類別 / Student category", max_length=16, choices=IdentityCategory.choices, blank=True,
        help_text="匯入時可留空，由使用者註冊時自行填寫。",
    )
    program = models.ForeignKey(
        PartnerProgram,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="roster_entries",
        verbose_name="所屬計畫 / Program",
    )
    is_enabled = models.BooleanField("可註冊 / Registration enabled", default=True)
    claimed_at = models.DateTimeField("註冊時間 / Claimed at", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["student_id"]
        verbose_name = "學生名冊 / Roster entry"
        verbose_name_plural = "學生名冊 / Roster entries"

    def clean(self):
        if self.student_id:
            self.student_id = self.student_id.strip().upper()
        if self.role == Role.ADMIN:
            raise ValidationError("管理員不可由學生名冊建立。 / Admins cannot be created from the student roster.")
        if self.role == Role.TUTEE and self.program_id is None:
            raise ValidationError({"program": "Tutee 必須設定所屬計畫。 / Tutee program is required."})

    @property
    def is_claimed(self):
        return self.claimed_at is not None

    def __str__(self):
        return f"{self.student_id} - {self.name_zh}"


class RegistrationDraft(models.Model):
    roster_entry = models.OneToOneField(
        RosterEntry,
        on_delete=models.CASCADE,
        related_name="registration_draft",
        verbose_name="名冊資料 / Roster entry",
    )
    password_hash = models.CharField("密碼雜湊 / Password hash", max_length=256)
    expires_at = models.DateTimeField("到期時間 / Expires at")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "註冊草稿 / Registration draft"
        verbose_name_plural = "註冊草稿 / Registration drafts"

    @property
    def is_expired(self):
        return timezone.now() >= self.expires_at


class User(AbstractUser):
    objects = CSLUserManager()

    role = models.CharField("角色 / Role", max_length=10, choices=Role.choices, default=Role.TUTOR)
    account_status = models.CharField(
        "帳號狀態 / Account status", max_length=12, choices=AccountStatus.choices, default=AccountStatus.ACTIVE
    )
    roster_entry = models.OneToOneField(
        RosterEntry,
        verbose_name="名冊資料 / Roster entry",
        on_delete=models.PROTECT,
        related_name="user",
        null=True,
        blank=True,
    )
    name_zh = models.CharField("中文姓名 / Chinese name", max_length=100, blank=True)
    name_en = models.CharField("英文姓名 / English name", max_length=150, blank=True)
    phone = models.CharField("電話 / Phone", max_length=30, blank=True)

    class Meta:
        ordering = ["username"]
        verbose_name = "使用者 / User"
        verbose_name_plural = "使用者 / Users"

    @property
    def student_id(self):
        return self.username

    @property
    def bilingual_name(self):
        return " / ".join(value for value in [self.name_zh, self.name_en] if value) or self.username

    def __str__(self):
        return f"{self.username} - {self.bilingual_name}"


class SecurityQuestionAnswer(models.Model):
    # Full list, including retired questions (Q4/Q6/Q7). New registrations may only pick from
    # ACTIVE_QUESTION_CHOICES below, but existing users who already answered a retired question
    # must still be able to see and answer it during account recovery, so the model field choices
    # (and get_question_N_display()) must keep resolving every key that was ever issued.
    QUESTION_CHOICES = [
        ("Q1", "我第一所就讀的小學名稱？ / What was the name of my first elementary school?"),
        ("Q2", "我最喜歡的食物？ / What is my favorite food?"),
        ("Q3", "我最喜歡的一本書？ / What is my favorite book?"),
        ("Q4", "我第一位導師的姓氏？ / What was my first homeroom teacher's surname?"),
        ("Q5", "我最想造訪的城市？ / Which city would I most like to visit?"),
        ("Q6", "我自訂的一句秘密短語？ / What is my personal secret phrase?"),
        ("Q7", "我童年最喜歡的遊戲？ / What was my favorite childhood game?"),
        ("Q8", "我的第一隻寵物叫什麼名字？ / What was the name of my first pet?"),
        ("Q9", "我的綽號？ / What is my nickname?"),
        ("Q10", "我印象最深刻的旅行地點？ / What is my most memorable travel destination?"),
        ("Q11", "我最喜歡的一部電影？ / What is my favorite movie?"),
        ("Q12", "我最喜歡的一首歌？ / What is my favorite song?"),
    ]
    # Retired: no longer offered to new registrations (Q4 "first homeroom teacher's surname",
    # Q6 "personal secret phrase", Q7 "favorite childhood game"). Existing answers still work.
    RETIRED_QUESTION_KEYS = {"Q4", "Q6", "Q7"}
    # NOTE: computed just below the class body, not here — a class-body comprehension can't see
    # other class attributes in its condition (only the outermost iterable), so referencing
    # RETIRED_QUESTION_KEYS here would raise NameError.
    ACTIVE_QUESTION_CHOICES = []

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="security_questions")
    question_1 = models.CharField(max_length=3, choices=QUESTION_CHOICES)
    answer_1_hash = models.CharField(max_length=256)
    question_2 = models.CharField(max_length=3, choices=QUESTION_CHOICES)
    answer_2_hash = models.CharField(max_length=256)
    question_3 = models.CharField(max_length=3, choices=QUESTION_CHOICES)
    answer_3_hash = models.CharField(max_length=256)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "安全問題 / Security questions"
        verbose_name_plural = "安全問題 / Security questions"
        constraints = [
            models.CheckConstraint(
                condition=(
                    ~models.Q(question_1=models.F("question_2"))
                    & ~models.Q(question_1=models.F("question_3"))
                    & ~models.Q(question_2=models.F("question_3"))
                ),
                name="three_distinct_security_questions",
            )
        ]

    @staticmethod
    def normalize_answer(value):
        return " ".join(value.strip().casefold().split())

    def set_answers(self, answers):
        self.answer_1_hash = make_password(self.normalize_answer(answers[0]))
        self.answer_2_hash = make_password(self.normalize_answer(answers[1]))
        self.answer_3_hash = make_password(self.normalize_answer(answers[2]))

    def check_answers(self, answers):
        normalized = [self.normalize_answer(value) for value in answers]
        return all(
            check_password(value, stored)
            for value, stored in zip(
                normalized,
                [self.answer_1_hash, self.answer_2_hash, self.answer_3_hash],
            )
        )


SecurityQuestionAnswer.ACTIVE_QUESTION_CHOICES = [
    choice for choice in SecurityQuestionAnswer.QUESTION_CHOICES
    if choice[0] not in SecurityQuestionAnswer.RETIRED_QUESTION_KEYS
]


class AuditLog(models.Model):
    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="audit_actions")
    target_user = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="audit_events"
    )
    event_type = models.CharField("事件類型 / Event type", max_length=80)
    description = models.CharField("說明 / Description", max_length=255)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "稽核紀錄 / Audit log"
        verbose_name_plural = "稽核紀錄 / Audit logs"

    @classmethod
    def record(cls, **kwargs):
        """Best-effort audit log write.

        Wrapped in its own nested atomic() (a savepoint when called from inside an
        outer @transaction.atomic block) so a failure here only rolls back this one
        insert instead of poisoning the caller's whole transaction. The failure is
        logged rather than swallowed, and the caller's primary action still succeeds
        without an audit trail rather than being blocked by a logging failure.
        """
        try:
            with transaction.atomic():
                return cls.objects.create(**kwargs)
        except Exception:
            logger.exception(
                "Failed to write AuditLog entry: event_type=%s target_user_id=%s",
                kwargs.get("event_type"), getattr(kwargs.get("target_user"), "pk", None),
            )
            return None


class DepartmentOralExamPassListType(models.TextChoices):
    ORAL_EXAM_PASS = "ORAL_EXAM_PASS", "語音通過 / Oral exam passed"
    # 2026-09-24(使用者要求):馬里蘭計畫的口語能力審核依據不是語音考試,而是系辦提供的
    # 修課名單(「115-1課程學生名單」等)——在這份名單上就等同符合資格,語意跟 NTNU 的
    # 「語音通過」完全不同,不能沿用同一句提示文字。
    MARYLAND_COURSE_ROSTER = "MARYLAND_COURSE_ROSTER", "馬里蘭修課名單 / Maryland course roster"


class DepartmentOralExamPass(models.Model):
    """系辦匯入的資格比對名單(2026-09-11 新增,2026-09-24 擴充涵蓋馬里蘭修課名單)。

    這跟 `RosterEntry`(系統註冊用名冊)是完全不同的資料來源與用途。目前有兩種來源檔案,
    由 `list_type` 區分:

    - `ORAL_EXAM_PASS`(NTNU):系辦內部的「碩士生修業概況一覽表」畢業條件追蹤表混雜學術
      倫理、外語、論文倫理等各種欄位,且「語音」欄位的值並不一致(通過/完成/有皆曾出現,
      語意不明確),因此匯入時只挑出值**恰好**是「通過」的列,其餘一律不視為通過。
    - `MARYLAND_COURSE_ROSTER`(馬里蘭):馬里蘭計畫的口語能力資格不是語音考試,而是系辦
      提供的修課名單(例如「115-1課程學生名單」),在名單上即視為符合資格。目前系辦提供的
      這份檔案沿用跟語音名單相同的「學號＋語音＝通過」欄位格式(可能是既有匯入介面沒有
      其他選項下的權宜格式),因此解析邏輯不需要另外改寫,只需要在匯入時記錄正確的
      `list_type` 即可正確顯示對應的提示文字。

    兩種來源都只記錄「符合資格」的學號,用來在 Admin 審核 Tutor 自行上傳的
    `tutoring.models.QualificationDocument` 時提供交叉比對提示,**不會、也不應該自動
    改變任何審核狀態**——最終核准/拒絕永遠是 Admin 手動決定,這裡只是輔助資訊。

    比對邏輯採累加式(比照 `import_roster_ids()` 的既有慣例:只新增/更新,不刪除),重新
    匯入不會清掉先前已存在的紀錄;如需訂正錯誤資料,由 Admin 在 Django Admin 手動刪除
    該筆。`student_id` 全域唯一,同一學號不會同時屬於兩種名單。
    """

    student_id = models.CharField("學號 / Student ID", max_length=24, unique=True)
    list_type = models.CharField(
        "名單類型 / List type", max_length=32,
        choices=DepartmentOralExamPassListType.choices,
        default=DepartmentOralExamPassListType.ORAL_EXAM_PASS,
    )
    imported_at = models.DateTimeField("匯入時間 / Imported at", auto_now=True)
    imported_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="imported_oral_exam_passes", verbose_name="匯入者 / Imported by"
    )

    class Meta:
        ordering = ["student_id"]
        verbose_name = "系辦資格比對名單 / Department eligibility list record"
        verbose_name_plural = "系辦資格比對名單 / Department eligibility list records"

    def clean(self):
        if self.student_id:
            self.student_id = self.student_id.strip().upper()

    def __str__(self):
        return self.student_id


class Announcement(models.Model):
    """Tutor/Tutee 首頁上方的公告欄項目(2026-09-24 新增,使用者要求)。

    比照 `tutoring.models.ClassDocument` 的 Admin 自行編輯慣例:單一模型、
    無角色區分(目前 Tutor 與 Tutee 看到同一份公告),`display_order` 決定顯示順序,
    `is_active=False` 只是暫時隱藏、不刪除歷史內容。
    """

    content = models.TextField("公告內容 / Announcement content", max_length=1000)
    display_order = models.PositiveIntegerField("顯示順序 / Display order", default=0)
    is_active = models.BooleanField("顯示中 / Active", default=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_announcements",
        verbose_name="建立者 / Created by",
    )
    created_at = models.DateTimeField("建立時間 / Created at", auto_now_add=True)
    updated_at = models.DateTimeField("更新時間 / Updated at", auto_now=True)

    class Meta:
        ordering = ["display_order", "-created_at"]
        verbose_name = "公告欄項目 / Announcement"
        verbose_name_plural = "公告欄項目 / Announcements"

    def __str__(self):
        return self.content[:40]
