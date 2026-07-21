from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.models import AbstractUser, UserManager
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


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
    LOCAL = "LOCAL", "本地生 / Local student"
    OVERSEAS = "OVERSEAS", "僑生 / Overseas Chinese student"
    INTERNATIONAL = "INTERNATIONAL", "外籍生 / International student"


class ProgramSource(models.TextChoices):
    NTNU = "NTNU", "師大外籍生 / NTNU international student"
    MARYLAND = "MARYLAND", "馬里蘭大學 / University of Maryland"
    OTHER = "OTHER", "其他合作計畫 / Other partner program"
    NOT_APPLICABLE = "NA", "不適用 / Not applicable"


class AccountStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "啟用 / Active"
    SUSPENDED = "SUSPENDED", "停用 / Suspended"


class CSLUserManager(UserManager):
    def create_superuser(self, username, email=None, password=None, **extra_fields):
        extra_fields.setdefault("role", Role.ADMIN)
        extra_fields.setdefault("account_status", AccountStatus.ACTIVE)
        return super().create_superuser(username, email, password, **extra_fields)


class RosterEntry(models.Model):
    student_id = models.CharField("學號 / Student ID", max_length=24, unique=True)
    name_zh = models.CharField("中文姓名 / Chinese name", max_length=100)
    name_en = models.CharField("英文姓名 / English name", max_length=150, blank=True)
    role = models.CharField("身分 / Role", max_length=10, choices=Role.choices)
    education_level = models.CharField(
        "學制 / Degree level", max_length=12, choices=EducationLevel.choices, default=EducationLevel.NOT_APPLICABLE
    )
    identity_category = models.CharField(
        "學生類別 / Student category", max_length=16, choices=IdentityCategory.choices
    )
    program_source = models.CharField(
        "所屬計畫 / Program", max_length=16, choices=ProgramSource.choices, default=ProgramSource.NOT_APPLICABLE
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
        if self.role == Role.ADMIN:
            raise ValidationError("管理員不可由學生名冊建立。 / Admins cannot be created from the student roster.")
        if self.role == Role.TUTOR and self.education_level == EducationLevel.NOT_APPLICABLE:
            raise ValidationError({"education_level": "Tutor 必須設定學制。 / Tutor degree level is required."})
        if self.role == Role.TUTEE and self.program_source == ProgramSource.NOT_APPLICABLE:
            raise ValidationError({"program_source": "Tutee 必須設定所屬計畫。 / Tutee program is required."})

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
    QUESTION_CHOICES = [
        ("Q1", "我第一所就讀的小學名稱？ / What was the name of my first elementary school?"),
        ("Q2", "我童年最喜歡的食物？ / What was my favorite childhood food?"),
        ("Q3", "我最喜歡的一本書？ / What is my favorite book?"),
        ("Q4", "我第一位導師的姓氏？ / What was my first homeroom teacher's surname?"),
        ("Q5", "我最想造訪的城市？ / Which city would I most like to visit?"),
        ("Q6", "我自訂的一句秘密短語？ / What is my personal secret phrase?"),
        ("Q7", "我童年最喜歡的遊戲？ / What was my favorite childhood game?"),
        ("Q8", "我的第一隻寵物叫什麼名字？ / What was the name of my first pet?"),
        ("Q9", "我童年時的綽號？ / What was my childhood nickname?"),
        ("Q10", "我印象最深刻的旅行地點？ / What is my most memorable travel destination?"),
        ("Q11", "我最喜歡的一部電影？ / What is my favorite movie?"),
    ]

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
