import logging
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.models import AbstractUser, UserManager
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone
from django.utils.html import format_html
from django.utils.safestring import mark_safe

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

    content = models.TextField("中文公告內容 / Chinese content", max_length=1000)
    content_en = models.TextField("英文公告內容 / English content", max_length=1000, blank=True, default="")
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


class AnnouncementReadState(models.Model):
    """記錄每位使用者上一次查看「公告欄」的時間(2026-09-25 新增,使用者要求)。

    比照 `TutorProfile`/`TuteeProfile` 的既有慣例,用一筆對 `User` 的 `OneToOneField`
    儲存單純的每人狀態,不掛在 `Announcement` 本身——已讀與否是「使用者」的屬性,
    不是「公告」的屬性(同一則公告對不同使用者可能一個已讀一個未讀)。
    `last_viewed_at` 為 `None` 代表這位使用者從未點開過「公告欄」分頁,此時應視為
    全部現有公告都是新的。
    """

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="announcement_read_state")
    last_viewed_at = models.DateTimeField("上次查看時間 / Last viewed at", null=True, blank=True)

    def __str__(self):
        return f"{self.user.username} @ {self.last_viewed_at}"


class DashboardSection(models.TextChoices):
    """2026-10-03 新增(使用者要求「admin審核/紀錄的資料，tutor/tutee左側欄位對應的功能
    會有提示嗎？」):目前只有公告欄、邀請管理、私訊這三個側邊欄項目會顯示未讀數字,
    Admin 審核口語能力證明、課程、課堂通報、異常回報之後,對應的側邊欄項目完全不會
    冒出提示。這裡只先涵蓋使用者這次明確點名的三類,其餘(例如解除配對結果,已經有
    `release_notices.html` 這個首頁橫幅提示)不在這次範圍內。"""

    QUALIFICATION = "QUALIFICATION", "口語能力證明 / Qualification"
    HOURS = "HOURS", "輔導時數／課表 / Hours and schedule"
    INCIDENT_REPORTS = "INCIDENT_REPORTS", "異常回報 / Incident reports"


class DashboardReadState(models.Model):
    """記錄每位使用者上一次查看某個 dashboard 分頁的時間,比照 `AnnouncementReadState`
    的既有慣例,但一個使用者需要分別追蹤多個分類(口語能力證明/輔導時數/異常回報),
    所以用 `section` 欄位區分,而不是像公告欄那樣每人只有一筆。`last_viewed_at` 為
    `None` 代表這位使用者從未點開過這個分頁,此時應視為全部現有變動都是新的。"""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="dashboard_read_states")
    section = models.CharField(max_length=20, choices=DashboardSection.choices)
    last_viewed_at = models.DateTimeField("上次查看時間 / Last viewed at", null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "section"], name="unique_dashboard_read_state_per_section")
        ]

    def __str__(self):
        return f"{self.user.username} · {self.section} @ {self.last_viewed_at}"


_ORAL_EXAM_WEEKDAY_ZH = ["一", "二", "三", "四", "五", "六", "日"]


def _oral_exam_attachment_upload_to(instance, filename):
    """比照 `tutoring.models._uuid_upload_path()` 同一種做法(把原始檔名換成隨機字串
    儲存,原始檔名另外存在 `attachment_filename_N`),但這裡刻意不跨 app 匯入那個
    helper——`accounts.models` 目前完全不匯入 `tutoring.models`,而 `tutoring.models`
    本身會匯入 `accounts.models.User`,為了不冒一個目前還不存在、但以後很容易不小心
    踩到的循環匯入風險,這裡自己寫一份邏輯一樣簡單的版本。"""
    extension = Path(filename).suffix.lower()
    return f"oral_exam_attachments/{timezone.now():%Y/%m}/{uuid.uuid4().hex}{extension}"


