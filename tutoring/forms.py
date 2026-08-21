from datetime import time

from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.utils.html import escape
from django.utils.safestring import mark_safe

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


MAX_EVIDENCE_LINKS = 5
MIN_EVIDENCE_LINKS = 1


class EvidenceLinksWidget(forms.Widget):
    """Renders one <input type="url"> per link, all sharing `name`, plus an "add" button.

    static/js/class-record-links.js clones/removes rows up to MAX_EVIDENCE_LINKS client-side
    (project convention: vanilla JS + data-* hooks, no frontend framework); the shared name
    lets value_from_datadict() collect the rows back into a list via QueryDict.getlist(),
    the same trick Django's own CheckboxSelectMultiple relies on.
    """

    def value_from_datadict(self, data, files, name):
        getter = getattr(data, "getlist", None)
        if getter:
            return getter(name)
        value = data.get(name)
        if isinstance(value, (list, tuple)):
            return list(value)
        return [value] if value else []

    def value_omitted_from_data(self, data, files, name):
        return False

    def render(self, name, value, attrs=None, renderer=None):
        links = value or [""]
        if not links:
            links = [""]
        rows = "".join(
            '<div class="evidence-link-row" data-evidence-link-row>'
            f'<input type="url" name="{name}" value="{escape(link)}" placeholder="https://..." data-evidence-link-input>'
            '<button type="button" class="button button-ghost button-small" data-evidence-link-remove>移除 <span>Remove</span></button>'
            "</div>"
            for link in links
        )
        return mark_safe(
            f'<div class="evidence-link-list" data-evidence-link-list data-max-links="{MAX_EVIDENCE_LINKS}">{rows}</div>'
            '<button type="button" class="button button-secondary button-small" data-evidence-link-add>'
            "+ 新增連結 <span>Add link</span></button>"
        )


class EvidenceLinksField(forms.Field):
    """1–5 https:// URLs (item 14). The "at least one" rule comes from the standard
    `required` empty-value check (an empty list is one of Field.empty_values) so it uses
    the project's usual "此欄位為必填欄位" message; only the max-count and per-link URL
    format get bespoke messages.
    """

    widget = EvidenceLinksWidget

    def to_python(self, value):
        if not value:
            return []
        return [item.strip() for item in value if item and item.strip()]

    def validate(self, value):
        super().validate(value)
        if len(value) > MAX_EVIDENCE_LINKS:
            raise ValidationError(
                f"最多只能提供 {MAX_EVIDENCE_LINKS} 個佐證連結。 / At most {MAX_EVIDENCE_LINKS} evidence links are allowed."
            )
        validate_https_url = URLValidator(schemes=["https"])
        for link in value:
            try:
                validate_https_url(link)
            except ValidationError:
                raise ValidationError(f"「{link}」不是合法的 https 網址。 / \"{link}\" is not a valid https:// URL.")


class ClassRecordForm(forms.ModelForm):
    skills_practiced = forms.MultipleChoiceField(
        label="授課類型 / Skills practiced", choices=SKILL_CHOICES, required=False, widget=forms.CheckboxSelectMultiple
    )
    evidence_links = EvidenceLinksField(label="佐證連結 / Evidence links")

    class Meta:
        model = ClassRecord
        fields = ("location", "topic", "content", "skills_practiced", "remarks", "attachment", "evidence_links")
        widgets = {
            "content": forms.Textarea(attrs={"rows": 5, "maxlength": 500, "data-character-count": "500"}),
            "remarks": forms.Textarea(attrs={"rows": 5, "maxlength": 500, "data-character-count": "500"}),
            "attachment": forms.FileInput(attrs={"accept": ".pdf,.jpg,.jpeg,.png"}),
        }

    def __init__(self, *args, author=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["evidence_links"].help_text = mark_safe(
            '<span class="evidence-help-points">'
            '<span><b>1</b><span>請提供 1–5 個可供對方及管理者查看的當次上課佐證連結，例如上課畫面截圖、教材、作業或錄影。'
            '<small>Provide 1–5 accessible links showing evidence of this class, such as class screenshots, teaching materials, assignments, or recordings, for your partner and administrators to review.</small></span></span>'
            '<span><b>2</b><span>請確認分享權限（共用檢視權限），確保對方及管理者可直接開啟查看。'
            '<small>Confirm that the link-sharing permissions allow your partner and administrators to open and view the evidence.</small></span></span>'
            '<span><b>3</b><span>請於本次實習／輔導階段結束後至少 10 天再刪除或下架；若查核時無法查看，該堂時數可能不予採計。'
            '<small>Keep the links available for at least 10 days after the practicum or tutoring stage ends. Hours may not be counted if the evidence cannot be reviewed.</small></span></span>'
            "</span>"
        )
        # Both participants now submit the same 1–5 evidence links. The attachment model
        # field remains only so historical records created before this change stay readable.
        del self.fields["attachment"]


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

    class Meta:
        model = Semester
        fields = ("name_zh", "name_en", "starts_on", "ends_on", "is_active", "program")
        widgets = {
            "starts_on": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "ends_on": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["program"].required = False
        self.fields["program"].empty_label = "（沿用舊版共用期間，不指定計畫） / (legacy shared period, no program)"


class SemesterCreateForm(forms.ModelForm):
    """Admin creation form: new semesters are enabled automatically. Unlike the edit form,
    `program` is required — new periods should always be scoped to a partner program going
    forward (see MEETING_CHANGE_REQUIREMENTS_2026-08-04.md item 15)."""

    class Meta:
        model = Semester
        fields = ("name_zh", "name_en", "starts_on", "ends_on", "program")
        widgets = {
            "starts_on": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "ends_on": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["program"].required = True
        self.fields["program"].queryset = PartnerProgram.objects.filter(is_active=True).order_by("name_zh")


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
        widget=forms.Select,
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
