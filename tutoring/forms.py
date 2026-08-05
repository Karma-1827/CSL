from datetime import time

from django import forms
from django.core.exceptions import ValidationError

from accounts.forms import SKILL_CHOICES
from accounts.models import PartnerProgram, Role, User

from .models import (
    ClassAlert,
    ClassRecord,
    ClassSession,
    IncidentReport,
    Pairing,
    PairingMessage,
    PairingStatus,
    Semester,
)
from .reporting import tutor_available_programs


class FiveMinuteTimeWidget(forms.MultiWidget):
    def __init__(self, attrs=None):
        widgets = (
            forms.Select(choices=[(f"{hour:02d}", f"{hour:02d}") for hour in range(24)], attrs={"aria-label": "小時 / Hour"}),
            forms.Select(choices=[(f"{minute:02d}", f"{minute:02d}") for minute in range(0, 60, 5)], attrs={"aria-label": "分鐘 / Minute"}),
        )
        super().__init__(widgets, attrs)

    def decompress(self, value):
        if isinstance(value, time):
            return [f"{value.hour:02d}", f"{value.minute:02d}"]
        if isinstance(value, str) and ":" in value:
            hour, minute = value.split(":", 1)
            return [hour.zfill(2), minute[:2].zfill(2)]
        return ["09", "00"]


class FiveMinuteTimeField(forms.MultiValueField):
    widget = FiveMinuteTimeWidget

    def __init__(self, *args, **kwargs):
        fields = (forms.IntegerField(min_value=0, max_value=23), forms.IntegerField(min_value=0, max_value=55))
        super().__init__(fields=fields, require_all_fields=True, *args, **kwargs)

    def compress(self, values):
        if not values or len(values) != 2:
            raise forms.ValidationError("請選擇開始時間。 / Select a start time.")
        hour, minute = values
        if minute % 5:
            raise forms.ValidationError("分鐘須為 5 分鐘的倍數。 / Minutes must use five-minute increments.")
        return time(hour, minute)


class ScheduleClassForm(forms.Form):
    pairing = forms.ModelChoiceField(label="學生 / Student", queryset=Pairing.objects.none())
    class_date = forms.DateField(label="上課日期 / Class date", widget=forms.DateInput(attrs={"type": "date"}))
    start_time = FiveMinuteTimeField(label="開始時間 / Start time")
    duration = forms.ChoiceField(label="時數 / Duration", choices=ClassSession.DURATION_CHOICES)
    repeat_weekly = forms.BooleanField(label="每週重複 / Repeat weekly", required=False)
    repeat_until = forms.DateField(
        label="重複至 / Repeat until", required=False, widget=forms.DateInput(attrs={"type": "date"})
    )

    def __init__(self, *args, tutor=None, **kwargs):
        super().__init__(*args, **kwargs)
        if tutor:
            self.fields["pairing"].queryset = Pairing.objects.filter(
                tutor=tutor, status=PairingStatus.ACTIVE
            ).select_related("tutee", "semester")

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("repeat_weekly") and not cleaned.get("repeat_until"):
            self.add_error("repeat_until", "每週重複時請選擇結束日期。 / Select an end date for weekly repeats.")
        return cleaned


class RescheduleClassForm(forms.Form):
    class_date = forms.DateField(label="新上課日期 / New class date", widget=forms.DateInput(attrs={"type": "date"}))
    start_time = FiveMinuteTimeField(label="新開始時間 / New start time")
    duration = forms.ChoiceField(label="時數 / Duration", choices=ClassSession.DURATION_CHOICES)
    scope = forms.ChoiceField(
        label="修改範圍 / Edit scope",
        choices=(("single", "只修改這堂 / This class only"), ("following", "這堂及之後 / This and following")),
    )

    def __init__(self, *args, session=None, **kwargs):
        super().__init__(*args, **kwargs)
        if session and not session.recurrence_group:
            self.fields["scope"].choices = (("single", "只修改這堂 / This class only"),)