class OralExamAnnouncement(models.Model):
    """師大外籍生(NTNU)計畫專用的線上口語考試公告(2026-10-06 新增,使用者要求)。

    使用者提供的真實公告文字裡,日期/時間以「XXXX/XX/XX」這種格式重複出現在好幾個
    不同位置,但實際上只對應兩個獨立變數——考試日期(`exam_date`)與報名截止時間
    (`registration_deadline`),其餘出現位置(含不同的日期格式、依考試日期算出的中文
    星期)都是從這兩個值動態算出來的,不是各自獨立的欄位,見下方幾個 `@property`。
    刻意**只保留「目前這一次」設定**,不像公告欄/上課文件那樣保留歷史清單——每次口試
    公告是獨立事件,Admin 改了新的一次就直接覆蓋舊的,不需要回顧舊公告;因此全站只會
    有一筆資料,`accounts/views.py` 一律用 `OralExamAnnouncement.objects.first()` 取得。
    `is_published` 是獨立的「發佈」開關(對應 Admin 畫面上的「發佈/取消發佈」按鈕),
    跟日期本身是否已填寫分開——Admin 可以先填好日期但還沒按發佈,Tutor 端完全看不到;
    按下發佈後 Tutor 才看得到完整內容,過了報名截止時間畫面上只會改標示「已截止」,
    不會整個隱藏(使用者確認:公告本身要留著,只是標記還能不能報名)。

    **2026-10-06 當天追加「附件年份＋檔案上傳」,隨後使用者更正設計(使用者要求)**:原本
    「附件是ＸＸＸＱ（2024）﹑ＸＸＸＱ（2025）﹑ＸＸＸＱ（2026）的試題」這句是刻意維持的
    靜態文字(第一輪 Q&A 確認「先當成靜態文字」)。第一版誤以為三個年份各自對應一個獨立
    檔案(做成三組「年份+檔案」),但使用者澄清**三個年份只是顯示用,不是一年一個檔案——
    附件實際上是三年合併成同一份檔案,年份純粹是用來組出公告文字裡的那句「附件是2024﹑
    2025﹑2026的試題」**。因此年份(`attachment_year_1/2/3`)與檔案(`attachment_file`)
    是**互相獨立**的兩組欄位,不是配對關係:年份只影響 `attachment_intro_text` 那句話
    怎麼寫,檔案是單一一份、所有年份共用的合併考題。這次送出**沒有附加新檔案時維持既有
    檔案不變**(方便只改日期/年份不必重新上傳同一份合併考題);附加了新檔案則直接取代
    舊檔案。
    """

    exam_date = models.DateField("考試日期 / Exam date")
    registration_deadline = models.DateTimeField("報名截止時間 / Registration deadline")
    attachment_year_1 = models.PositiveIntegerField("附件年份 1 / Attachment year 1", null=True, blank=True)
    attachment_year_2 = models.PositiveIntegerField("附件年份 2 / Attachment year 2", null=True, blank=True)
    attachment_year_3 = models.PositiveIntegerField("附件年份 3 / Attachment year 3", null=True, blank=True)
    attachment_file = models.FileField(
        "附件檔案(歷年試題合併檔) / Attachment file (combined exam papers)",
        upload_to=_oral_exam_attachment_upload_to, null=True, blank=True,
    )
    attachment_filename = models.CharField(max_length=255, blank=True)
    is_published = models.BooleanField("已發佈 / Published", default=False)
    updated_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
        verbose_name="最後更新者 / Last updated by",
    )
    updated_at = models.DateTimeField("更新時間 / Updated at", auto_now=True)

    class Meta:
        verbose_name = "線上口語考試公告 / Oral exam announcement"
        verbose_name_plural = "線上口語考試公告 / Oral exam announcements"

    def __str__(self):
        return f"{self.exam_date} ({'已發佈' if self.is_published else '未發佈'})"

    @property
    def exam_date_full(self):
        d = self.exam_date
        return f"{d.year}/{d.month}/{d.day}（{_ORAL_EXAM_WEEKDAY_ZH[d.weekday()]}）"

    @property
    def exam_date_plain(self):
        d = self.exam_date
        return f"{d.year}/{d.month}/{d.day}"

    @property
    def exam_date_short(self):
        d = self.exam_date
        return f"{d.month}/{d.day}週{_ORAL_EXAM_WEEKDAY_ZH[d.weekday()]}"

    @property
    def registration_deadline_full(self):
        local = timezone.localtime(self.registration_deadline)
        return (
            f"{local.year}/{local.month}/{local.day}"
            f"({_ORAL_EXAM_WEEKDAY_ZH[local.weekday()]}){local.hour:02d}：{local.minute:02d}"
        )

    @property
    def is_registration_open(self):
        return timezone.now() <= self.registration_deadline

    @property
    def attachment_years(self):
        """只收集真的填了的年份,依序排列——純粹用來組出公告文字,跟 `attachment_file`
        是不是已經上傳無關(年份可以先填,檔案晚點補;或檔案存在但年份還沒填,兩者
        彼此獨立)。"""
        return [year for year in [self.attachment_year_1, self.attachment_year_2, self.attachment_year_3] if year]

    @property
    def attachment_intro_text(self):
        """「附件是...的試題」這整段,只在至少填了一個年份時才存在——沒有年份代表這次
        公告沒有歷年試題可附,連「考試時將抽一份題目測驗」這兩句都一起省略,因為沒有
        附件就沒有題目可以抽。**2026-10-09 使用者要求把原本三行合併成一句,並把年份
        那一段改成粗體**:回傳值是 `format_html()` 產生的安全 HTML,不是純文字,
        `full_text` 直接把它當成已經轉好 HTML 的一行拼接進去,不能再對它的結果做
        字串層級的二次轉換(例如再丟進 `linebreaksbr`)。"""
        years = self.attachment_years
        if not years:
            return ""
        years_text = "﹑".join(str(year) for year in years)
        return format_html(
            "附件是<strong>{years}的試題</strong>，考試時將抽一份題目測驗。請抽空認字﹑練習發音，以便通過考試。",
            years=years_text,
        )

    @property
    def full_text(self):
        """完整公告內文。靜態文案(含銀行帳戶、姓名、費用)原文照抄使用者提供的內容,
        不做任何改寫或猜測性編輯——這些是正式對外公告,內容必須跟使用者實際要發佈的
        文字一字不差。**2026-10-06 使用者要求刪除「教育部華語教師能力認證考試」與
        「華語正音與口語表達」這兩行**,已整段移除,不是隱藏。

        **2026-10-09 使用者提供排版後的新版文案**:原本三行一段的開頭(考試日期/
        測驗軟體/每人時長)合併成一句,日期標紅字粗體、google meet 標粗體;原本各自
        一行的「即日起開始報名」「報名截止」「本次僅受理」「口試時間限8-17時之間，
        請至少告知3個30分鐘時段」合併成一句並刪掉「請至少告知3個30分鐘時段，以便
        安排」(系統表單本身就會要求選3個時段,不需要再用文字提醒),報名截止那段標
        紅字粗體;原本「報名方式:以電郵回覆...」整行改成系統現在實際的報名流程
        (點擊下方報名→選擇三個時段考試→上傳轉帳帳號後4碼口試費截圖),不再是電郵
        回覆,「報名方式：」這個標籤標紅字粗體。**回傳值從此是安全的 HTML 字串**
        (`format_html()`/字面常數混合拼接,最後用 `mark_safe()` 把 `<br>` 串起來的
        整段結果重新標記成安全——個別片段用純文字字面常數沒關係,因為最後整段都會
        被 `mark_safe()` 標記,逐段標記與否不影響最終結果,只有真的嵌入動態值
        的段落才需要經過 `format_html()` 跳脫),呼叫端(`templates/dashboard/
        admin_v2_panels.html`/`participant_v2_panels.html`)已改成直接
        `{{ announcement.full_text }}` 輸出,不再套用 `linebreaksbr`(那個 filter
        會把這裡原本就是安全 HTML 的 `<strong>`/`<span>` 標籤逃脫成看得到标籤符號
        的純文字)。"""
        lines = [
            format_html(
                '<span class="oral-exam-highlight">{exam_date}</span>將舉行線上語音口試，'
                "測驗軟體：<strong>google meet</strong>，每位同學10分鐘",
                exam_date=self.exam_date_full,
            ),
            "",
            format_html(
                '即日起開始報名，<span class="oral-exam-highlight">報名截止：{deadline}</span>，'
                "本次僅受理{exam_date}語音口試報名，口試時間安排在8-17時之間。",
                deadline=self.registration_deadline_full, exam_date=self.exam_date_plain,
            ),
            '<span class="oral-exam-highlight">報名方式：</span>',
            "1. 點擊下方報名",
            "2. 選擇三個時段考試",
            "3. 上傳轉帳帳號後4碼口試費截圖",
            "",
            "口試費100元請以本人的帳戶轉帳到以下郵局帳戶：",
            "戶名：王雪妮",
            "金融機構代碼：700",
            "局號：0031283 帳號：0483791",
        ]
        attachment_text = self.attachment_intro_text
        if attachment_text:
            lines.append("")
            lines.append(attachment_text)
        return mark_safe("<br>".join(str(line) for line in lines))


