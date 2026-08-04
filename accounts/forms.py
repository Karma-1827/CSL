from django import forms
from datetime import timedelta

from django.contrib.auth import password_validation
from django.contrib.auth.hashers import make_password
from django.contrib.auth.forms import AuthenticationForm, SetPasswordForm
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from tutoring.models import (
    Gender,
    QualificationDocument,
    QualificationStatus,
    TuteeProfile,
    TutorProfile,
    validate_qualification_file,
)

from .models import EducationLevel, IdentityCategory, RegistrationDraft, Role, RosterEntry, SecurityQuestionAnswer, User


def client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    return (forwarded.split(",")[0].strip() if forwarded else request.META.get("REMOTE_ADDR")) or None


def add_form_classes(form):
    for field in form.fields.values():
        if isinstance(field.widget, (forms.CheckboxSelectMultiple, forms.RadioSelect)):
            field.widget.attrs.setdefault("class", "choice-control")
        else:
            field.widget.attrs.setdefault("class", "form-control")
        field.error_messages["required"] = "此欄位為必填欄位"
    return form


class BilingualAuthenticationForm(AuthenticationForm):
    username = forms.CharField(
        label="學號 / Student ID",
        widget=forms.TextInput(attrs={"autocomplete": "username", "placeholder": "請輸入學號 / Enter student ID"}),
    )
    password = forms.CharField(
        label="密碼 / Password",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password", "placeholder": "請輸入密碼 / Enter password"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        add_form_classes(self)

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if user.account_status != "ACTIVE":
            raise ValidationError("此帳號目前已停用。 / This account is currently suspended.", code="inactive")

    def get_invalid_login_error(self):
        return ValidationError(
            "學號或密碼不正確。 / The student ID or password is incorrect.", code="invalid_login"
        )

    def _throttle_key(self, username):
        return f"login:{client_ip(self.request)}:{username.strip().upper()}"

    def clean(self):
        username = self.cleaned_data.get("username")
        if not username:
            return super().clean()
        throttle_key = self._throttle_key(username)
        if cache.get(throttle_key, 0) >= 5:
            raise ValidationError(
                "嘗試次數過多，請 15 分鐘後再試。 / Too many attempts. Please try again in 15 minutes.",
                code="throttled",
            )
        try:
            cleaned = super().clean()
        except ValidationError:
            cache.set(throttle_key, cache.get(throttle_key, 0) + 1, 900)
            raise
        cache.delete(throttle_key)
        return cleaned


class RegistrationForm(forms.Form):
    student_id = forms.CharField(
        label="學號 / Student ID",
        max_length=24,
        widget=forms.TextInput(attrs={"autocomplete": "username", "placeholder": "例如 / Example: 612840001"}),
    )
    password1 = forms.CharField(
        label="設定密碼 / Create password",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text="至少 10 個字元，避免使用常見密碼。\nUse at least 10 characters and avoid common passwords.",
    )
    password2 = forms.CharField(
        label="再次輸入密碼 / Confirm password",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    question_1 = forms.ChoiceField(label="安全問題一 / Security question 1", choices=SecurityQuestionAnswer.ACTIVE_QUESTION_CHOICES)
    answer_1 = forms.CharField(label="答案一 / Answer 1", min_length=3, widget=forms.PasswordInput(attrs={"autocomplete": "off"}))
    question_2 = forms.ChoiceField(label="安全問題二 / Security question 2", choices=SecurityQuestionAnswer.ACTIVE_QUESTION_CHOICES)
    answer_2 = forms.CharField(label="答案二 / Answer 2", min_length=3, widget=forms.PasswordInput(attrs={"autocomplete": "off"}))
    question_3 = forms.ChoiceField(label="安全問題三 / Security question 3", choices=SecurityQuestionAnswer.ACTIVE_QUESTION_CHOICES)
    answer_3 = forms.CharField(label="答案三 / Answer 3", min_length=3, widget=forms.PasswordInput(attrs={"autocomplete": "off"}))
    agree = forms.BooleanField(
        label="我確認資料正確，並同意依系統目的使用。 / I confirm the information and consent to its use for this system.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        add_form_classes(self)
        self.fields["agree"].widget.attrs["class"] = "form-check-input"
        self.fields["question_1"].initial = "Q1"
        self.fields["question_2"].initial = "Q2"
        self.fields["question_3"].initial = "Q3"

    def clean_student_id(self):
        student_id = self.cleaned_data["student_id"].strip().upper()
        try:
            roster = RosterEntry.objects.get(student_id=student_id, is_enabled=True)
        except RosterEntry.DoesNotExist:
            raise ValidationError("找不到註冊學號，請聯絡系辦。\nStudent ID not found. Please contact the department office.")
        if roster.is_claimed or User.objects.filter(username=student_id).exists():
            raise ValidationError("此學號已完成註冊。 / This student ID has already been registered.")
        return student_id

    def clean(self):
        cleaned = super().clean()
        questions = [cleaned.get(f"question_{index}") for index in range(1, 4)]
        if all(questions) and len(set(questions)) != 3:
            self.add_error("question_3", "三題不可重複。 / Please choose three different questions.")
        password1 = cleaned.get("password1")
        password2 = cleaned.get("password2")
        if password1 and password2:
            if password1 != password2:
                self.add_error("password2", "兩次密碼不一致。 / The two passwords do not match.")
            else:
                provisional = User(username=cleaned.get("student_id", ""))
                try:
                    password_validation.validate_password(password1, provisional)
                except ValidationError as error:
                    self.add_error("password1", error)
        return cleaned

    @transaction.atomic
    def save(self):
        roster = RosterEntry.objects.select_for_update().get(student_id=self.cleaned_data["student_id"])
        if roster.is_claimed or User.objects.filter(username=roster.student_id).exists():
            raise ValidationError("此學號已完成註冊。 / This student ID has already been registered.")
        user = User.objects.create_user(
            username=roster.student_id,
            password=self.cleaned_data["password1"],
            role=roster.role,
            roster_entry=roster,
            name_zh=roster.name_zh,
            name_en=roster.name_en,
        )
        questions = SecurityQuestionAnswer(
            user=user,
            question_1=self.cleaned_data["question_1"],
            question_2=self.cleaned_data["question_2"],
            question_3=self.cleaned_data["question_3"],
        )
        questions.set_answers([self.cleaned_data["answer_1"], self.cleaned_data["answer_2"], self.cleaned_data["answer_3"]])
        questions.save()
        roster.claimed_at = timezone.now()
        roster.save(update_fields=["claimed_at", "updated_at"])
        return user


DAYS = [
    ("MON", "星期一 / Monday"),
    ("TUE", "星期二 / Tuesday"),
    ("WED", "星期三 / Wednesday"),
    ("THU", "星期四 / Thursday"),
    ("FRI", "星期五 / Friday"),
]
TIME_SLOTS = [
    ("09:00-11:00", "09:00–11:00"),
    ("11:00-13:00", "11:00–13:00"),
    ("13:00-15:00", "13:00–15:00"),
    ("15:00-17:00", "15:00–17:00"),
    ("17:00-19:00", "17:00–19:00"),
    ("OTHER", "其他 / Other"),
]
SKILL_CHOICES = [
    ("LISTENING", "聽力 / Listening"),
    ("SPEAKING", "口說 / Speaking"),
    ("READING", "閱讀 / Reading"),
    ("WRITING", "寫作 / Writing"),
]
LEVEL_CHOICES = [(number, str(number)) for number in range(1, 6)]
GENDER_CHOICES = [
    ("", "請選擇 / Select"),
    (Gender.MALE, "男 / Male"),
    (Gender.FEMALE, "女 / Female"),
    (Gender.NON_BINARY, "非二元 / Non-binary"),
]
OVERALL_LEVEL_CHOICES = [
    ("UNKNOWN", "不知道 / Unknown"),
    ("N", "TOCFL N"),
    ("A1", "TOCFL A1"),
    ("A2", "TOCFL A2"),
    ("B1", "TOCFL B1"),
    ("B2", "TOCFL B2"),
    ("C1", "TOCFL C1"),
    ("C2", "TOCFL C2"),
]


class RegistrationLookupForm(forms.Form):
    student_id = forms.CharField(
        label="學號 / Student ID",
        max_length=24,
        widget=forms.TextInput(attrs={"autocomplete": "username", "placeholder": "例如 / Example: 612840001"}),
    )
    password1 = forms.CharField(
        label="設定密碼 / Create password",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text="至少 10 個字元，避免使用常見密碼。\nUse at least 10 characters and avoid common passwords.",
    )
    password2 = forms.CharField(
        label="再次輸入密碼 / Confirm password",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        add_form_classes(self)

    def clean_student_id(self):
        student_id = self.cleaned_data["student_id"].strip().upper()
        try:
            roster = RosterEntry.objects.get(student_id=student_id, is_enabled=True)
        except RosterEntry.DoesNotExist:
            raise ValidationError(
                "找不到註冊學號，請聯絡系辦。\nStudent ID not found. Please contact the department office."
            )
        if roster.is_claimed or User.objects.filter(username=student_id).exists():
            raise ValidationError("此學號已完成註冊。 / This student ID has already been registered.")
        if roster.role not in {Role.TUTOR, Role.TUTEE}:
            raise ValidationError("此名冊身分無法公開註冊。 / This roster role cannot register here.")
        self.roster = roster
        return student_id

    def clean(self):
        cleaned = super().clean()
        password1 = cleaned.get("password1")
        password2 = cleaned.get("password2")
        if password1 and password2:
            if password1 != password2:
                self.add_error("password2", "兩次密碼不一致。 / The two passwords do not match.")
            else:
                provisional = User(username=cleaned.get("student_id", ""))
                try:
                    password_validation.validate_password(password1, provisional)
                except ValidationError as error:
                    self.add_error("password1", error)
        return cleaned

    def save_draft(self):
        draft, _ = RegistrationDraft.objects.update_or_create(
            roster_entry=self.roster,
            defaults={
                "password_hash": make_password(self.cleaned_data["password1"]),
                "expires_at": timezone.now() + timedelta(minutes=30),
            },
        )
        return draft


class BaseRoleRegistrationForm(forms.Form):
    name_zh = forms.CharField(label="中文姓名 / Chinese name", max_length=100)
    name_en = forms.CharField(label="英文姓名（選填） / English name (optional)", max_length=150, required=False)
    nickname = forms.CharField(label="暱稱（選填） / Nickname (optional)", max_length=50, required=False)
    identity_category = forms.ChoiceField(label="身份別 / Identity category", choices=IdentityCategory.choices)
    phone = forms.CharField(label="電話（選填） / Phone (optional)", max_length=30, required=False)
    email = forms.EmailField(label="Email", max_length=254)
    gender = forms.ChoiceField(label="性別 / Gender", choices=GENDER_CHOICES)
    native_language = forms.CharField(
        label="母語 / Native language",
        max_length=80,
        widget=forms.Select(
            attrs={"data-profile-options": "language"},
            choices=[("", "請選擇母語 / Select native language")],
        ),
    )
    nationality = forms.CharField(
        label="國家／地區 / Country or region",
        max_length=80,
        widget=forms.Select(
            attrs={"data-profile-options": "region"},
            choices=[("", "請選擇國家／地區 / Select country or region")],
        ),
    )
    department = forms.CharField(label="系所 / Department", max_length=150)
    question_1 = forms.ChoiceField(label="安全問題一 / Security question 1", choices=SecurityQuestionAnswer.ACTIVE_QUESTION_CHOICES)
    answer_1 = forms.CharField(label="答案一 / Answer 1", min_length=3, widget=forms.PasswordInput(attrs={"autocomplete": "off"}))
    question_2 = forms.ChoiceField(label="安全問題二 / Security question 2", choices=SecurityQuestionAnswer.ACTIVE_QUESTION_CHOICES)
    answer_2 = forms.CharField(label="答案二 / Answer 2", min_length=3, widget=forms.PasswordInput(attrs={"autocomplete": "off"}))
    question_3 = forms.ChoiceField(label="安全問題三 / Security question 3", choices=SecurityQuestionAnswer.ACTIVE_QUESTION_CHOICES)
    answer_3 = forms.CharField(label="答案三 / Answer 3", min_length=3, widget=forms.PasswordInput(attrs={"autocomplete": "off"}))
    agree = forms.BooleanField(
        label="我確認資料正確，並同意依系統目的使用。 / I confirm the information and consent to its use for this system."
    )

    expected_role = None

    def __init__(self, *args, roster, draft, **kwargs):
        self.roster = roster
        self.draft = draft
        initial = kwargs.pop("initial", {})
        if roster.name_zh:
            initial.setdefault("name_zh", roster.name_zh)
        if roster.name_en:
            initial.setdefault("name_en", roster.name_en)
        if roster.identity_category:
            initial.setdefault("identity_category", roster.identity_category)
        kwargs["initial"] = initial
        super().__init__(*args, **kwargs)
        add_form_classes(self)
        if self.is_bound:
            self.fields["native_language"].widget.attrs["data-current-value"] = self.data.get("native_language", "")
            self.fields["nationality"].widget.attrs["data-current-value"] = self.data.get("nationality", "")
        self.fields["agree"].widget.attrs["class"] = "form-check-input"
        for field_name in ("question_1", "question_2", "question_3"):
            self.fields[field_name].initial = field_name.replace("question_", "Q")
        if roster.role != self.expected_role:
            raise ValueError("Registration form role does not match roster role")

    def clean(self):
        cleaned = super().clean()
        questions = [cleaned.get(f"question_{index}") for index in range(1, 4)]
        if all(questions) and len(set(questions)) != 3:
            self.add_error("question_3", "三題不可重複。 / Please choose three different questions.")
        return cleaned

    def create_user(self):
        roster = RosterEntry.objects.select_for_update().get(pk=self.roster.pk)
        if roster.is_claimed or User.objects.filter(username=roster.student_id).exists():
            raise ValidationError("此學號已完成註冊。 / This student ID has already been registered.")
        if self.draft.is_expired or self.draft.roster_entry_id != roster.pk:
            raise ValidationError("註冊資料已逾時，請重新開始。 / Registration expired. Please start again.")
        roster.name_zh = self.cleaned_data["name_zh"]
        roster.name_en = self.cleaned_data.get("name_en", "")
        roster.identity_category = self.cleaned_data["identity_category"]
        if "education_level" in self.cleaned_data:
            roster.education_level = self.cleaned_data["education_level"]
        roster.full_clean()
        roster.save()
        user = User(
            username=roster.student_id,
            password=self.draft.password_hash,
            role=roster.role,
            roster_entry=roster,
            name_zh=roster.name_zh,
            name_en=roster.name_en,
            nickname=self.cleaned_data.get("nickname", ""),
            phone=self.cleaned_data["phone"],
            email=self.cleaned_data["email"],
        )
        user.save()
        questions = SecurityQuestionAnswer(
            user=user,
            question_1=self.cleaned_data["question_1"],
            question_2=self.cleaned_data["question_2"],
            question_3=self.cleaned_data["question_3"],
        )
        questions.set_answers([self.cleaned_data["answer_1"], self.cleaned_data["answer_2"], self.cleaned_data["answer_3"]])
        questions.save()
        roster.claimed_at = timezone.now()
        roster.save(update_fields=["claimed_at", "updated_at"])
        return user


class TutorRegistrationForm(BaseRoleRegistrationForm):
    expected_role = Role.TUTOR
    education_level = forms.ChoiceField(
        label="學制 / Degree level",
        choices=[choice for choice in EducationLevel.choices if choice[0] != EducationLevel.NOT_APPLICABLE],
    )
    level_listening = forms.TypedChoiceField(label="聽力 / Listening", choices=LEVEL_CHOICES, coerce=int, widget=forms.RadioSelect)
    level_speaking = forms.TypedChoiceField(label="口說 / Speaking", choices=LEVEL_CHOICES, coerce=int, widget=forms.RadioSelect)
    level_reading = forms.TypedChoiceField(label="閱讀 / Reading", choices=LEVEL_CHOICES, coerce=int, widget=forms.RadioSelect)
    level_writing = forms.TypedChoiceField(label="寫作 / Writing", choices=LEVEL_CHOICES, coerce=int, widget=forms.RadioSelect)
    teaching_notes = forms.CharField(
        label="教學簡介 / Teaching notes", required=False, widget=forms.Textarea(attrs={"rows": 4})
    )
    available_days = forms.MultipleChoiceField(
        label="可配合星期 / Available days", choices=DAYS, widget=forms.CheckboxSelectMultiple
    )
    available_time_slots = forms.MultipleChoiceField(
        label="可配合時段 / Available time slots", choices=TIME_SLOTS, widget=forms.CheckboxSelectMultiple
    )
    qualification_file = forms.FileField(
        label="口語能力證明 / Oral proficiency document",
        required=False,
        validators=[validate_qualification_file],
        widget=forms.ClearableFileInput(attrs={"accept": ".pdf,.jpg,.jpeg,.png"}),
        help_text="目前可先略過；PDF、JPG、PNG，最大 1 MB。\nOptional for now; PDF, JPG, or PNG, up to 1 MB.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.roster.education_level != EducationLevel.NOT_APPLICABLE:
            self.fields["education_level"].initial = self.roster.education_level

    @transaction.atomic
    def save(self):
        user = self.create_user()
        TutorProfile.objects.create(
            tutor=user,
            gender=self.cleaned_data["gender"],
            native_language=self.cleaned_data["native_language"],
            nationality=self.cleaned_data["nationality"],
            department=self.cleaned_data["department"],
            level_listening=self.cleaned_data["level_listening"],
            level_speaking=self.cleaned_data["level_speaking"],
            level_reading=self.cleaned_data["level_reading"],
            level_writing=self.cleaned_data["level_writing"],
            teaching_notes=self.cleaned_data["teaching_notes"],
            available_days=self.cleaned_data["available_days"],
            available_time_slots=self.cleaned_data["available_time_slots"],
        )
        upload = self.cleaned_data.get("qualification_file")
        if upload:
            QualificationDocument.objects.create(
                tutor=user,
                file=upload,
                original_filename=upload.name,
                status=QualificationStatus.PENDING,
            )
        self.draft.delete()
        return user


class TuteeRegistrationForm(BaseRoleRegistrationForm):
    expected_role = Role.TUTEE
    overall_level = forms.ChoiceField(
        label="整體華語程度 / Overall Chinese level",
        choices=OVERALL_LEVEL_CHOICES,
    )
    learning_duration = forms.ChoiceField(
        label="華語學習時間 / Learning duration",
        choices=[
            ("", "請選擇學習時間 / Select learning duration"),
            ("LT_3_MONTHS", "3 個月以下 / Less than 3 months"),
            ("3_TO_6_MONTHS", "3 個月～半年 / 3–6 months"),
            ("6_TO_12_MONTHS", "半年～1 年 / 6–12 months"),
            ("1_TO_2_YEARS", "1～2 年 / 1–2 years"),
            ("GT_2_YEARS", "2 年以上 / More than 2 years"),
        ],
    )
    level_listening = forms.TypedChoiceField(label="聽力 / Listening", choices=LEVEL_CHOICES, coerce=int, initial=3, widget=forms.RadioSelect)
    level_speaking = forms.TypedChoiceField(label="口說 / Speaking", choices=LEVEL_CHOICES, coerce=int, initial=3, widget=forms.RadioSelect)
    level_reading = forms.TypedChoiceField(label="閱讀 / Reading", choices=LEVEL_CHOICES, coerce=int, initial=3, widget=forms.RadioSelect)
    level_writing = forms.TypedChoiceField(label="寫作 / Writing", choices=LEVEL_CHOICES, coerce=int, initial=3, widget=forms.RadioSelect)
    target_skills = forms.MultipleChoiceField(
        label="希望加強項目 / Skills to improve", choices=SKILL_CHOICES, widget=forms.CheckboxSelectMultiple
    )
    skills_to_improve = forms.CharField(
        label="學習需求說明 / Learning needs", required=False, widget=forms.Textarea(attrs={"rows": 4})
    )
    preferred_days = forms.MultipleChoiceField(
        label="偏好星期 / Preferred days", choices=DAYS, widget=forms.CheckboxSelectMultiple
    )
    preferred_time_slots = forms.MultipleChoiceField(
        label="偏好時段 / Preferred time slots", choices=TIME_SLOTS, widget=forms.CheckboxSelectMultiple
    )

    @transaction.atomic
    def save(self):
        user = self.create_user()
        TuteeProfile.objects.create(
            tutee=user,
            gender=self.cleaned_data["gender"],
            native_language=self.cleaned_data["native_language"],
            nationality=self.cleaned_data["nationality"],
            department=self.cleaned_data["department"],
            overall_level=self.cleaned_data["overall_level"],
            learning_duration=self.cleaned_data["learning_duration"],
            level_listening=self.cleaned_data["level_listening"],
            level_speaking=self.cleaned_data["level_speaking"],
            level_reading=self.cleaned_data["level_reading"],
            level_writing=self.cleaned_data["level_writing"],
            target_skills=self.cleaned_data["target_skills"],
            skills_to_improve=self.cleaned_data["skills_to_improve"],
            preferred_days=self.cleaned_data["preferred_days"],
            preferred_time_slots=self.cleaned_data["preferred_time_slots"],
        )
        self.draft.delete()
        return user


class RecoveryVerificationForm(forms.Form):
    student_id = forms.CharField(label="學號 / Student ID", max_length=24)
    question_1 = forms.ChoiceField(label="安全問題一 / Security question 1", choices=SecurityQuestionAnswer.QUESTION_CHOICES)
    answer_1 = forms.CharField(label="答案一 / Answer 1", widget=forms.PasswordInput(attrs={"autocomplete": "off"}))
    question_2 = forms.ChoiceField(label="安全問題二 / Security question 2", choices=SecurityQuestionAnswer.QUESTION_CHOICES)
    answer_2 = forms.CharField(label="答案二 / Answer 2", widget=forms.PasswordInput(attrs={"autocomplete": "off"}))
    question_3 = forms.ChoiceField(label="安全問題三 / Security question 3", choices=SecurityQuestionAnswer.QUESTION_CHOICES)
    answer_3 = forms.CharField(label="答案三 / Answer 3", widget=forms.PasswordInput(attrs={"autocomplete": "off"}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        add_form_classes(self)


class BilingualSetPasswordForm(SetPasswordForm):
    new_password1 = forms.CharField(
        label="新密碼 / New password", strip=False, widget=forms.PasswordInput(attrs={"autocomplete": "new-password"})
    )
    new_password2 = forms.CharField(
        label="再次輸入新密碼 / Confirm new password", strip=False, widget=forms.PasswordInput(attrs={"autocomplete": "new-password"})
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        add_form_classes(self)


class QualificationUploadForm(forms.ModelForm):
    class Meta:
        model = QualificationDocument
        fields = ["file"]
        widgets = {"file": forms.ClearableFileInput(attrs={"accept": ".pdf,.jpg,.jpeg,.png"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        add_form_classes(self)
        self.fields["file"].help_text = "PDF、JPG、PNG，最大 1 MB。\nPDF, JPG, or PNG, up to 1 MB."


class TutorProfileEditForm(forms.Form):
    phone = forms.CharField(label="電話（選填） / Phone (optional)", max_length=30, required=False)
    nickname = forms.CharField(label="暱稱（選填） / Nickname (optional)", max_length=50, required=False)
    email = forms.EmailField(label="Email", max_length=254)
    gender = forms.ChoiceField(label="性別 / Gender", choices=GENDER_CHOICES)
    native_language = forms.CharField(
        label="母語 / Native language",
        max_length=80,
        widget=forms.Select(
            attrs={"data-profile-options": "language"},
            choices=[("", "請選擇母語 / Select native language")],
        ),
    )
    nationality = forms.CharField(
        label="國家／地區 / Country or region",
        max_length=80,
        widget=forms.Select(
            attrs={"data-profile-options": "region"},
            choices=[("", "請選擇國家／地區 / Select country or region")],
        ),
    )
    department = forms.CharField(label="系所 / Department", max_length=150)
    level_listening = forms.TypedChoiceField(label="聽力 / Listening", choices=LEVEL_CHOICES, coerce=int, widget=forms.RadioSelect)
    level_speaking = forms.TypedChoiceField(label="口說 / Speaking", choices=LEVEL_CHOICES, coerce=int, widget=forms.RadioSelect)
    level_reading = forms.TypedChoiceField(label="閱讀 / Reading", choices=LEVEL_CHOICES, coerce=int, widget=forms.RadioSelect)
    level_writing = forms.TypedChoiceField(label="寫作 / Writing", choices=LEVEL_CHOICES, coerce=int, widget=forms.RadioSelect)
    teaching_notes = forms.CharField(
        label="教學簡介 / Teaching notes", required=False, widget=forms.Textarea(attrs={"rows": 4})
    )
    available_days = forms.MultipleChoiceField(
        label="可配合星期 / Available days", choices=DAYS, widget=forms.CheckboxSelectMultiple
    )
    available_time_slots = forms.MultipleChoiceField(
        label="可配合時段 / Available time slots", choices=TIME_SLOTS, widget=forms.CheckboxSelectMultiple
    )

    profile_fields = (
        "gender", "native_language", "nationality", "department",
        "level_listening", "level_speaking", "level_reading", "level_writing",
        "teaching_notes", "available_days", "available_time_slots",
    )

    def __init__(self, *args, profile, user, **kwargs):
        self.profile_instance = profile
        self.user = user
        kwargs.setdefault(
            "initial",
            {
                "phone": user.phone,
                "nickname": user.nickname,
                "email": user.email,
                **{name: getattr(profile, name) for name in self.profile_fields},
            },
        )
        super().__init__(*args, **kwargs)
        add_form_classes(self)
        current_language = self.data.get("native_language") if self.is_bound else self.initial.get("native_language")
        current_nationality = self.data.get("nationality") if self.is_bound else self.initial.get("nationality")
        self.fields["native_language"].widget.attrs["data-current-value"] = current_language or ""
        self.fields["nationality"].widget.attrs["data-current-value"] = current_nationality or ""

    def save(self):
        changed = []
        user_fields = []
        for field_name in ("phone", "nickname", "email"):
            if getattr(self.user, field_name) != self.cleaned_data[field_name]:
                changed.append(field_name)
                user_fields.append(field_name)
                setattr(self.user, field_name, self.cleaned_data[field_name])
        if user_fields:
            self.user.save(update_fields=user_fields)
        for field_name in self.profile_fields:
            if getattr(self.profile_instance, field_name) != self.cleaned_data[field_name]:
                changed.append(field_name)
                setattr(self.profile_instance, field_name, self.cleaned_data[field_name])
        if changed:
            self.profile_instance.full_clean()
            self.profile_instance.save()
        return changed


class TuteeProfileEditForm(forms.Form):
    phone = forms.CharField(label="電話（選填） / Phone (optional)", max_length=30, required=False)
    nickname = forms.CharField(label="暱稱（選填） / Nickname (optional)", max_length=50, required=False)
    email = forms.EmailField(label="Email", max_length=254)
    gender = forms.ChoiceField(label="性別 / Gender", choices=GENDER_CHOICES)
    native_language = forms.CharField(
        label="母語 / Native language",
        max_length=80,
        widget=forms.Select(
            attrs={"data-profile-options": "language"},
            choices=[("", "請選擇母語 / Select native language")],
        ),
    )
    nationality = forms.CharField(
        label="國家／地區 / Country or region",
        max_length=80,
        widget=forms.Select(
            attrs={"data-profile-options": "region"},
            choices=[("", "請選擇國家／地區 / Select country or region")],
        ),
    )
    department = forms.CharField(label="系所 / Department", max_length=150)
    overall_level = forms.ChoiceField(
        label="整體華語程度 / Overall Chinese level",
        choices=OVERALL_LEVEL_CHOICES,
    )
    learning_duration = forms.ChoiceField(
        label="華語學習時間 / Learning duration",
        choices=[
            ("", "請選擇學習時間 / Select learning duration"),
            ("LT_3_MONTHS", "3 個月以下 / Less than 3 months"),
            ("3_TO_6_MONTHS", "3 個月～半年 / 3–6 months"),
            ("6_TO_12_MONTHS", "半年～1 年 / 6–12 months"),
            ("1_TO_2_YEARS", "1～2 年 / 1–2 years"),
            ("GT_2_YEARS", "2 年以上 / More than 2 years"),
        ],
    )
    level_listening = forms.TypedChoiceField(label="聽力 / Listening", choices=LEVEL_CHOICES, coerce=int, widget=forms.RadioSelect)
    level_speaking = forms.TypedChoiceField(label="口說 / Speaking", choices=LEVEL_CHOICES, coerce=int, widget=forms.RadioSelect)
    level_reading = forms.TypedChoiceField(label="閱讀 / Reading", choices=LEVEL_CHOICES, coerce=int, widget=forms.RadioSelect)
    level_writing = forms.TypedChoiceField(label="寫作 / Writing", choices=LEVEL_CHOICES, coerce=int, widget=forms.RadioSelect)
    target_skills = forms.MultipleChoiceField(
        label="希望加強項目 / Skills to improve", choices=SKILL_CHOICES, widget=forms.CheckboxSelectMultiple
    )
    skills_to_improve = forms.CharField(
        label="學習需求說明 / Learning needs", required=False, widget=forms.Textarea(attrs={"rows": 4})
    )
    preferred_days = forms.MultipleChoiceField(
        label="偏好星期 / Preferred days", choices=DAYS, widget=forms.CheckboxSelectMultiple
    )
    preferred_time_slots = forms.MultipleChoiceField(
        label="偏好時段 / Preferred time slots", choices=TIME_SLOTS, widget=forms.CheckboxSelectMultiple
    )

    profile_fields = (
        "gender", "native_language", "nationality", "department",
        "overall_level", "learning_duration",
        "level_listening", "level_speaking", "level_reading", "level_writing",
        "target_skills", "skills_to_improve", "preferred_days", "preferred_time_slots",
    )

    def __init__(self, *args, profile, user, **kwargs):
        self.profile_instance = profile
        self.user = user
        kwargs.setdefault(
            "initial",
            {
                "phone": user.phone,
                "nickname": user.nickname,
                "email": user.email,
                **{name: getattr(profile, name) for name in self.profile_fields},
            },
        )
        super().__init__(*args, **kwargs)
        add_form_classes(self)
        current_language = self.data.get("native_language") if self.is_bound else self.initial.get("native_language")
        current_nationality = self.data.get("nationality") if self.is_bound else self.initial.get("nationality")
        self.fields["native_language"].widget.attrs["data-current-value"] = current_language or ""
        self.fields["nationality"].widget.attrs["data-current-value"] = current_nationality or ""

    def save(self):
        changed = []
        user_fields = []
        for field_name in ("phone", "nickname", "email"):
            if getattr(self.user, field_name) != self.cleaned_data[field_name]:
                changed.append(field_name)
                user_fields.append(field_name)
                setattr(self.user, field_name, self.cleaned_data[field_name])
        if user_fields:
            self.user.save(update_fields=user_fields)
        for field_name in self.profile_fields:
            if getattr(self.profile_instance, field_name) != self.cleaned_data[field_name]:
                changed.append(field_name)
                setattr(self.profile_instance, field_name, self.cleaned_data[field_name])
        if changed:
            self.profile_instance.full_clean()
            self.profile_instance.save()
        return changed


class RosterImportForm(forms.Form):
    file = forms.FileField(widget=forms.ClearableFileInput(attrs={"accept": ".csv,.xlsx"}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        add_form_classes(self)
        self.fields["file"].help_text = "CSV 或 Excel（.xlsx），需含標題列。\nCSV or Excel (.xlsx), with a header row."

    def clean_file(self):
        upload = self.cleaned_data["file"]
        name = upload.name.lower()
        if not (name.endswith(".csv") or name.endswith(".xlsx")):
            raise ValidationError("僅支援 .csv 或 .xlsx 檔案。 / Only .csv or .xlsx files are supported.")
        return upload