class ClassRecordForm(forms.ModelForm):
    skills_practiced = forms.MultipleChoiceField(
        label="授課類型 / Skills practiced", choices=SKILL_CHOICES, required=False, widget=forms.CheckboxSelectMultiple
    )

    class Meta:
        model = ClassRecord
        fields = ("location", "topic", "content", "skills_practiced", "remarks", "attachment")
        widgets = {
            "content": forms.Textarea(attrs={"rows": 5, "maxlength": 2000}),
            "remarks": forms.Textarea(attrs={"rows": 5, "maxlength": 2000}),
            "attachment": forms.FileInput(attrs={"accept": ".pdf,.jpg,.jpeg,.png"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["attachment"].help_text = "PDF、JPG、PNG，最大 500 KB（選填）。\nPDF, JPG, or PNG, up to 500 KB (optional)."


class ClassAlertForm(forms.ModelForm):
    class Meta:
        model = ClassAlert
        fields = ("reason", "note")
        widgets = {"note": forms.Textarea(attrs={"rows": 3})}


class IncidentReportForm(forms.ModelForm):
    class Meta:
        model = IncidentReport
        fields = ("category", "content")
        widgets = {"content": forms.Textarea(attrs={"rows": 3})}


class MakeupReasonForm(forms.Form):
    reason = forms.CharField(
        label="補登原因 / Reason for makeup entry",
        widget=forms.Textarea(attrs={"rows": 3}),
        min_length=5,
    )


class SemesterSettingsForm(forms.ModelForm):
    """Admin edit form. `program` stays optional here so existing legacy (program=None)
    periods can still be renamed/rescheduled without being forced to retroactively pick a
    program — see Semester.program's docstring-comment in models.py."""

    applicable_users = forms.ModelMultipleChoiceField(
        label="適用對象（留空＝該計畫全部帳號） / Applicable users (blank = everyone in the program)",
        queryset=User.objects.filter(role__in=(Role.TUTOR, Role.TUTEE), is_active=True).order_by("username"),
        required=False,
    )

    class Meta:
        model = Semester
        fields = (
            "name_zh", "name_en", "starts_on", "ends_on", "is_active", "program", "applicable_users",
        )
        widgets = {
            "starts_on": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "ends_on": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["program"].required = False
        self.fields["program"].empty_label = "（沿用舊版共用期間，不指定計畫） / (legacy shared period, no program)"

    def clean(self):
        cleaned = super().clean()
        users = cleaned.get("applicable_users")
        if users is not None:
            candidate = Semester(program=cleaned.get("program"))
            try:
                candidate.validate_applicable_users(users)
            except ValidationError as error:
                self.add_error("applicable_users", error)
        return cleaned


class SemesterCreateForm(forms.ModelForm):
    """Admin creation form: new semesters are enabled automatically. Unlike the edit form,
    `program` is required — new periods should always be scoped to a partner program going
    forward (see MEETING_CHANGE_REQUIREMENTS_2026-08-04.md item 15)."""

    applicable_users = forms.ModelMultipleChoiceField(
        label="適用對象（留空＝該計畫全部帳號） / Applicable users (blank = everyone in the program)",
        queryset=User.objects.filter(role__in=(Role.TUTOR, Role.TUTEE), is_active=True).order_by("username"),
        required=False,
    )

    class Meta:
        model = Semester
        fields = ("name_zh", "name_en", "starts_on", "ends_on", "program", "applicable_users")
        widgets = {
            "starts_on": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "ends_on": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["program"].required = True
        self.fields["program"].queryset = PartnerProgram.objects.filter(is_active=True).order_by("name_zh")

    def clean(self):
        cleaned = super().clean()
        users = cleaned.get("applicable_users")
        if users is not None:
            candidate = Semester(program=cleaned.get("program"))
            try:
                candidate.validate_applicable_users(users)
            except ValidationError as error:
                self.add_error("applicable_users", error)
        return cleaned


class PairingMessageForm(forms.ModelForm):
    class Meta:
        model = PairingMessage
        fields = ("body",)
        widgets = {
            "body": forms.Textarea(attrs={
                "rows": 3,
                "maxlength": 2000,
                "placeholder": "輸入訊息… / Write a message…",
            })
        }


class HoursDownloadForm(forms.Form):
    MODE_CHOICES = (("semester", "選擇學期 / Semester"), ("range", "自訂日期 / Date range"))
    VERSION_CHOICES = (("summary", "摘要版 / Summary"), ("detailed", "詳細版 / Detailed"))
    DETAIL_FIELD_CHOICES = (
        ("date", "日期 / Date"),
        ("nationality", "學生國籍 / Student nationality"),
        ("level", "學生程度 / Student level"),
        ("hours", "時數 / Hours"),
    )
    mode = forms.ChoiceField(label="下載方式 / Download mode", choices=MODE_CHOICES)
    semester = forms.ModelChoiceField(
        label="學期 / Semester", queryset=Semester.objects.none(), required=False
    )
    starts_on = forms.DateField(
        label="開始日期 / Start date", required=False, widget=forms.DateInput(attrs={"type": "date"})
    )
    ends_on = forms.DateField(
        label="截至日期 / End date", required=False, widget=forms.DateInput(attrs={"type": "date"})
    )
    LANGUAGE_CHOICES = (("zh", "中文版 / Chinese"), ("en", "英文版 / English"))
    language = forms.ChoiceField(
        label="證明語言 / Certificate language",
        choices=LANGUAGE_CHOICES,
        initial="zh",
        widget=forms.RadioSelect,
    )
    version = forms.ChoiceField(
        label="證明版本 / Certificate version",
        choices=VERSION_CHOICES,
        initial="summary",
        widget=forms.RadioSelect,
    )
    detail_fields = forms.MultipleChoiceField(
        label="詳細版顯示欄位 / Detailed fields",
        choices=DETAIL_FIELD_CHOICES,
        initial=["date", "nationality", "level", "hours"],
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    program = forms.ModelChoiceField(
        label="實習計劃 / Practicum program",
        queryset=None,
        required=False,
        error_messages={"required": "請選擇實習計劃。 / Select a practicum program."},
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        downloadable_ids = [row.pk for row in Semester.objects.all() if row.is_hours_downloadable]
        self.fields["semester"].queryset = Semester.objects.filter(pk__in=downloadable_ids).order_by("-starts_on")
        if user and user.role == Role.TUTOR:
            self.fields["program"].queryset = tutor_available_programs(user)
            self.fields["program"].required = True
        else:
            del self.fields["program"]

    def clean(self):
        cleaned = super().clean()
        mode = cleaned.get("mode")
        if mode == "semester":
            semester = cleaned.get("semester")
            if not semester:
                self.add_error("semester", "請選擇學期。 / Select a semester.")
            elif not semester.is_hours_downloadable:
                self.add_error("semester", "此學期尚未開放下載。 / This semester is not available yet.")
            elif semester:
                cleaned["starts_on"], cleaned["ends_on"] = semester.starts_on, semester.ends_on
        elif mode == "range":
            start, end = cleaned.get("starts_on"), cleaned.get("ends_on")
            if not start:
                self.add_error("starts_on", "請選擇開始日期。 / Select a start date.")
            if not end:
                self.add_error("ends_on", "請選擇截至日期。 / Select an end date.")
            if start and end and start > end:
                self.add_error("ends_on", "截至日期不可早於開始日期。 / End date cannot precede start date.")
            if start and end:
                blocked = [
                    row for row in Semester.objects.filter(starts_on__lte=end, ends_on__gte=start)
                    if not row.is_hours_downloadable
                ]
                if blocked:
                    names = "、".join(row.name_zh for row in blocked)
                    self.add_error(
                        "ends_on",
                        f"日期範圍包含尚未開放下載的學期：{names}。 / The range includes unavailable semesters.",
                    )
        if cleaned.get("version") == "detailed" and not cleaned.get("detail_fields"):
            self.add_error("detail_fields", "詳細版請至少選擇一個欄位。 / Select at least one detailed field.")
        return cleaned


class AdminPairingForm(forms.Form):
    """Admin manual pairing (item 12): picks tutor, tutee, and period directly, no invitation."""

    tutor = forms.ModelChoiceField(
        label="Tutor",
        queryset=User.objects.filter(role=Role.TUTOR, is_active=True).order_by("username"),
    )
    tutee = forms.ModelChoiceField(
        label="Tutee",
        queryset=User.objects.filter(role=Role.TUTEE, is_active=True).order_by("username"),
    )
    semester = forms.ModelChoiceField(
        label="學期 / 期間 (Semester / period)",
        queryset=Semester.objects.filter(is_active=True).order_by("-starts_on"),
    )