def _oral_exam_payment_proof_upload_to(instance, filename):
    extension = Path(filename).suffix.lower()
    return f"oral_exam_payment_proofs/{timezone.now():%Y/%m}/{uuid.uuid4().hex}{extension}"


# 2026-10-09(使用者要求「現在每次安排考試最多20人...已經滿了先停止報名」,接著
# 澄清「如果讓他們報名...他們都已經繳費了，所以我才說要從報名人數開始擋」):口試一場
# 排下來能排的人數有限(每人 15 分鐘一格),20 是系辦實際決定的上限,不是從時段範圍
# 反推出來的數字。**上限算的是「已送出報名」的總數,不是「已登記(CONFIRMED)」人數**
# ——第一版誤以為可以只擋已登記人數,讓送出總數不設上限,但使用者指出報名時就已經
# 要求繳費,若送出不設限,多出來的人等於白白繳了錯過名額的費用,所以要在「送出報名」
# 這一步就擋下,不是等 Admin 登記核對完才擋(見
# `accounts/views.py::submit_oral_exam_registration()`)。
ORAL_EXAM_MAX_REGISTRATIONS = 20


class OralExamRegistrationReviewStatus(models.TextChoices):
    """2026-10-07(使用者要求「登記狀態也加個撤回功能好了，以及「補件」按鈕和可以紀錄
    留言」):原本只有「已登記/未登記」(`confirmed_at` 有無值)兩種狀態,現在改成明確的
    三態,比照 `tutoring.models.ClassReviewStatus` 的既有慣例(PENDING/已決定兩種
    終局/REVISE 這種「還要再補東西」的中間態)。"""

    PENDING = "PENDING", "尚未核對 / Pending"
    CONFIRMED = "CONFIRMED", "已登記 / Confirmed"
    NEEDS_REVISION = "NEEDS_REVISION", "補件 / Needs additional documents"


class OralExamRegistration(models.Model):
    """NTNU Tutor 的線上口語考試報名紀錄(2026-10-06 新增,使用者要求「如果開放報名，
    tutor就可以點擊報名，完成兩個欄位 1. 選3個時間段 2. 上傳檔案(繳費紀錄) 就可以
    送出」)。

    `exam_date` 是報名當下從 `OralExamAnnouncement.exam_date` 複製過來的**快照**,
    不是即時指向那一筆的 FK——`OralExamAnnouncement` 本身是「只保留目前這一次設定」
    的 singleton,Admin 開下一輪考試時會直接覆寫同一筆資料;如果這裡改成 FK 直接指向
    那一筆,舊的報名紀錄會在 Admin 覆寫後被誤判成「報的是新的那一輪」。用快照可以讓
    已送出的報名紀錄維持跟當時實際報名的那一輪考試綁在一起,不受之後覆寫影響。

    同一位 Tutor 對同一個考試日期只能有一筆報名(`unique_together`),報名截止前重新
    送出會更新(覆蓋)前一次,比照 `QualificationDocument` 重新上傳覆蓋同一筆的既有
    慣例,不是保留每一次送出的歷史清單。
    """

    tutor = models.ForeignKey(User, on_delete=models.PROTECT, related_name="oral_exam_registrations")
    exam_date = models.DateField("考試日期 / Exam date")
    time_slot_1 = models.TimeField("可口試時段 1 / Available time slot 1")
    time_slot_2 = models.TimeField("可口試時段 2 / Available time slot 2")
    time_slot_3 = models.TimeField("可口試時段 3 / Available time slot 3")
    payment_proof = models.FileField(
        "繳費紀錄 / Payment proof", upload_to=_oral_exam_payment_proof_upload_to,
    )
    payment_proof_filename = models.CharField(max_length=255, blank=True)
    submitted_at = models.DateTimeField("報名時間 / Submitted at", auto_now_add=True)
    updated_at = models.DateTimeField("更新時間 / Updated at", auto_now=True)
    # 2026-10-07(使用者要求「報名清單最右側多一個欄位「登記」...如果admin檢查可以，
    # 狀態就顯示已登記，然後tutor介面就不能再更改時間段了」,當天再要求「登記狀態也加
    # 個撤回功能好了，以及「補件」按鈕和可以紀錄留言」):Admin 人工核對（例如對照繳費
    # 紀錄、確認真的有這個人）後決定「登記」或「補件」,`review_status` 非
    # `PENDING` 即鎖定——`CONFIRMED` 時 Tutor 不能再更改時段/繳費紀錄(見
    # `submit_oral_exam_registration()` 的鎖定檢查),`NEEDS_REVISION` 時則故意
    # 仍開放編輯,讓 Tutor 可以依 `review_note` 的留言補件重新送出。「撤回」會把狀態
    # 退回 `PENDING`、清空留言與核對人員/時間,比照口語能力審核撤回的既有慣例,沒有
    # 審核人員身分限制。
    review_status = models.CharField(
        "核對狀態 / Review status", max_length=20,
        choices=OralExamRegistrationReviewStatus.choices, default=OralExamRegistrationReviewStatus.PENDING,
    )
    review_note = models.TextField("留言 / Note", blank=True)
    reviewed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
        verbose_name="核對者 / Reviewed by",
    )
    reviewed_at = models.DateTimeField("核對時間 / Reviewed at", null=True, blank=True)
    # 2026-10-07(使用者要求「下方新增一個卡片「考試名單」...把已登記的tutor，根據他們的
    # 時間組合排列...考試順序」):Admin 按「安排考試」後由
    # `accounts/services.py::schedule_oral_exam_registrations()` 寫入,只排
    # `review_status=CONFIRMED` 的報名;兩者皆為空代表尚未排入(例如重新安排時排不進去
    # 的極端情況,或已被撤回登記)。重新按一次「安排考試」會整批重算覆蓋,不是疊加,
    # 比照本功能一路以來「只保留目前這一次結果」的慣例。
    exam_time = models.TimeField("考試時間 / Exam time", null=True, blank=True)
    exam_order = models.PositiveIntegerField("考試順序 / Exam order", null=True, blank=True)
    # 2026-10-09(使用者要求「考試名單右側多加兩個欄位：1. 可以讓助教放上google meet
    # 連結，2. 口語是否通過」):純文字連結,不限定 meet.google.com 網域——Admin 可能
    # 貼別的視訊連結(例如改用 Zoom),限定網域反而造成不便。口語是否通過**不是**存在
    # 這個欄位上,而是直接改這位 Tutor 的 `tutoring.models.QualificationDocument.status`
    # (見 `templates/dashboard/admin_v2_panels.html` 直接重用既有的
    # `accounts:review_qualification` 這個 view,不是另外寫一套)——使用者原話「如果按
    # 通過就代表口語能力證明直接通過」,語意上這就是口語能力審核本身,不是口試這個報名
    # 紀錄自己的狀態,所以不在這裡新增欄位。
    meet_link = models.URLField("Google Meet 連結 / Google Meet link", blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tutor", "exam_date"], name="one_oral_exam_registration_per_tutor_per_exam",
            )
        ]
        ordering = ["-submitted_at"]
        verbose_name = "線上口語考試報名 / Oral exam registration"
        verbose_name_plural = "線上口語考試報名 / Oral exam registrations"

    def __str__(self):
        return f"{self.tutor.username} · {self.exam_date}"

    def save(self, *args, **kwargs):
        if self.payment_proof and not self.payment_proof._committed and not self.payment_proof_filename:
            self.payment_proof_filename = Path(self.payment_proof.name).name
        super().save(*args, **kwargs)

    @property
    def is_confirmed(self):
        return self.review_status == OralExamRegistrationReviewStatus.CONFIRMED

    @property
    def needs_revision(self):
        return self.review_status == OralExamRegistrationReviewStatus.NEEDS_REVISION

    @property
    def time_slots(self):
        return [self.time_slot_1, self.time_slot_2, self.time_slot_3]

    @property
    def time_slot_ranges(self):
        """2026-10-06(使用者問「tutor選三個口試時段，在admin介面會出現＋30分嗎？」,
        確認要加上):每個時段存的只是起始時間,畫面上只顯示起始時間(例如「09:00」)
        容易讓 Admin 誤會成單一時間點,不是「這 30 分鐘內都可以」的意思——這裡算出
        結束時間(起始+30分),組成「09:00–09:30」這種區間字串。用 `datetime.combine()`
        接任意固定日期(`date.today()` 純粹借位,不代表任何實際日期)再加
        `timedelta(minutes=30)`,是因為 Python `datetime.time` 本身不支援直接加減。"""
        return [
            f"{slot.strftime('%H:%M')}–{(datetime.combine(date.today(), slot) + timedelta(minutes=30)).strftime('%H:%M')}"
            for slot in self.time_slots
        ]
