from datetime import date, datetime, time, timedelta
from decimal import Decimal
from io import BytesIO
from pathlib import Path

import openpyxl

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import AuditLog, EducationLevel, IdentityCategory, PartnerProgram, Role, RosterEntry, User
from .forms import ClassRecordForm, HoursDownloadForm, ScheduleClassForm, SemesterCreateForm
from .reporting import build_hours_pdf, tutor_available_programs, user_has_hour_records

from .models import (
    InvitationStatus,
    Pairing,
    PairingReleaseReason,
    PairingReleaseRequest,
    PairingReleaseStatus,
    PairingStatus,
    PairingMessage,
    QualificationDocument,
    QualificationStatus,
    Semester,
    TuteeProfile,
    TutorProfile,
    Attendance,
    ClassRecord,
    ClassConfirmation,
    ClassAlert,
    ClassAlertReason,
    ClassAlertStatus,
    ClassSession,
    ConfirmationStatus,
    HourAdjustment,
    IncidentReport,
    IncidentReportCategory,
    IncidentReportStatus,
    MakeupReviewStatus,
)
from .services import (
    active_semester,
    anonymous_tutee_candidates,
    anonymous_tutor_candidates,
    archive_expired_semesters,
    check_in,
    cancel_class_alert,
    class_is_valid,
    confirm_counterpart,
    create_admin_pairing,
    respond_to_invitation,
    resolve_class_alert,
    resolve_incident_report,
    review_makeup,
    report_class_alert,
    process_pending_pairing_releases,
    review_pairing_release_request,
    reschedule_class,
    schedule_classes,
    semester_applies_to_user,
    send_invitation,
    submit_incident_report,
    submit_pairing_release_request,
    submit_class_record,
    user_program,
)


class SemesterTests(TestCase):
    def test_end_date_must_follow_start_date(self):
        semester = Semester(
            name_zh="測試學期",
            name_en="Test semester",
            starts_on=date(2026, 9, 1),
            ends_on=date(2026, 8, 31),
        )
        with self.assertRaises(ValidationError):
            semester.full_clean()

    def test_create_form_asks_for_dates_program_and_applicable_users(self):
        self.assertEqual(
            list(SemesterCreateForm().fields),
            ["name_zh", "name_en", "starts_on", "ends_on", "program", "applicable_users"],
        )
        self.assertTrue(SemesterCreateForm().fields["program"].required)

    def test_semester_is_automatically_archived_after_six_months(self):
        today = date(2026, 7, 19)
        old = Semester.objects.create(
            name_zh="舊學期", name_en="Old semester",
            starts_on=date(2025, 9, 1), ends_on=date(2026, 1, 18), is_active=True,
        )
        recent = Semester.objects.create(
            name_zh="半年內", name_en="Within six months",
            starts_on=date(2025, 7, 1), ends_on=date(2026, 1, 19), is_active=True,
        )
        self.assertEqual(archive_expired_semesters(today=today), 1)
        old.refresh_from_db()
        recent.refresh_from_db()
        self.assertFalse(old.is_active)
        self.assertTrue(recent.is_active)

    def test_admin_can_archive_an_ended_semester(self):
        today = timezone.localdate()
        semester = Semester.objects.create(
            name_zh="已結束學期", name_en="Ended semester",
            starts_on=today - timedelta(days=90), ends_on=today - timedelta(days=1),
            is_active=True,
        )
        admin = User.objects.create_superuser(username="SEMESTER-ADMIN", password="Admin-password-2026")
        self.client.force_login(admin)
        response = self.client.post(reverse("tutoring:archive_semester", args=[semester.pk]))
        self.assertRedirects(response, f"{reverse('accounts:dashboard')}#semesters")
        semester.refresh_from_db()
        self.assertFalse(semester.is_active)

    def test_admin_can_delete_semester_without_pairings(self):
        today = timezone.localdate()
        semester = Semester.objects.create(
            name_zh="打錯的學期", name_en="Mistaken semester",
            starts_on=today, ends_on=today + timedelta(days=60), is_active=True,
        )
        admin = User.objects.create_superuser(username="DELETE-SEM-ADMIN", password="Admin-password-2026")
        self.client.force_login(admin)
        response = self.client.post(reverse("tutoring:delete_semester", args=[semester.pk]))
        self.assertRedirects(response, f"{reverse('accounts:dashboard')}#semesters")
        self.assertFalse(Semester.objects.filter(pk=semester.pk).exists())
        self.assertTrue(AuditLog.objects.filter(event_type="SEMESTER_DELETED").exists())

    def test_admin_cannot_delete_semester_with_pairings(self):
        today = timezone.localdate()
        semester = Semester.objects.create(
            name_zh="已有配對的學期", name_en="Semester with pairings",
            starts_on=today, ends_on=today + timedelta(days=60), is_active=True,
        )
        ntnu = PartnerProgram.objects.get(code="NTNU")
        tutor_roster = RosterEntry.objects.create(
            student_id="DEL-SEM-TUTOR", name_zh="老師", role=Role.TUTOR,
            education_level=EducationLevel.MASTER, identity_category=IdentityCategory.LOCAL,
        )
        tutee_roster = RosterEntry.objects.create(
            student_id="DEL-SEM-TUTEE", name_zh="學生", role=Role.TUTEE,
            education_level=EducationLevel.NOT_APPLICABLE, identity_category=IdentityCategory.INTERNATIONAL,
            program=ntnu,
        )
        tutor = User.objects.create_user(username="DEL-SEM-TUTOR", password="Password-2026", role=Role.TUTOR, roster_entry=tutor_roster)
        tutee = User.objects.create_user(username="DEL-SEM-TUTEE", password="Password-2026", role=Role.TUTEE, roster_entry=tutee_roster)
        Pairing.objects.create(semester=semester, tutor=tutor, tutee=tutee)

        admin = User.objects.create_superuser(username="DELETE-SEM-ADMIN2", password="Admin-password-2026")
        self.client.force_login(admin)
        response = self.client.post(reverse("tutoring:delete_semester", args=[semester.pk]))
        self.assertRedirects(response, f"{reverse('accounts:dashboard')}#semesters")
        self.assertTrue(Semester.objects.filter(pk=semester.pk).exists())

    def test_admin_can_edit_semester_dates(self):
        today = timezone.localdate()
        semester = Semester.objects.create(
            name_zh="待修正學期", name_en="Semester to fix",
            starts_on=today, ends_on=today + timedelta(days=60), is_active=True,
        )
        admin = User.objects.create_superuser(username="EDIT-SEM-ADMIN", password="Admin-password-2026")
        self.client.force_login(admin)
        response = self.client.post(
            reverse("tutoring:update_semester", args=[semester.pk]),
            {
                f"semester-{semester.pk}-name_zh": "修正後學期",
                f"semester-{semester.pk}-name_en": "Fixed semester",
                f"semester-{semester.pk}-starts_on": (today + timedelta(days=5)).isoformat(),
                f"semester-{semester.pk}-ends_on": (today + timedelta(days=70)).isoformat(),
                f"semester-{semester.pk}-is_active": "on",
            },
        )
        self.assertRedirects(response, f"{reverse('accounts:dashboard')}#semesters")
        semester.refresh_from_db()
        self.assertEqual(semester.name_zh, "修正後學期")
        self.assertEqual(semester.starts_on, today + timedelta(days=5))
        log = AuditLog.objects.get(event_type="SEMESTER_UPDATED")
        self.assertEqual(log.metadata["semester_id"], semester.pk)

    def test_dashboard_shows_edit_toggle_for_each_semester(self):
        today = timezone.localdate()
        semester = Semester.objects.create(
            name_zh="顯示編輯用學期", name_en="Semester for edit UI",
            starts_on=today, ends_on=today + timedelta(days=60), is_active=True,
        )
        admin = User.objects.create_superuser(username="EDIT-UI-ADMIN", password="Admin-password-2026")
        self.client.force_login(admin)
        response = self.client.get(reverse("accounts:dashboard"))
        self.assertContains(response, reverse("tutoring:update_semester", args=[semester.pk]))
        self.assertContains(response, reverse("tutoring:delete_semester", args=[semester.pk]))


class ProgramScopedSemesterTests(TestCase):
    """MEETING_CHANGE_REQUIREMENTS_2026-08-04.md item 15: program-scoped, overlapping periods."""

    def setUp(self):
        self.ntnu = PartnerProgram.objects.get(code="NTNU")
        self.maryland = PartnerProgram.objects.get(code="MARYLAND")
        self.today = timezone.localdate()

    def test_more_than_three_active_future_semesters_can_be_created(self):
        for index in range(5):
            Semester.objects.create(
                name_zh=f"期間 {index}", name_en=f"Period {index}",
                starts_on=self.today + timedelta(days=400 * index),
                ends_on=self.today + timedelta(days=400 * index + 60),
                is_active=True, program=self.ntnu,
            ).full_clean()
        self.assertEqual(Semester.objects.filter(is_active=True).count(), 5)

    def test_same_program_overlap_is_rejected(self):
        Semester.objects.create(
            name_zh="NTNU 一", name_en="NTNU one", program=self.ntnu, is_active=True,
            starts_on=self.today, ends_on=self.today + timedelta(days=90),
        )
        overlapping = Semester(
            name_zh="NTNU 二", name_en="NTNU two", program=self.ntnu, is_active=True,
            starts_on=self.today + timedelta(days=30), ends_on=self.today + timedelta(days=120),
        )
        with self.assertRaises(ValidationError):
            overlapping.full_clean()

    def test_different_program_overlap_is_allowed(self):
        Semester.objects.create(
            name_zh="NTNU 學期", name_en="NTNU semester", program=self.ntnu, is_active=True,
            starts_on=self.today, ends_on=self.today + timedelta(days=90),
        )
        maryland_period = Semester(
            name_zh="馬里蘭計畫", name_en="Maryland program", program=self.maryland, is_active=True,
            starts_on=self.today, ends_on=self.today + timedelta(days=90),
        )
        maryland_period.full_clean()
        maryland_period.save()
        self.assertEqual(Semester.objects.filter(is_active=True, starts_on=self.today).count(), 2)

    def test_legacy_none_program_periods_still_reject_overlap_with_each_other(self):
        Semester.objects.create(
            name_zh="舊版一", name_en="Legacy one", is_active=True,
            starts_on=self.today, ends_on=self.today + timedelta(days=90),
        )
        overlapping = Semester(
            name_zh="舊版二", name_en="Legacy two", is_active=True,
            starts_on=self.today + timedelta(days=10), ends_on=self.today + timedelta(days=100),
        )
        with self.assertRaises(ValidationError):
            overlapping.full_clean()

    def test_active_semester_prefers_program_specific_then_falls_back_to_legacy(self):
        legacy = Semester.objects.create(
            name_zh="共用期間", name_en="Shared period", is_active=True,
            starts_on=self.today, ends_on=self.today + timedelta(days=90),
        )
        self.assertEqual(active_semester(program=self.maryland), legacy)
        ntnu_specific = Semester.objects.create(
            name_zh="NTNU 專屬", name_en="NTNU specific", program=self.ntnu, is_active=True,
            starts_on=self.today, ends_on=self.today + timedelta(days=90),
        )
        self.assertEqual(active_semester(program=self.ntnu), ntnu_specific)
        self.assertEqual(active_semester(program=self.maryland), legacy)
        self.assertEqual(active_semester(), legacy)

    def test_user_can_be_applicable_to_multiple_programs_and_periods(self):
        tutee_roster = RosterEntry.objects.create(
            student_id="MULTI-TUTEE", name_zh="多計畫學生", role=Role.TUTEE,
            education_level=EducationLevel.NOT_APPLICABLE, identity_category=IdentityCategory.INTERNATIONAL,
            program=self.ntnu,
        )
        tutee = User.objects.create_user(username="MULTI-TUTEE", password="Password-2026", role=Role.TUTEE, roster_entry=tutee_roster)
        tutor_roster = RosterEntry.objects.create(
            student_id="MULTI-TUTOR", name_zh="多計畫老師", role=Role.TUTOR,
            education_level=EducationLevel.MASTER, identity_category=IdentityCategory.LOCAL,
        )
        tutor = User.objects.create_user(username="MULTI-TUTOR", password="Password-2026", role=Role.TUTOR, roster_entry=tutor_roster)

        ntnu_period = Semester.objects.create(
            name_zh="NTNU 專屬", name_en="NTNU specific", program=self.ntnu, is_active=True,
            starts_on=self.today, ends_on=self.today + timedelta(days=90),
        )
        maryland_period = Semester.objects.create(
            name_zh="馬里蘭計畫", name_en="Maryland program", program=self.maryland, is_active=True,
            starts_on=self.today, ends_on=self.today + timedelta(days=90),
        )
        ntnu_period.applicable_users.set([tutor, tutee])
        maryland_period.applicable_users.set([tutor])
        self.assertTrue(semester_applies_to_user(ntnu_period, tutor))
        self.assertTrue(semester_applies_to_user(ntnu_period, tutee))
        self.assertTrue(semester_applies_to_user(maryland_period, tutor))
        self.assertEqual(user_program(tutee), self.ntnu)
        self.assertIsNone(user_program(tutor))

    def test_empty_applicable_users_means_open_to_everyone(self):
        period = Semester.objects.create(
            name_zh="開放期間", name_en="Open period", program=self.ntnu, is_active=True,
            starts_on=self.today, ends_on=self.today + timedelta(days=90),
        )
        tutee_roster = RosterEntry.objects.create(
            student_id="OPEN-TUTEE", name_zh="學生", role=Role.TUTEE,
            education_level=EducationLevel.NOT_APPLICABLE, identity_category=IdentityCategory.INTERNATIONAL,
            program=self.ntnu,
        )
        tutee = User.objects.create_user(username="OPEN-TUTEE", password="Password-2026", role=Role.TUTEE, roster_entry=tutee_roster)
        self.assertTrue(semester_applies_to_user(period, tutee))

    def test_applicable_users_rejects_tutee_from_a_different_program(self):
        maryland_roster = RosterEntry.objects.create(
            student_id="WRONG-PROGRAM-TUTEE", name_zh="馬里蘭學生", role=Role.TUTEE,
            education_level=EducationLevel.NOT_APPLICABLE, identity_category=IdentityCategory.INTERNATIONAL,
            program=self.maryland,
        )
        maryland_tutee = User.objects.create_user(
            username="WRONG-PROGRAM-TUTEE", password="Password-2026", role=Role.TUTEE, roster_entry=maryland_roster
        )
        form = SemesterCreateForm(data={
            "name_zh": "NTNU 專屬", "name_en": "NTNU specific",
            "starts_on": self.today.isoformat(), "ends_on": (self.today + timedelta(days=90)).isoformat(),
            "program": self.ntnu.pk, "applicable_users": [maryland_tutee.pk],
        })
        self.assertFalse(form.is_valid())
        self.assertIn("applicable_users", form.errors)

    def test_send_invitation_uses_tutee_program_period_over_unrelated_legacy_period(self):
        Semester.objects.filter(is_active=True).delete()
        legacy = Semester.objects.create(
            name_zh="共用期間", name_en="Shared period", is_active=True,
            starts_on=self.today - timedelta(days=400), ends_on=self.today - timedelta(days=300),
        )
        ntnu_period = Semester.objects.create(
            name_zh="NTNU 專屬", name_en="NTNU specific", program=self.ntnu, is_active=True,
            starts_on=self.today, ends_on=self.today + timedelta(days=90),
        )
        tutor_roster = RosterEntry.objects.create(
            student_id="INV-TUTOR", name_zh="老師", role=Role.TUTOR,
            education_level=EducationLevel.MASTER, identity_category=IdentityCategory.LOCAL,
        )
        tutor = User.objects.create_user(username="INV-TUTOR", password="Password-2026", role=Role.TUTOR, roster_entry=tutor_roster)
        TutorProfile.objects.create(tutor=tutor)
        QualificationDocument.objects.create(tutor=tutor, file="x.pdf", original_filename="x.pdf", status=QualificationStatus.APPROVED)
        tutee_roster = RosterEntry.objects.create(
            student_id="INV-TUTEE", name_zh="學生", role=Role.TUTEE,
            education_level=EducationLevel.NOT_APPLICABLE, identity_category=IdentityCategory.INTERNATIONAL,
            program=self.ntnu,
        )
        tutee = User.objects.create_user(username="INV-TUTEE", password="Password-2026", role=Role.TUTEE, roster_entry=tutee_roster)
        invitation = send_invitation(initiator=tutor, tutor_id=tutor.pk, tutee_id=tutee.pk)
        self.assertEqual(invitation.semester_id, ntnu_period.pk)
        self.assertNotEqual(invitation.semester_id, legacy.pk)


class MatchingFixtureTestCase(TestCase):
    """Shared tutor/tutee fixtures and factory helpers. No test_ methods of its own — it exists
    so MatchingTests and MarylandTutorRosterTests can both use the same setUp() without either
    inheriting (and re-running) the other's tests."""

    def setUp(self):
        today = timezone.localdate()
        self.semester = Semester.objects.create(
            name_zh="115 學年度第 1 學期",
            name_en="Fall 2026",
            starts_on=today - timedelta(days=7),
            ends_on=today + timedelta(days=90),
            is_active=True,
        )
        self.ntnu_program = PartnerProgram.objects.get(code="NTNU")
        self.maryland_program = PartnerProgram.objects.get(code="MARYLAND")
        self.tutor = self.make_tutor("TUTOR100", "知名小老師", "Known Tutor")
        self.tutee = self.make_tutee("TUTEE100", "知名外籍生", "Known Tutee", self.ntnu_program)
        self.maryland = self.make_tutee("MARY100", "馬里蘭學生", "Maryland Student", self.maryland_program)
        self.maryland_tutor = self.make_maryland_tutor("MARYTUTOR100", "馬里蘭老師", "Maryland Tutor")

    def make_tutor(self, student_id, name_zh, name_en, program=None, education_level=EducationLevel.MASTER):
        roster = RosterEntry.objects.create(
            student_id=student_id,
            name_zh=name_zh,
            name_en=name_en,
            role=Role.TUTOR,
            education_level=education_level,
            identity_category=IdentityCategory.LOCAL,
            program=program,
        )
        user = User.objects.create_user(
            username=student_id, password="Matching-password-2026", role=Role.TUTOR,
            roster_entry=roster, name_zh=name_zh, name_en=name_en,
        )
        TutorProfile.objects.create(
            tutor=user, gender="MALE", native_language="Mandarin Chinese", nationality="Taiwan",
            level_listening=4, level_speaking=5, level_reading=4, level_writing=4,
            available_days=["MON"], available_time_slots=["13:00-15:00"],
        )
        QualificationDocument.objects.create(
            tutor=user,
            file=SimpleUploadedFile(f"{student_id}.pdf", b"%PDF-1.4 test"),
            original_filename=f"{student_id}.pdf",
            status=QualificationStatus.APPROVED,
        )
        return user

    def make_maryland_tutor(self, student_id, name_zh, name_en):
        """A tutor on the Maryland course roster (item 4): bachelor's level, program=MARYLAND."""
        return self.make_tutor(
            student_id, name_zh, name_en, program=self.maryland_program, education_level=EducationLevel.BACHELOR,
        )

    def make_tutee(self, student_id, name_zh, name_en, program):
        roster = RosterEntry.objects.create(
            student_id=student_id,
            name_zh=name_zh,
            name_en=name_en,
            role=Role.TUTEE,
            education_level=EducationLevel.NOT_APPLICABLE,
            identity_category=IdentityCategory.INTERNATIONAL,
            program=program,
        )
        user = User.objects.create_user(
            username=student_id, password="Matching-password-2026", role=Role.TUTEE,
            roster_entry=roster, name_zh=name_zh, name_en=name_en,
        )
        TuteeProfile.objects.create(
            tutee=user, gender="FEMALE", native_language="English", nationality="United States",
            department="Languages", overall_level="B1", learning_duration="1_TO_2_YEARS",
            target_skills=["SPEAKING"], skills_to_improve="希望加強日常會話",
            preferred_days=["TUE"], preferred_time_slots=["15:00-17:00"],
        )
        return user


class MatchingTests(MatchingFixtureTestCase):
    def test_anonymous_candidate_data_excludes_identity(self):
        candidate = anonymous_tutee_candidates(semester=self.semester, tutor=self.tutor)[0]
        self.assertNotIn("name_zh", candidate)
        self.assertNotIn("name_en", candidate)
        self.assertNotIn("student_id", candidate)
        self.assertNotIn("phone", candidate)
        self.client.force_login(self.tutor)
        response = self.client.get(reverse("accounts:dashboard"))
        self.assertNotContains(response, "知名外籍生")
        self.assertNotContains(response, "Known Tutee")
        self.assertNotContains(response, "TUTEE100")
        self.assertContains(response, "United States")
        self.assertContains(response, "TOCFL B1")

    def test_tutee_candidates_can_be_filtered_by_compound_criteria(self):
        TuteeProfile.objects.filter(tutee=self.maryland).delete()
        other = self.make_tutee("TUTEE200", "另一位外籍生", "Other Tutee", self.ntnu_program)
        other.tutee_profile.gender = "MALE"
        other.tutee_profile.native_language = "Korean"
        other.tutee_profile.overall_level = "A1"
        other.tutee_profile.target_skills = ["LISTENING", "READING"]
        other.tutee_profile.preferred_days = ["WED"]
        other.tutee_profile.preferred_time_slots = ["09:00-11:00"]
        other.tutee_profile.save()

        all_ids = {c["user_id"] for c in anonymous_tutee_candidates(semester=self.semester, tutor=self.tutor)}
        self.assertEqual(all_ids, {self.tutee.pk, other.pk})

        gender_filtered = anonymous_tutee_candidates(
            semester=self.semester, tutor=self.tutor, filters={"gender": "MALE"}
        )
        self.assertEqual({c["user_id"] for c in gender_filtered}, {other.pk})

        level_filtered = anonymous_tutee_candidates(
            semester=self.semester, tutor=self.tutor, filters={"overall_level": "B1"}
        )
        self.assertEqual({c["user_id"] for c in level_filtered}, {self.tutee.pk})

        language_filtered = anonymous_tutee_candidates(
            semester=self.semester, tutor=self.tutor, filters={"native_language": "Korean"}
        )
        self.assertEqual({c["user_id"] for c in language_filtered}, {other.pk})

        skills_filtered = anonymous_tutee_candidates(
            semester=self.semester, tutor=self.tutor, filters={"target_skills": ["LISTENING", "READING"]}
        )
        self.assertEqual({c["user_id"] for c in skills_filtered}, {other.pk})

        days_filtered = anonymous_tutee_candidates(
            semester=self.semester, tutor=self.tutor, filters={"days": ["TUE"]}
        )
        self.assertEqual({c["user_id"] for c in days_filtered}, {self.tutee.pk})

        slots_filtered = anonymous_tutee_candidates(
            semester=self.semester, tutor=self.tutor, filters={"time_slots": ["09:00-11:00"]}
        )
        self.assertEqual({c["user_id"] for c in slots_filtered}, {other.pk})

        combined_filtered = anonymous_tutee_candidates(
            semester=self.semester,
            tutor=self.tutor,
            filters={"gender": "MALE", "native_language": "korean", "days": ["MON"]},
        )
        self.assertEqual(combined_filtered, [])

        self.client.force_login(self.tutor)
        response = self.client.get(reverse("accounts:dashboard"), {"tutee_gender": "MALE"})
        self.assertContains(response, "1 位符合")
        self.assertContains(response, reverse("tutoring:invite_tutee", args=[other.pk]))
        self.assertNotContains(response, reverse("tutoring:invite_tutee", args=[self.tutee.pk]))

    def test_maryland_dashboard_hides_tutor_identity(self):
        self.client.force_login(self.maryland)
        response = self.client.get(reverse("accounts:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "知名小老師")
        self.assertNotContains(response, "Known Tutor")
        self.assertNotContains(response, "TUTOR100")
        self.assertContains(response, "Mandarin Chinese")

    def test_tutor_candidates_can_be_filtered_by_compound_criteria(self):
        other_tutor = self.make_maryland_tutor("TUTOR200", "另一位老師", "Other Tutor")
        other_tutor.tutor_profile.gender = "FEMALE"
        other_tutor.tutor_profile.native_language = "Spanish"
        other_tutor.tutor_profile.available_days = ["WED"]
        other_tutor.tutor_profile.available_time_slots = ["09:00-11:00"]
        other_tutor.tutor_profile.save()

        all_ids = {c["user_id"] for c in anonymous_tutor_candidates(semester=self.semester, tutee=self.maryland)}
        self.assertEqual(all_ids, {self.maryland_tutor.pk, other_tutor.pk})

        gender_filtered = anonymous_tutor_candidates(
            semester=self.semester, tutee=self.maryland, filters={"gender": "FEMALE"}
        )
        self.assertEqual({c["user_id"] for c in gender_filtered}, {other_tutor.pk})

        language_filtered = anonymous_tutor_candidates(
            semester=self.semester, tutee=self.maryland, filters={"native_language": "Spanish"}
        )
        self.assertEqual({c["user_id"] for c in language_filtered}, {other_tutor.pk})

        days_filtered = anonymous_tutor_candidates(
            semester=self.semester, tutee=self.maryland, filters={"days": ["MON"]}
        )
        self.assertEqual({c["user_id"] for c in days_filtered}, {self.maryland_tutor.pk})

        slots_filtered = anonymous_tutor_candidates(
            semester=self.semester, tutee=self.maryland, filters={"time_slots": ["09:00-11:00"]}
        )
        self.assertEqual({c["user_id"] for c in slots_filtered}, {other_tutor.pk})

        combined_filtered = anonymous_tutor_candidates(
            semester=self.semester,
            tutee=self.maryland,
            filters={"gender": "FEMALE", "days": ["MON"]},
        )
        self.assertEqual(combined_filtered, [])

        self.client.force_login(self.maryland)
        response = self.client.get(reverse("accounts:dashboard"), {"tutor_gender": "FEMALE"})
        self.assertContains(response, "1 位符合")
        self.assertContains(response, reverse("tutoring:invite_tutor", args=[other_tutor.pk]))
        self.assertNotContains(response, reverse("tutoring:invite_tutor", args=[self.maryland_tutor.pk]))

    def test_pending_candidate_uses_short_status_label(self):
        send_invitation(initiator=self.tutor, tutor_id=self.tutor.pk, tutee_id=self.tutee.pk)
        self.client.force_login(self.tutor)
        response = self.client.get(reverse("accounts:dashboard"))
        self.assertContains(response, "待回覆")
        self.assertNotContains(response, "已有待回覆邀請 / Pending")

    def test_tutee_can_expand_anonymous_teacher_information_from_received_invitation(self):
        self.tutor.tutor_profile.teaching_notes = "重視生活會話與發音練習"
        self.tutor.tutor_profile.save(update_fields=["teaching_notes", "updated_at"])
        send_invitation(initiator=self.tutor, tutor_id=self.tutor.pk, tutee_id=self.tutee.pk)
        self.client.force_login(self.tutee)
        response = self.client.get(reverse("accounts:dashboard"))
        self.assertContains(response, "查看老師資料")
        self.assertContains(response, "聽力教學")
        self.assertContains(response, "13:00-15:00")
        self.assertContains(response, "重視生活會話與發音練習")
        self.assertNotContains(response, "知名小老師")
        self.assertNotContains(response, "Known Tutor")
        self.assertNotContains(response, "TUTOR100")

    def test_active_pair_can_open_each_others_full_profile(self):
        Pairing.objects.create(semester=self.semester, tutor=self.tutor, tutee=self.tutee)

        self.client.force_login(self.tutor)
        response = self.client.get(reverse("accounts:matched_profile", args=[self.tutee.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "知名外籍生")
        self.assertContains(response, "學習資料")
        self.assertContains(response, "希望加強日常會話")

        self.client.force_login(self.tutee)
        response = self.client.get(reverse("accounts:matched_profile", args=[self.tutor.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "知名小老師")
        self.assertContains(response, "教學資料")

    def test_unmatched_user_cannot_open_matched_profile(self):
        Pairing.objects.create(semester=self.semester, tutor=self.tutor, tutee=self.tutee)
        self.client.force_login(self.maryland)
        response = self.client.get(reverse("accounts:matched_profile", args=[self.tutor.pk]))
        self.assertEqual(response.status_code, 404)

    def test_current_match_card_links_to_profile_and_message_thread(self):
        pairing = Pairing.objects.create(semester=self.semester, tutor=self.tutor, tutee=self.tutee)
        self.client.force_login(self.tutee)
        response = self.client.get(reverse("accounts:dashboard"))
        self.assertContains(response, reverse("accounts:matched_profile", args=[self.tutor.pk]))
        self.assertContains(response, "私訊 / Message")
        self.assertContains(response, reverse("tutoring:pairing_messages", args=[pairing.pk]))
        self.assertNotContains(response, "電話 / Phone")

    def test_ntnu_tutee_hides_hours_but_maryland_keeps_them(self):
        Pairing.objects.create(semester=self.semester, tutor=self.tutor, tutee=self.tutee)
        self.client.force_login(self.tutee)
        response = self.client.get(reverse("accounts:dashboard"))
        self.assertNotContains(response, "已排時數 / Reserved")
        self.assertNotContains(response, "有效時數 / Verified")

        self.client.force_login(self.maryland)
        response = self.client.get(reverse("accounts:dashboard"))
        self.assertContains(response, "已排時數 / Reserved")
        self.assertContains(response, "有效時數 / Verified")

    def test_admin_matching_summary_renders(self):
        admin = User.objects.create_superuser(username="MATCH-ADMIN", password="Admin-password-2026")
        self.client.force_login(admin)
        response = self.client.get(reverse("accounts:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Active matches")

    def test_ntnu_tutee_cannot_initiate_but_maryland_can(self):
        with self.assertRaises(ValidationError):
            send_invitation(initiator=self.tutee, tutor_id=self.tutor.pk, tutee_id=self.tutee.pk)
        invitation = send_invitation(
            initiator=self.maryland, tutor_id=self.maryland_tutor.pk, tutee_id=self.maryland.pk
        )
        self.assertEqual(invitation.status, InvitationStatus.PENDING)
        self.assertEqual(invitation.initiated_by, self.maryland)

    def test_acceptance_creates_pairing_and_tutee_cannot_have_two_tutors(self):
        invitation = send_invitation(
            initiator=self.tutor, tutor_id=self.tutor.pk, tutee_id=self.tutee.pk
        )
        pairing = respond_to_invitation(invitation_id=invitation.pk, responder=self.tutee, accept=True)
        self.assertEqual(pairing.status, PairingStatus.ACTIVE)
        other_tutor = self.make_tutor("TUTOR200", "第二位老師", "Second Tutor")
        with self.assertRaises(ValidationError):
            send_invitation(initiator=other_tutor, tutor_id=other_tutor.pk, tutee_id=self.tutee.pk)

    def test_tutor_capacity_is_two_active_tutees(self):
        second = self.make_tutee("TUTEE200", "第二位學生", "Second Tutee", self.ntnu_program)
        third = self.make_tutee("TUTEE300", "第三位學生", "Third Tutee", self.ntnu_program)
        Pairing.objects.create(semester=self.semester, tutor=self.tutor, tutee=self.tutee)
        Pairing.objects.create(semester=self.semester, tutor=self.tutor, tutee=second)
        with self.assertRaises(ValidationError):
            send_invitation(initiator=self.tutor, tutor_id=self.tutor.pk, tutee_id=third.pk)

    def test_invitation_expires_in_five_days(self):
        invitation = send_invitation(
            initiator=self.tutor, tutor_id=self.tutor.pk, tutee_id=self.tutee.pk
        )
        remaining = invitation.expires_at - timezone.now()
        self.assertGreater(remaining, timedelta(days=4, hours=23))
        self.assertLessEqual(remaining, timedelta(days=5))

    def test_auto_eligible_release_ends_pairing_after_48_hours_and_cancels_future_class(self):
        pairing = Pairing.objects.create(semester=self.semester, tutor=self.tutor, tutee=self.tutee)
        class_session = ClassSession.objects.create(
            pairing=pairing,
            class_date=timezone.localdate() + timedelta(days=7),
            start_time=time(15, 0),
            duration=1,
            created_by=self.tutor,
        )
        requested_at = timezone.now()
        release_request = submit_pairing_release_request(
            pairing_id=pairing.pk,
            requester=self.tutee,
            reason=PairingReleaseReason.SCHEDULE_CONFLICT,
            now=requested_at,
        )
        self.assertAlmostEqual(
            release_request.auto_resolve_at,
            requested_at + timedelta(hours=48),
            delta=timedelta(seconds=1),
        )
        self.assertEqual(
            process_pending_pairing_releases(now=requested_at + timedelta(hours=47, minutes=59)), 0
        )
        release_request.refresh_from_db()
        self.assertEqual(release_request.status, PairingReleaseStatus.PENDING)
        self.assertEqual(process_pending_pairing_releases(now=requested_at + timedelta(hours=48, seconds=1)), 1)
        pairing.refresh_from_db()
        release_request.refresh_from_db()
        class_session.refresh_from_db()
        self.assertEqual(pairing.status, PairingStatus.ENDED)
        self.assertEqual(release_request.status, PairingReleaseStatus.AUTO_APPROVED)
        self.assertEqual(class_session.status, "CANCELLED")
        replacement_tutor = self.make_tutor("TUTOR-REPLACEMENT", "新老師", "Replacement Tutor")
        replacement_invitation = send_invitation(
            initiator=replacement_tutor,
            tutor_id=replacement_tutor.pk,
            tutee_id=self.tutee.pk,
        )
        self.assertEqual(replacement_invitation.status, InvitationStatus.PENDING)
        with self.assertRaises(ValidationError):
            send_invitation(
                initiator=self.tutor,
                tutor_id=self.tutor.pk,
                tutee_id=self.tutee.pk,
            )

    def test_conduct_release_never_auto_approves_and_admin_can_approve(self):
        pairing = Pairing.objects.create(semester=self.semester, tutor=self.tutor, tutee=self.tutee)
        requested_at = timezone.now()
        with self.assertRaises(ValidationError):
            submit_pairing_release_request(
                pairing_id=pairing.pk,
                requester=self.tutor,
                reason=PairingReleaseReason.CONDUCT,
                note="",
                now=requested_at,
            )
        release_request = submit_pairing_release_request(
            pairing_id=pairing.pk,
            requester=self.tutor,
            reason=PairingReleaseReason.CONDUCT,
            note="課堂互動有不適當行為",
            now=requested_at,
        )
        self.assertIsNone(release_request.auto_resolve_at)
        self.assertEqual(process_pending_pairing_releases(now=requested_at + timedelta(days=10)), 0)
        pairing.refresh_from_db()
        self.assertEqual(pairing.status, PairingStatus.ACTIVE)
        admin = User.objects.create_superuser(username="RELEASE-ADMIN", password="Admin-password-2026")
        review_pairing_release_request(
            request_id=release_request.pk,
            admin=admin,
            approve=True,
            note="已確認雙方狀況",
        )
        pairing.refresh_from_db()
        release_request.refresh_from_db()
        self.assertEqual(pairing.status, PairingStatus.ENDED)
        self.assertEqual(release_request.status, PairingReleaseStatus.APPROVED)

    def test_rejected_release_keeps_pairing_active(self):
        pairing = Pairing.objects.create(semester=self.semester, tutor=self.tutor, tutee=self.tutee)
        release_request = submit_pairing_release_request(
            pairing_id=pairing.pk,
            requester=self.tutee,
            reason=PairingReleaseReason.UNREACHABLE,
        )
        admin = User.objects.create_superuser(username="REJECT-ADMIN", password="Admin-password-2026")
        review_pairing_release_request(
            request_id=release_request.pk,
            admin=admin,
            approve=False,
            note="已恢復聯繫",
        )
        pairing.refresh_from_db()
        release_request.refresh_from_db()
        self.assertEqual(pairing.status, PairingStatus.ACTIVE)
        self.assertEqual(release_request.status, PairingReleaseStatus.REJECTED)

    def test_release_request_appears_for_participant_and_admin(self):
        pairing = Pairing.objects.create(semester=self.semester, tutor=self.tutor, tutee=self.tutee)
        self.client.force_login(self.tutor)
        response = self.client.get(reverse("accounts:dashboard"))
        self.assertContains(response, "申請解除配對")
        self.assertNotContains(response, "管理員 48 小時內未處理，系統將自動解除")
        response = self.client.post(
            reverse("tutoring:request_pairing_release", args=[pairing.pk]),
            {"reason": PairingReleaseReason.NO_SHOW, "note": "已多次未到"},
        )
        self.assertRedirects(response, reverse("accounts:dashboard") + "#overview")
        self.assertTrue(PairingReleaseRequest.objects.filter(pairing=pairing).exists())
        admin = User.objects.create_superuser(username="DASHBOARD-ADMIN", password="Admin-password-2026")
        self.client.force_login(admin)
        response = self.client.get(reverse("accounts:dashboard"))
        self.assertContains(response, "解除配對審核")
        self.assertContains(response, "已多次未到")

    def test_pending_invitation_cap_blocks_new_invitations_for_tutor(self):
        second = self.make_tutee("TUTEE210", "第二位學生", "Second Tutee", self.ntnu_program)
        third = self.make_tutee("TUTEE220", "第三位學生", "Third Tutee", self.ntnu_program)
        fourth = self.make_tutee("TUTEE230", "第四位學生", "Fourth Tutee", self.ntnu_program)
        send_invitation(initiator=self.tutor, tutor_id=self.tutor.pk, tutee_id=self.tutee.pk)
        send_invitation(initiator=self.tutor, tutor_id=self.tutor.pk, tutee_id=second.pk)
        send_invitation(initiator=self.tutor, tutor_id=self.tutor.pk, tutee_id=third.pk)
        with self.assertRaises(ValidationError):
            send_invitation(initiator=self.tutor, tutor_id=self.tutor.pk, tutee_id=fourth.pk)

    def test_pending_invitation_cap_counts_both_directions_for_tutee(self):
        tutor_b = self.make_maryland_tutor("TUTOR210", "第二位老師", "Second Tutor")
        tutor_c = self.make_maryland_tutor("TUTOR220", "第三位老師", "Third Tutor")
        tutor_d = self.make_maryland_tutor("TUTOR230", "第四位老師", "Fourth Tutor")
        send_invitation(initiator=self.maryland_tutor, tutor_id=self.maryland_tutor.pk, tutee_id=self.maryland.pk)
        send_invitation(initiator=tutor_b, tutor_id=tutor_b.pk, tutee_id=self.maryland.pk)
        send_invitation(initiator=self.maryland, tutor_id=tutor_c.pk, tutee_id=self.maryland.pk)
        with self.assertRaises(ValidationError):
            send_invitation(initiator=self.maryland, tutor_id=tutor_d.pk, tutee_id=self.maryland.pk)

    def test_tutor_reaching_capacity_cancels_other_pending_invitations(self):
        tutee_b = self.make_tutee("TUTEE240", "乙學生", "Tutee B", self.ntnu_program)
        tutee_c = self.make_tutee("TUTEE250", "丙學生", "Tutee C", self.ntnu_program)
        invitation_a = send_invitation(initiator=self.tutor, tutor_id=self.tutor.pk, tutee_id=self.tutee.pk)
        invitation_b = send_invitation(initiator=self.tutor, tutor_id=self.tutor.pk, tutee_id=tutee_b.pk)
        invitation_c = send_invitation(initiator=self.tutor, tutor_id=self.tutor.pk, tutee_id=tutee_c.pk)

        respond_to_invitation(invitation_id=invitation_a.pk, responder=self.tutee, accept=True)
        invitation_c.refresh_from_db()
        self.assertEqual(invitation_c.status, InvitationStatus.PENDING)

        respond_to_invitation(invitation_id=invitation_b.pk, responder=tutee_b, accept=True)
        invitation_c.refresh_from_db()
        self.assertEqual(invitation_c.status, InvitationStatus.CANCELLED)

    def test_maryland_initiated_invitation_cancels_tutees_other_pending_on_acceptance(self):
        tutor_b = self.make_maryland_tutor("TUTOR240", "乙老師", "Tutor B")
        invitation_to_tutor = send_invitation(
            initiator=self.maryland, tutor_id=self.maryland_tutor.pk, tutee_id=self.maryland.pk
        )
        invitation_to_tutor_b = send_invitation(
            initiator=self.maryland, tutor_id=tutor_b.pk, tutee_id=self.maryland.pk
        )
        respond_to_invitation(invitation_id=invitation_to_tutor.pk, responder=self.maryland_tutor, accept=True)
        invitation_to_tutor_b.refresh_from_db()
        self.assertEqual(invitation_to_tutor_b.status, InvitationStatus.CANCELLED)


class MarylandTutorRosterTests(MatchingFixtureTestCase):
    """MEETING_CHANGE_REQUIREMENTS_2026-08-04.md item 4: Maryland tutees only match tutors on
    the Maryland course roster, and only bachelor's-level ones at that; ordinary tutors keep
    serving NTNU tutees as before."""

    def test_ordinary_tutor_does_not_see_maryland_tutee_as_candidate(self):
        candidates = anonymous_tutee_candidates(semester=self.semester, tutor=self.tutor)
        self.assertNotIn(self.maryland.pk, {c["user_id"] for c in candidates})
        self.assertIn(self.tutee.pk, {c["user_id"] for c in candidates})

    def test_maryland_tutor_only_sees_maryland_tutee_not_ntnu(self):
        candidates = anonymous_tutee_candidates(semester=self.semester, tutor=self.maryland_tutor)
        ids = {c["user_id"] for c in candidates}
        self.assertIn(self.maryland.pk, ids)
        self.assertNotIn(self.tutee.pk, ids)

    def test_maryland_roster_tutor_at_wrong_education_level_is_excluded(self):
        masters_tutor = self.make_tutor(
            "MARY-MASTERS", "碩士老師", "Masters Tutor",
            program=self.maryland_program, education_level=EducationLevel.MASTER,
        )
        tutee_candidates = anonymous_tutor_candidates(semester=self.semester, tutee=self.maryland)
        self.assertNotIn(masters_tutor.pk, {c["user_id"] for c in tutee_candidates})
        with self.assertRaises(ValidationError):
            send_invitation(initiator=self.maryland, tutor_id=masters_tutor.pk, tutee_id=self.maryland.pk)

    def test_send_invitation_rejects_ordinary_tutor_for_maryland_tutee_even_off_screen(self):
        with self.assertRaises(ValidationError):
            send_invitation(initiator=self.tutor, tutor_id=self.tutor.pk, tutee_id=self.maryland.pk)

    def test_send_invitation_rejects_maryland_tutor_for_ntnu_tutee_even_off_screen(self):
        with self.assertRaises(ValidationError):
            send_invitation(initiator=self.maryland_tutor, tutor_id=self.maryland_tutor.pk, tutee_id=self.tutee.pk)

    def test_ordinary_tutor_can_still_pair_with_ntnu_tutee(self):
        invitation = send_invitation(initiator=self.tutor, tutor_id=self.tutor.pk, tutee_id=self.tutee.pk)
        self.assertEqual(invitation.status, InvitationStatus.PENDING)


class AdminPairingTests(MatchingFixtureTestCase):
    """MEETING_CHANGE_REQUIREMENTS_2026-08-04.md item 12: Admin can build a pairing directly,
    including one extra active tutee for non-NTNU programs — but never for NTNU."""

    def test_non_admin_cannot_create_admin_pairing(self):
        with self.assertRaises(ValidationError):
            create_admin_pairing(
                admin=self.tutor, tutor_id=self.tutor.pk, tutee_id=self.tutee.pk, semester_id=self.semester.pk,
            )

    def test_admin_can_create_pairing_without_invitation(self):
        admin = User.objects.create_superuser(username="PAIR-ADMIN1", password="Admin-password-2026")
        pairing = create_admin_pairing(
            admin=admin, tutor_id=self.tutor.pk, tutee_id=self.tutee.pk, semester_id=self.semester.pk,
        )
        self.assertEqual(pairing.status, PairingStatus.ACTIVE)
        self.assertEqual(pairing.created_by, admin)
        self.assertIsNone(pairing.invitation)
        log = AuditLog.objects.get(event_type="ADMIN_PAIRING_CREATED")
        self.assertEqual(log.metadata["tutor"], self.tutor.username)
        self.assertEqual(log.metadata["tutee"], self.tutee.username)

    def test_admin_can_grant_third_tutee_for_non_ntnu_program(self):
        admin = User.objects.create_superuser(username="PAIR-ADMIN2", password="Admin-password-2026")
        second_maryland_tutee = self.make_tutee("MARY200", "馬里蘭學生二", "Maryland Student 2", self.maryland_program)
        third_maryland_tutee = self.make_tutee("MARY300", "馬里蘭學生三", "Maryland Student 3", self.maryland_program)
        invitation_a = send_invitation(
            initiator=self.maryland_tutor, tutor_id=self.maryland_tutor.pk, tutee_id=self.maryland.pk,
        )
        invitation_b = send_invitation(
            initiator=self.maryland_tutor, tutor_id=self.maryland_tutor.pk, tutee_id=second_maryland_tutee.pk,
        )
        respond_to_invitation(invitation_id=invitation_a.pk, responder=self.maryland, accept=True)
        respond_to_invitation(invitation_id=invitation_b.pk, responder=second_maryland_tutee, accept=True)
        with self.assertRaises(ValidationError):
            send_invitation(
                initiator=self.maryland_tutor, tutor_id=self.maryland_tutor.pk, tutee_id=third_maryland_tutee.pk,
            )
        pairing = create_admin_pairing(
            admin=admin, tutor_id=self.maryland_tutor.pk, tutee_id=third_maryland_tutee.pk,
            semester_id=self.semester.pk,
        )
        self.assertEqual(pairing.status, PairingStatus.ACTIVE)
        self.assertEqual(
            Pairing.objects.filter(tutor=self.maryland_tutor, status=PairingStatus.ACTIVE).count(), 3
        )

    def test_admin_cannot_grant_third_tutee_for_ntnu(self):
        admin = User.objects.create_superuser(username="PAIR-ADMIN3", password="Admin-password-2026")
        tutee_b = self.make_tutee("TUTEE300", "乙學生", "Tutee B", self.ntnu_program)
        tutee_c = self.make_tutee("TUTEE310", "丙學生", "Tutee C", self.ntnu_program)
        invitation_a = send_invitation(initiator=self.tutor, tutor_id=self.tutor.pk, tutee_id=self.tutee.pk)
        invitation_b = send_invitation(initiator=self.tutor, tutor_id=self.tutor.pk, tutee_id=tutee_b.pk)
        respond_to_invitation(invitation_id=invitation_a.pk, responder=self.tutee, accept=True)
        respond_to_invitation(invitation_id=invitation_b.pk, responder=tutee_b, accept=True)
        with self.assertRaises(ValidationError):
            create_admin_pairing(
                admin=admin, tutor_id=self.tutor.pk, tutee_id=tutee_c.pk, semester_id=self.semester.pk,
            )
        self.assertEqual(Pairing.objects.filter(tutor=self.tutor, status=PairingStatus.ACTIVE).count(), 2)

    def test_admin_pairing_still_enforces_program_roster_and_existing_tutor_checks(self):
        admin = User.objects.create_superuser(username="PAIR-ADMIN4", password="Admin-password-2026")
        with self.assertRaises(ValidationError):
            create_admin_pairing(
                admin=admin, tutor_id=self.tutor.pk, tutee_id=self.maryland.pk, semester_id=self.semester.pk,
            )
        create_admin_pairing(
            admin=admin, tutor_id=self.tutor.pk, tutee_id=self.tutee.pk, semester_id=self.semester.pk,
        )
        other_tutor = self.make_tutor("TUTOR320", "另一位老師", "Other Tutor")
        with self.assertRaises(ValidationError):
            create_admin_pairing(
                admin=admin, tutor_id=other_tutor.pk, tutee_id=self.tutee.pk, semester_id=self.semester.pk,
            )

    def test_non_admin_cannot_reach_create_pairing_view(self):
        self.client.force_login(self.tutor)
        response = self.client.post(reverse("tutoring:create_pairing"), {
            "tutor": self.tutor.pk, "tutee": self.tutee.pk, "semester": self.semester.pk,
        })
        self.assertEqual(response.status_code, 404)
        self.assertFalse(Pairing.objects.filter(tutor=self.tutor, tutee=self.tutee).exists())


class ClassWorkflowTests(TestCase):
    def setUp(self):
        today = timezone.localdate()
        self.semester = Semester.objects.create(
            name_zh="V2 測試學期", name_en="V2 test semester",
            starts_on=today - timedelta(days=7), ends_on=today + timedelta(days=90),
            is_active=True,
        )
        self.ntnu_program = PartnerProgram.objects.get(code="NTNU")
        tutor_roster = RosterEntry.objects.create(
            student_id="CLASS-TUTOR", name_zh="課程老師", name_en="Class Tutor", role=Role.TUTOR,
            education_level=EducationLevel.MASTER, identity_category=IdentityCategory.LOCAL,
        )
        tutee_roster = RosterEntry.objects.create(
            student_id="CLASS-TUTEE", name_zh="課程學生", name_en="Class Student", role=Role.TUTEE,
            education_level=EducationLevel.NOT_APPLICABLE, identity_category=IdentityCategory.INTERNATIONAL,
            program=self.ntnu_program,
        )
        self.tutor = User.objects.create_user(
            username="CLASS-TUTOR", password="Test-password-2026", role=Role.TUTOR,
            roster_entry=tutor_roster, name_zh="課程老師", name_en="Class Tutor",
        )
        self.tutee = User.objects.create_user(
            username="CLASS-TUTEE", password="Test-password-2026", role=Role.TUTEE,
            roster_entry=tutee_roster, name_zh="課程學生", name_en="Class Student",
        )
        self.pairing = Pairing.objects.create(semester=self.semester, tutor=self.tutor, tutee=self.tutee)

    def aware(self, day, clock):
        return timezone.make_aware(datetime.combine(day, clock), timezone.get_current_timezone())

    def record_data(self, topic):
        return {
            "location": "綜合大樓 / General Building",
            "topic": topic,
            "content": "會話與發音練習",
            "reflection": "完成本次練習並互相回饋",
            "remarks": "",
        }

    def test_schedule_reserves_weekly_quota_and_dashboard_shows_class(self):
        class_date = timezone.localdate() + timedelta(days=1)
        sessions = schedule_classes(
            tutor=self.tutor,
            pairing=self.pairing,
            class_date=class_date,
            start_time=time(22, 30),
            duration="1.5",
        )
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0].ends_at.date(), class_date + timedelta(days=1))
        with self.assertRaises(ValidationError):
            schedule_classes(
                tutor=self.tutor,
                pairing=self.pairing,
                class_date=class_date + timedelta(days=1),
                start_time=time(10),
                duration="1.0",
            )
        self.client.force_login(self.tutor)
        response = self.client.get(reverse("accounts:dashboard"))
        self.assertContains(response, "我的課表")
        self.assertContains(response, reverse("tutoring:class_detail", args=[sessions[0].pk]))

    def test_start_time_accepts_five_minute_increments(self):
        class_date = timezone.localdate() + timedelta(days=1)
        session = schedule_classes(
            tutor=self.tutor,
            pairing=self.pairing,
            class_date=class_date,
            start_time=time(17, 20),
            duration="1.0",
        )[0]
        self.assertEqual(session.start_time, time(17, 20))
        with self.assertRaises(ValidationError):
            schedule_classes(
                tutor=self.tutor,
                pairing=self.pairing,
                class_date=class_date + timedelta(days=7),
                start_time=time(17, 22),
                duration="1.0",
            )

    def test_schedule_form_lists_only_five_minute_values(self):
        class_date = timezone.localdate() + timedelta(days=1)
        form = ScheduleClassForm(
            {
                "pairing": self.pairing.pk,
                "class_date": class_date.isoformat(),
                "start_time_0": "17",
                "start_time_1": "20",
                "duration": "1",
                "repeat_weekly": "",
                "repeat_until": "",
            },
            tutor=self.tutor,
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["start_time"], time(17, 20))
        minute_choices = [value for value, _label in form.fields["start_time"].widget.widgets[1].choices]
        self.assertEqual(minute_choices, [f"{minute:02d}" for minute in range(0, 60, 5)])

    def test_both_records_and_mutual_confirmation_create_valid_hours(self):
        class_date = timezone.localdate()
        session = schedule_classes(
            tutor=self.tutor, pairing=self.pairing, class_date=class_date,
            start_time=time(10), duration="1.0", now=self.aware(class_date, time(9)),
        )[0]
        normal_now = self.aware(class_date, time(10, 30))
        check_in(session_id=session.pk, participant=self.tutor, now=normal_now)
        check_in(session_id=session.pk, participant=self.tutee, now=normal_now)
        submit_class_record(
            session_id=session.pk, author=self.tutor, data=self.record_data("老師紀錄"), now=normal_now
        )
        submit_class_record(
            session_id=session.pk, author=self.tutee, data=self.record_data("學生紀錄"), now=normal_now
        )
        confirm_counterpart(
            session_id=session.pk, reviewer=self.tutor, status=ConfirmationStatus.CONFIRMED
        )
        confirm_counterpart(
            session_id=session.pk, reviewer=self.tutee, status=ConfirmationStatus.CONFIRMED
        )
        session.refresh_from_db()
        self.assertTrue(class_is_valid(session))

    def test_class_record_skills_practiced_saved_and_shown_to_counterpart_and_admin(self):
        class_date = timezone.localdate()
        session = schedule_classes(
            tutor=self.tutor, pairing=self.pairing, class_date=class_date,
            start_time=time(10), duration="1.0", now=self.aware(class_date, time(9)),
        )[0]
        normal_now = self.aware(class_date, time(10, 30))
        check_in(session_id=session.pk, participant=self.tutor, now=normal_now)
        submit_class_record(
            session_id=session.pk,
            author=self.tutor,
            data={**self.record_data("聽說練習"), "skills_practiced": ["LISTENING", "SPEAKING"]},
            now=normal_now,
        )
        record = ClassRecord.objects.get(session=session, author=self.tutor)
        self.assertEqual(record.skills_practiced, ["LISTENING", "SPEAKING"])

        self.client.force_login(self.tutee)
        response = self.client.get(reverse("tutoring:class_detail", args=[session.pk]))
        self.assertContains(response, "<b>聽力 / Listening</b>", html=False)
        self.assertContains(response, "<b>口說 / Speaking</b>", html=False)
        self.assertNotContains(response, "<b>寫作 / Writing</b>", html=False)

        admin = User.objects.create_superuser(username="RECORD-SKILL-ADMIN", password="Admin-password-2026")
        self.client.force_login(admin)
        response = self.client.get(reverse("tutoring:class_detail", args=[session.pk]))
        self.assertContains(response, "<b>聽力 / Listening</b>", html=False)
        self.assertContains(response, "<b>口說 / Speaking</b>", html=False)
        self.assertNotContains(response, "<b>寫作 / Writing</b>", html=False)

        response = self.client.get("/system-admin/tutoring/classrecord/?skill=LISTENING")
        self.assertContains(response, "聽說練習")
        response = self.client.get("/system-admin/tutoring/classrecord/?skill=WRITING")
        self.assertNotContains(response, "聽說練習")

    def test_class_record_attachment_validates_type_and_size(self):
        base_data = {
            "location": "綜合大樓 / General Building", "topic": "課堂主題", "content": "課堂內容", "remarks": "",
        }
        valid_form = ClassRecordForm(
            data=base_data,
            files={"attachment": SimpleUploadedFile("outcome.pdf", b"%PDF-1.4 test", content_type="application/pdf")},
        )
        self.assertTrue(valid_form.is_valid(), valid_form.errors)

        wrong_type_form = ClassRecordForm(
            data=base_data,
            files={"attachment": SimpleUploadedFile("outcome.txt", b"plain text", content_type="text/plain")},
        )
        self.assertFalse(wrong_type_form.is_valid())
        self.assertIn("僅接受 PDF、JPG、PNG", str(wrong_type_form.errors["attachment"]))

        oversized_form = ClassRecordForm(
            data=base_data,
            files={"attachment": SimpleUploadedFile("outcome.pdf", b"x" * 500_001, content_type="application/pdf")},
        )
        self.assertFalse(oversized_form.is_valid())
        self.assertIn("500 KB", str(oversized_form.errors["attachment"]))

    def test_class_record_content_and_remarks_enforce_2000_char_limit(self):
        at_limit_data = {
            "location": "綜合大樓 / General Building", "topic": "課堂主題",
            "content": "內" * 2000, "remarks": "備" * 2000,
        }
        at_limit_form = ClassRecordForm(data=at_limit_data)
        self.assertTrue(at_limit_form.is_valid(), at_limit_form.errors)

        over_limit_data = {
            "location": "綜合大樓 / General Building", "topic": "課堂主題",
            "content": "內" * 2001, "remarks": "",
        }
        over_limit_form = ClassRecordForm(data=over_limit_data)
        self.assertFalse(over_limit_form.is_valid())
        self.assertIn("content", over_limit_form.errors)

        over_limit_remarks_data = {
            "location": "綜合大樓 / General Building", "topic": "課堂主題",
            "content": "課堂內容", "remarks": "備" * 2001,
        }
        over_limit_remarks_form = ClassRecordForm(data=over_limit_remarks_data)
        self.assertFalse(over_limit_remarks_form.is_valid())
        self.assertIn("remarks", over_limit_remarks_form.errors)

    def test_class_record_attachment_saved_and_downloadable_by_counterpart_and_admin(self):
        class_date = timezone.localdate()
        session = schedule_classes(
            tutor=self.tutor, pairing=self.pairing, class_date=class_date,
            start_time=time(10), duration="1.0", now=self.aware(class_date, time(9)),
        )[0]
        normal_now = self.aware(class_date, time(10, 30))
        check_in(session_id=session.pk, participant=self.tutor, now=normal_now)
        submit_class_record(
            session_id=session.pk,
            author=self.tutor,
            data={
                **self.record_data("附件測試"),
                "attachment": SimpleUploadedFile("proof.pdf", b"%PDF-1.4 test", content_type="application/pdf"),
            },
            now=normal_now,
        )
        record = ClassRecord.objects.get(session=session, author=self.tutor)
        self.assertTrue(record.attachment.name)
        self.assertEqual(record.attachment_filename, Path(record.attachment.name).name)

        self.client.force_login(self.tutee)
        response = self.client.get(reverse("tutoring:class_detail", args=[session.pk]))
        self.assertContains(response, record.attachment.url)

        admin = User.objects.create_superuser(username="RECORD-ATTACHMENT-ADMIN", password="Admin-password-2026")
        self.client.force_login(admin)
        response = self.client.get(reverse("tutoring:class_detail", args=[session.pk]))
        self.assertContains(response, record.attachment.url)

    def test_makeup_reason_fields_only_shown_when_overdue(self):
        today = timezone.localdate()
        future_session = ClassSession.objects.create(
            pairing=self.pairing, class_date=today + timedelta(days=1), start_time=time(10, 0),
            duration=1, created_by=self.tutor,
        )
        overdue_session = ClassSession.objects.create(
            pairing=self.pairing, class_date=today - timedelta(days=3), start_time=time(10, 0),
            duration=1, created_by=self.tutor,
        )
        self.client.force_login(self.tutor)

        response = self.client.get(reverse("tutoring:class_detail", args=[future_session.pk]))
        self.assertNotContains(response, "逾時補簽原因")
        self.assertNotContains(response, "逾時補登原因")

        response = self.client.get(reverse("tutoring:class_detail", args=[overdue_session.pk]))
        self.assertContains(response, "逾時補簽原因")
        self.assertContains(response, "逾時補登原因")

    def test_makeup_record_requires_mutual_confirmation_and_admin_approval(self):
        class_date = timezone.localdate()
        session = schedule_classes(
            tutor=self.tutor, pairing=self.pairing, class_date=class_date,
            start_time=time(8), duration="1.0", now=self.aware(class_date, time(7)),
        )[0]
        check_time = self.aware(class_date, time(8, 30))
        check_in(session_id=session.pk, participant=self.tutor, now=check_time)
        check_in(session_id=session.pk, participant=self.tutee, now=check_time)
        late = self.aware(class_date + timedelta(days=2), time(9))
        submit_class_record(
            session_id=session.pk, author=self.tutor, data=self.record_data("老師補登"),
            reason="忘記在期限內填寫", now=late,
        )
        submit_class_record(
            session_id=session.pk, author=self.tutee, data=self.record_data("學生補登"),
            reason="忘記在期限內填寫", now=late,
        )
        confirm_counterpart(session_id=session.pk, reviewer=self.tutor, status=ConfirmationStatus.CONFIRMED)
        confirm_counterpart(session_id=session.pk, reviewer=self.tutee, status=ConfirmationStatus.CONFIRMED)
        session.makeup_review.refresh_from_db()
        self.assertEqual(session.makeup_review.status, MakeupReviewStatus.PENDING)
        self.assertFalse(class_is_valid(session))
        admin = User.objects.create_superuser(username="CLASS-ADMIN", password="Admin-password-2026")
        self.client.force_login(admin)
        detail = self.client.get(reverse("tutoring:class_detail", args=[session.pk]))
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, "補登詳情")
        self.assertContains(detail, "老師補登")
        self.assertContains(detail, "忘記在期限內填寫")
        review_makeup(session_id=session.pk, admin=admin, approve=True)
        session.makeup_review.refresh_from_db()
        self.assertTrue(class_is_valid(session))
        history = self.client.get(reverse("accounts:dashboard"))
        self.assertContains(history, "已核准")
        self.assertContains(history, "補課堂紀錄")

    def test_schedule_keeps_future_classes_and_moves_past_classes_to_hours_history(self):
        today = timezone.localdate()
        past = schedule_classes(
            tutor=self.tutor, pairing=self.pairing, class_date=today - timedelta(days=1),
            start_time=time(10), duration="0.5", now=self.aware(today - timedelta(days=1), time(9)),
        )[0]
        upcoming = schedule_classes(
            tutor=self.tutor, pairing=self.pairing, class_date=today + timedelta(days=2),
            start_time=time(10), duration="0.5",
        )[0]
        future = schedule_classes(
            tutor=self.tutor, pairing=self.pairing, class_date=today + timedelta(days=10),
            start_time=time(10), duration="0.5",
        )[0]
        self.client.force_login(self.tutor)
        response = self.client.get(reverse("accounts:dashboard"))
        self.assertContains(response, "即將課程")
        self.assertContains(response, "未來課程")
        self.assertContains(response, "學期課程")
        self.assertNotContains(response, "schedule-group-past")
        self.assertContains(response, "semester-hours-card")
        self.assertContains(response, "累積時數總覽")
        self.assertContains(response, "data-info-toggle")
        self.assertEqual([row.pk for row in response.context["upcoming_sessions"]], [upcoming.pk])
        self.assertEqual([row.pk for row in response.context["future_sessions"]], [future.pk])
        self.assertEqual([row.pk for row in response.context["past_sessions"]], [past.pk])

    def test_recent_missed_class_can_move_to_future_and_releases_old_week(self):
        today = timezone.localdate()
        old_date = today - timedelta(days=1)
        session = schedule_classes(
            tutor=self.tutor, pairing=self.pairing, class_date=old_date,
            start_time=time(10), duration="2.0", now=self.aware(old_date, time(9)),
        )[0]
        new_date = today + timedelta(days=8)
        changed = reschedule_class(
            session_id=session.pk,
            tutor=self.tutor,
            class_date=new_date,
            start_time=time(23),
            duration="1.5",
            now=self.aware(today, time(12)),
        )
        self.assertEqual(changed[0].class_date, new_date)
        self.assertEqual(changed[0].duration, 1.5)

    def test_class_alert_appears_for_admin_and_disappears_after_reporter_cancels(self):
        class_date = timezone.localdate()
        session = schedule_classes(
            tutor=self.tutor, pairing=self.pairing, class_date=class_date,
            start_time=time(10), duration="1.0", now=self.aware(class_date, time(9)),
        )[0]
        with self.assertRaises(ValidationError):
            report_class_alert(
                session_id=session.pk,
                reporter=self.tutor,
                reason=ClassAlertReason.CANNOT_REACH,
                now=self.aware(class_date, time(9, 55)),
            )
        alert = report_class_alert(
            session_id=session.pk,
            reporter=self.tutor,
            reason=ClassAlertReason.CANNOT_REACH,
            now=self.aware(class_date, time(10, 15)),
        )
        self.assertEqual(alert.subject, self.tutee)
        admin = User.objects.create_superuser(username="ALERT-ADMIN", password="Admin-password-2026")
        self.client.force_login(admin)
        response = self.client.get(reverse("accounts:dashboard"))
        self.assertContains(response, "課堂通報")
        self.assertContains(response, "聯絡不到對方")
        cancel_class_alert(alert_id=alert.pk, reporter=self.tutor)
        alert.refresh_from_db()
        self.assertEqual(alert.status, ClassAlertStatus.CANCELLED)
        response = self.client.get(reverse("accounts:dashboard"))
        self.assertNotContains(response, "聯絡不到對方")

    def test_admin_can_resolve_class_alert_and_history_shows_note(self):
        class_date = timezone.localdate()
        session = schedule_classes(
            tutor=self.tutor, pairing=self.pairing, class_date=class_date,
            start_time=time(10), duration="1.0", now=self.aware(class_date, time(9)),
        )[0]
        alert = report_class_alert(
            session_id=session.pk,
            reporter=self.tutor,
            reason=ClassAlertReason.CANNOT_REACH,
            now=self.aware(class_date, time(10, 15)),
        )
        admin = User.objects.create_superuser(username="ALERT-RESOLVE-ADMIN", password="Admin-password-2026")
        resolved = resolve_class_alert(alert_id=alert.pk, admin=admin, note="已與雙方確認過情況")
        self.assertEqual(resolved.status, ClassAlertStatus.RESOLVED)
        self.assertEqual(resolved.resolved_by, admin)

        self.client.force_login(admin)
        response = self.client.get(reverse("accounts:dashboard"))
        self.assertContains(response, "已與雙方確認過情況")
        self.assertContains(response, "目前沒有待處理的課堂通報")

    def test_resolved_class_alert_cannot_be_cancelled_and_active_cannot_be_resolved_twice(self):
        class_date = timezone.localdate()
        session = schedule_classes(
            tutor=self.tutor, pairing=self.pairing, class_date=class_date,
            start_time=time(10), duration="1.0", now=self.aware(class_date, time(9)),
        )[0]
        alert = report_class_alert(
            session_id=session.pk,
            reporter=self.tutor,
            reason=ClassAlertReason.OTHER,
            note="其他狀況",
            now=self.aware(class_date, time(10, 15)),
        )
        admin = User.objects.create_superuser(username="ALERT-RESOLVE-ADMIN2", password="Admin-password-2026")
        resolve_class_alert(alert_id=alert.pk, admin=admin, note="")
        with self.assertRaises(ValidationError):
            cancel_class_alert(alert_id=alert.pk, reporter=self.tutor)
        with self.assertRaises(ValidationError):
            resolve_class_alert(alert_id=alert.pk, admin=admin, note="")

    def test_non_admin_cannot_resolve_class_alert(self):
        class_date = timezone.localdate()
        session = schedule_classes(
            tutor=self.tutor, pairing=self.pairing, class_date=class_date,
            start_time=time(10), duration="1.0", now=self.aware(class_date, time(9)),
        )[0]
        alert = report_class_alert(
            session_id=session.pk,
            reporter=self.tutor,
            reason=ClassAlertReason.OTHER,
            note="其他狀況",
            now=self.aware(class_date, time(10, 15)),
        )
        with self.assertRaises(ValidationError):
            resolve_class_alert(alert_id=alert.pk, admin=self.tutee, note="")
        self.client.force_login(self.tutor)
        response = self.client.post(reverse("tutoring:resolve_alert", args=[alert.pk]), {"note": ""})
        self.assertEqual(response.status_code, 404)

    def test_incident_report_is_not_restricted_to_class_time_window(self):
        class_date = timezone.localdate() - timedelta(days=3)
        session = schedule_classes(
            tutor=self.tutor, pairing=self.pairing, class_date=class_date,
            start_time=time(10), duration="1.0", now=self.aware(class_date, time(9)),
        )[0]
        report = submit_incident_report(
            session_id=session.pk,
            reporter=self.tutor,
            category=IncidentReportCategory.STUDENT_ABSENT,
            content="學生當天未出席，也聯絡不上。",
        )
        self.assertEqual(report.status, IncidentReportStatus.PENDING)
        self.assertEqual(report.reporter, self.tutor)

    def test_incident_report_rejects_non_participant(self):
        class_date = timezone.localdate()
        session = schedule_classes(
            tutor=self.tutor, pairing=self.pairing, class_date=class_date,
            start_time=time(10), duration="1.0", now=self.aware(class_date, time(9)),
        )[0]
        bystander = User.objects.create_user(
            username="BYSTANDER", password="Test-password-2026", role=Role.TUTOR
        )
        with self.assertRaises(ValidationError):
            submit_incident_report(
                session_id=session.pk,
                reporter=bystander,
                category=IncidentReportCategory.OTHER,
                content="不是這堂課的參與者。",
            )

    def test_incident_report_requires_valid_category_and_content(self):
        class_date = timezone.localdate()
        session = schedule_classes(
            tutor=self.tutor, pairing=self.pairing, class_date=class_date,
            start_time=time(10), duration="1.0", now=self.aware(class_date, time(9)),
        )[0]
        with self.assertRaises(ValidationError):
            submit_incident_report(
                session_id=session.pk, reporter=self.tutor, category="NOT_A_CATEGORY", content="測試"
            )
        with self.assertRaises(ValidationError):
            submit_incident_report(
                session_id=session.pk,
                reporter=self.tutor,
                category=IncidentReportCategory.OTHER,
                content="   ",
            )

    def test_admin_can_resolve_incident_report_and_dashboard_history_updates(self):
        class_date = timezone.localdate()
        session = schedule_classes(
            tutor=self.tutor, pairing=self.pairing, class_date=class_date,
            start_time=time(10), duration="1.0", now=self.aware(class_date, time(9)),
        )[0]
        report = submit_incident_report(
            session_id=session.pk,
            reporter=self.tutee,
            category=IncidentReportCategory.VENUE_ISSUE,
            content="教室臨時被佔用。",
        )
        admin = User.objects.create_superuser(username="INCIDENT-ADMIN", password="Admin-password-2026")
        self.client.force_login(admin)
        response = self.client.get(reverse("accounts:dashboard"))
        self.assertContains(response, "異常回報")
        self.assertContains(response, "教室臨時被佔用")

        response = self.client.post(
            reverse("tutoring:resolve_incident_report", args=[report.pk]),
            {"note": "已協調改到 202 教室"},
        )
        self.assertRedirects(response, reverse("accounts:dashboard") + "#incident-reports")
        report.refresh_from_db()
        self.assertEqual(report.status, IncidentReportStatus.RESOLVED)
        self.assertEqual(report.resolved_by, admin)
        self.assertEqual(report.resolution_note, "已協調改到 202 教室")

        response = self.client.get(reverse("accounts:dashboard"))
        self.assertContains(response, "已協調改到 202 教室")

    def test_non_admin_cannot_resolve_incident_report(self):
        class_date = timezone.localdate()
        session = schedule_classes(
            tutor=self.tutor, pairing=self.pairing, class_date=class_date,
            start_time=time(10), duration="1.0", now=self.aware(class_date, time(9)),
        )[0]
        report = submit_incident_report(
            session_id=session.pk,
            reporter=self.tutor,
            category=IncidentReportCategory.OTHER,
            content="測試內容",
        )
        with self.assertRaises(ValidationError):
            resolve_incident_report(report_id=report.pk, admin=self.tutee, note="")
        self.client.force_login(self.tutor)
        response = self.client.post(
            reverse("tutoring:resolve_incident_report", args=[report.pk]), {"note": ""}
        )
        self.assertEqual(response.status_code, 404)


class V2FeatureTests(TestCase):
    def setUp(self):
        today = timezone.localdate()
        self.semester = Semester.objects.create(
            name_zh="目前學期", name_en="Current semester",
            starts_on=today - timedelta(days=20), ends_on=today + timedelta(days=20),
            is_active=True,
        )
        self.ntnu_program = PartnerProgram.objects.get(code="NTNU")
        tutor_roster = RosterEntry.objects.create(
            student_id="V2-TUTOR", name_zh="V2老師", role=Role.TUTOR,
            education_level=EducationLevel.MASTER, identity_category=IdentityCategory.LOCAL,
        )
        tutee_roster = RosterEntry.objects.create(
            student_id="V2-TUTEE", name_zh="V2學生", role=Role.TUTEE,
            education_level=EducationLevel.NOT_APPLICABLE, identity_category=IdentityCategory.INTERNATIONAL,
            program=self.ntnu_program,
        )
        self.tutor = User.objects.create_user(username="V2-TUTOR", password="Password-2026", role=Role.TUTOR, roster_entry=tutor_roster)
        self.tutee = User.objects.create_user(username="V2-TUTEE", password="Password-2026", role=Role.TUTEE, roster_entry=tutee_roster)
        self.pairing = Pairing.objects.create(semester=self.semester, tutor=self.tutor, tutee=self.tutee)

    def test_active_pairing_can_message_and_ended_pairing_is_read_only(self):
        self.client.force_login(self.tutor)
        url = reverse("tutoring:pairing_messages", args=[self.pairing.pk])
        response = self.client.post(url, {"body": "明天見 / See you tomorrow"})
        self.assertRedirects(response, url)
        self.assertTrue(PairingMessage.objects.filter(pairing=self.pairing, sender=self.tutor).exists())
        self.pairing.status = PairingStatus.ENDED
        self.pairing.save(update_fields=["status"])
        response = self.client.post(url, {"body": "Should not send"}, follow=True)
        self.assertContains(response, "只能查看歷史訊息")
        self.assertEqual(PairingMessage.objects.filter(pairing=self.pairing).count(), 1)
        response = self.client.get(reverse("accounts:dashboard"))
        self.assertContains(response, "過往對話紀錄")
        self.assertContains(response, "查看紀錄 / View history")
        self.assertContains(response, url)
        response = self.client.get(url)
        self.assertContains(response, "明天見 / See you tomorrow")
        self.assertContains(response, "已結束 · 僅供查看")
        self.assertNotContains(response, reverse("accounts:matched_profile", args=[self.tutee.pk]))

    def test_dashboard_shows_unread_badge_and_preview_then_clears_on_open(self):
        self.client.force_login(self.tutee)
        self.client.post(
            reverse("tutoring:pairing_messages", args=[self.pairing.pk]),
            {"body": "老師好，請問明天上課地點在哪裡？"},
        )
        message_url = reverse("tutoring:pairing_messages", args=[self.pairing.pk])

        self.client.force_login(self.tutor)
        response = self.client.get(reverse("accounts:dashboard"))
        self.assertContains(response, "老師好，請問明天上課地點在哪裡？")
        self.assertContains(response, "私訊<small>Messages</small></b><em>1</em>", html=False)
        self.assertContains(response, '<b class="unread-badge">1</b>', html=False)

        self.client.get(message_url)
        response = self.client.get(reverse("accounts:dashboard"))
        self.assertNotContains(response, 'unread-badge')

    def test_conversation_list_sorts_by_most_recent_message(self):
        other_tutee_roster = RosterEntry.objects.create(
            student_id="V2-TUTEE2", name_zh="V2學生二", role=Role.TUTEE,
            education_level=EducationLevel.NOT_APPLICABLE, identity_category=IdentityCategory.INTERNATIONAL,
            program=self.ntnu_program,
        )
        other_tutee = User.objects.create_user(
            username="V2-TUTEE2", password="Password-2026", role=Role.TUTEE, roster_entry=other_tutee_roster,
        )
        other_pairing = Pairing.objects.create(semester=self.semester, tutor=self.tutor, tutee=other_tutee)

        self.client.force_login(self.tutee)
        self.client.post(reverse("tutoring:pairing_messages", args=[self.pairing.pk]), {"body": "第一則訊息"})
        self.client.force_login(other_tutee)
        self.client.post(reverse("tutoring:pairing_messages", args=[other_pairing.pk]), {"body": "比較新的訊息"})

        self.client.force_login(self.tutor)
        response = self.client.get(reverse("accounts:dashboard"))
        content = response.content.decode()
        self.assertLess(content.index("比較新的訊息"), content.index("第一則訊息"))

    def test_unrelated_user_cannot_open_messages(self):
        outsider = User.objects.create_user(username="V2-OUT", password="Password-2026", role=Role.TUTEE)
        self.client.force_login(outsider)
        self.assertEqual(self.client.get(reverse("tutoring:pairing_messages", args=[self.pairing.pk])).status_code, 404)

    def test_admin_class_overview_links_to_tutor_schedule(self):
        ClassSession.objects.create(
            pairing=self.pairing,
            class_date=timezone.localdate(),
            start_time=time(10, 0),
            duration=1,
            created_by=self.tutor,
        )
        admin = User.objects.create_superuser(username="CLASS-OVERVIEW-ADMIN", password="Admin-password-2026")
        self.client.force_login(admin)
        response = self.client.get(reverse("accounts:dashboard"))
        schedule_url = reverse("accounts:admin_tutor_schedule", args=[self.tutor.pk])
        self.assertContains(response, "老師名單")
        self.assertContains(response, schedule_url)
        self.assertNotContains(response, "Latest 100 classes")
        response = self.client.get(f"{schedule_url}?semester={self.semester.pk}")
        self.assertContains(response, "TUTOR SCHEDULE")
        self.assertContains(response, self.tutee.username)

    def test_non_admin_cannot_open_admin_tutor_schedule(self):
        self.client.force_login(self.tutor)
        response = self.client.get(reverse("accounts:admin_tutor_schedule", args=[self.tutor.pk]))
        self.assertEqual(response.status_code, 404)

    def test_admin_user_profile_aggregates_pairings_hours_and_reports(self):
        session = ClassSession.objects.create(
            pairing=self.pairing, class_date=timezone.localdate(), start_time=time(10, 0),
            duration=1, created_by=self.tutor,
        )
        ClassAlert.objects.create(
            session=session, reporter=self.tutor, subject=self.tutee, reason=ClassAlertReason.CANNOT_REACH,
        )
        IncidentReport.objects.create(
            session=session, reporter=self.tutee, category=IncidentReportCategory.VENUE_ISSUE, content="教室有問題",
        )
        admin = User.objects.create_superuser(username="PROFILE-ADMIN", password="Admin-password-2026")
        HourAdjustment.objects.create(
            user=self.tutor, semester=self.semester, program=self.ntnu_program,
            hours=Decimal("2.5"), reason="舊紙本資料補登測試", created_by=admin,
        )
        self.client.force_login(admin)

        response = self.client.get(reverse("accounts:admin_user_profile", args=[self.tutor.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.tutee.bilingual_name)
        self.assertContains(response, "場地問題 / Venue issue")
        self.assertContains(response, "舊紙本資料補登測試")
        self.assertContains(response, "+2.5 小時")

        response = self.client.get(reverse("accounts:admin_user_profile", args=[self.tutee.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.tutor.bilingual_name)
        self.assertContains(response, "場地問題 / Venue issue")

    def test_non_admin_cannot_open_admin_user_profile(self):
        self.client.force_login(self.tutor)
        response = self.client.get(reverse("accounts:admin_user_profile", args=[self.tutee.pk]))
        self.assertEqual(response.status_code, 404)

    def test_admin_export_defaults_to_xlsx_and_can_filter_by_semester_and_selected_user(self):
        session = ClassSession.objects.create(
            pairing=self.pairing,
            class_date=timezone.localdate(),
            start_time=time(11, 0), duration=1, created_by=self.tutor,
        )
        admin = User.objects.create_superuser(username="EXPORT-ADMIN", password="Admin-password-2026")
        self.client.force_login(admin)
        response = self.client.post(reverse("tutoring:export_excel"), {
            "scope": "selected",
            "user_ids": [self.tutor.pk],
            "period_mode": "semester",
            "semester_id": self.semester.pk,
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        workbook = openpyxl.load_workbook(BytesIO(response.content))
        rows = list(workbook.active.iter_rows(values_only=True))
        self.assertIn(str(session.class_date), rows[1])

    def test_admin_export_can_produce_real_xlsx(self):
        session = ClassSession.objects.create(
            pairing=self.pairing,
            class_date=timezone.localdate(),
            start_time=time(11, 0), duration=1, created_by=self.tutor,
        )
        admin = User.objects.create_superuser(username="EXPORT-XLSX-ADMIN", password="Admin-password-2026")
        self.client.force_login(admin)
        response = self.client.post(reverse("tutoring:export_excel"), {
            "scope": "selected",
            "user_ids": [self.tutor.pk],
            "period_mode": "semester",
            "semester_id": self.semester.pk,
            "file_format": "xlsx",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        self.assertTrue(response["Content-Disposition"].endswith('.xlsx"'))
        workbook = openpyxl.load_workbook(BytesIO(response.content))
        worksheet = workbook.active
        rows = list(worksheet.iter_rows(values_only=True))
        self.assertEqual(rows[0][0], "學號 Student ID")
        self.assertIn(str(session.class_date), rows[1])

    def test_admin_export_can_produce_csv(self):
        session = ClassSession.objects.create(
            pairing=self.pairing,
            class_date=timezone.localdate(),
            start_time=time(11, 0), duration=1, created_by=self.tutor,
        )
        admin = User.objects.create_superuser(username="EXPORT-CSV-ADMIN", password="Admin-password-2026")
        self.client.force_login(admin)
        response = self.client.post(reverse("tutoring:export_excel"), {
            "scope": "selected",
            "user_ids": [self.tutor.pk],
            "period_mode": "semester",
            "semester_id": self.semester.pk,
            "file_format": "csv",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv")
        self.assertTrue(response["Content-Disposition"].endswith('.csv"'))
        decoded = response.content.decode("utf-8-sig")
        self.assertIn("學號 Student ID", decoded)
        self.assertIn(str(session.class_date), decoded)

    def test_admin_export_can_produce_pdf(self):
        ClassSession.objects.create(
            pairing=self.pairing,
            class_date=timezone.localdate(),
            start_time=time(11, 0), duration=1, created_by=self.tutor,
        )
        admin = User.objects.create_superuser(username="EXPORT-PDF-ADMIN", password="Admin-password-2026")
        self.client.force_login(admin)
        response = self.client.post(reverse("tutoring:export_excel"), {
            "scope": "selected",
            "user_ids": [self.tutor.pk],
            "period_mode": "semester",
            "semester_id": self.semester.pk,
            "file_format": "pdf",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response["Content-Disposition"].endswith('.pdf"'))
        self.assertTrue(response.content.startswith(b"%PDF"))
        from pypdf import PdfReader
        self.assertGreaterEqual(len(PdfReader(BytesIO(response.content)).pages), 1)

    def test_admin_export_rejects_reversed_date_range(self):
        admin = User.objects.create_superuser(username="EXPORT-RANGE-ADMIN", password="Admin-password-2026")
        self.client.force_login(admin)
        response = self.client.post(reverse("tutoring:export_excel"), {
            "scope": "all", "period_mode": "range",
            "starts_on": "2026-08-01", "ends_on": "2026-07-01",
        })
        self.assertRedirects(response, f"{reverse('accounts:dashboard')}#export")

    def test_archived_past_semester_remains_downloadable(self):
        today = timezone.localdate()
        past = Semester.objects.create(
            name_zh="過去學期", name_en="Past semester",
            starts_on=today - timedelta(days=100), ends_on=today - timedelta(days=20),
            is_active=False,
        )
        form = HoursDownloadForm()
        self.assertIn(past, list(form.fields["semester"].queryset))

    def test_semester_makeup_and_download_deadlines(self):
        self.assertEqual(self.semester.makeup_deadline_at.date(), self.semester.ends_on + timedelta(days=1))
        self.assertEqual(self.semester.hours_download_at.date(), self.semester.ends_on + timedelta(days=3))

    def test_detailed_certificate_requires_at_least_one_field(self):
        today = timezone.localdate()
        form = HoursDownloadForm({
            "mode": "range", "starts_on": today - timedelta(days=200),
            "ends_on": today - timedelta(days=190), "version": "detailed",
        })
        self.assertFalse(form.is_valid())
        self.assertIn("detail_fields", form.errors)

    def test_summary_and_detailed_certificate_use_pdf_template(self):
        from pypdf import PdfReader

        today = timezone.localdate()
        data = {
            "user": self.tutor, "starts_on": today - timedelta(days=30), "ends_on": today,
            "sections": [], "total": 0, "generated_at": timezone.now(),
        }
        summary = build_hours_pdf(data, version="summary", program=self.ntnu_program)
        detailed = build_hours_pdf(data, version="detailed", detail_fields=["date", "hours"], program=self.ntnu_program)
        self.assertTrue(summary.startswith(b"%PDF"))
        self.assertTrue(detailed.startswith(b"%PDF"))
        self.assertEqual(len(PdfReader(BytesIO(summary)).pages), 1)
        self.assertIn("實習證明", PdfReader(BytesIO(summary)).pages[0].extract_text())


class PartnerProgramCertificateTests(TestCase):
    def setUp(self):
        today = timezone.localdate()
        self.semester = Semester.objects.create(
            name_zh="方案測試學期", name_en="Program test semester",
            starts_on=today - timedelta(days=20), ends_on=today - timedelta(days=10),
            is_active=False,
        )
        self.ntnu_program = PartnerProgram.objects.get(code="NTNU")
        self.maryland_program = PartnerProgram.objects.get(code="MARYLAND")
        tutor_roster = RosterEntry.objects.create(
            student_id="PP-TUTOR", name_zh="方案老師", role=Role.TUTOR,
            education_level=EducationLevel.MASTER, identity_category=IdentityCategory.LOCAL,
        )
        tutee_roster = RosterEntry.objects.create(
            student_id="PP-TUTEE", name_zh="方案學生", role=Role.TUTEE,
            education_level=EducationLevel.NOT_APPLICABLE, identity_category=IdentityCategory.INTERNATIONAL,
            program=self.ntnu_program,
        )
        self.tutor = User.objects.create_user(
            username="PP-TUTOR", password="Password-2026", role=Role.TUTOR, roster_entry=tutor_roster
        )
        self.tutee = User.objects.create_user(
            username="PP-TUTEE", password="Password-2026", role=Role.TUTEE, roster_entry=tutee_roster
        )
        self.pairing = Pairing.objects.create(semester=self.semester, tutor=self.tutor, tutee=self.tutee)
        ClassSession.objects.create(
            pairing=self.pairing, class_date=today - timedelta(days=15),
            start_time=time(10), duration=1, created_by=self.tutor,
        )

    def test_ntnu_tutee_can_now_download_hours(self):
        self.assertTrue(user_has_hour_records(self.tutee))

    def test_tutor_available_programs_only_lists_programs_actually_tutored(self):
        codes = {program.code for program in tutor_available_programs(self.tutor)}
        self.assertEqual(codes, {"NTNU"})

        maryland_tutee_roster = RosterEntry.objects.create(
            student_id="PP-TUTEE-MD", name_zh="方案馬里蘭學生", role=Role.TUTEE,
            education_level=EducationLevel.NOT_APPLICABLE, identity_category=IdentityCategory.INTERNATIONAL,
            program=self.maryland_program,
        )
        maryland_tutee = User.objects.create_user(
            username="PP-TUTEE-MD", password="Password-2026", role=Role.TUTEE, roster_entry=maryland_tutee_roster
        )
        maryland_pairing = Pairing.objects.create(semester=self.semester, tutor=self.tutor, tutee=maryland_tutee)
        ClassSession.objects.create(
            pairing=maryland_pairing, class_date=timezone.localdate() - timedelta(days=15),
            start_time=time(14), duration=1, created_by=self.tutor,
        )
        codes = {program.code for program in tutor_available_programs(self.tutor)}
        self.assertEqual(codes, {"NTNU", "MARYLAND"})

    def test_program_selector_is_tutor_only_and_uses_practicum_label(self):
        tutor_form = HoursDownloadForm(user=self.tutor)
        self.assertEqual(tutor_form.fields["program"].label, "實習計劃 / Practicum program")
        self.assertNotIn("program", HoursDownloadForm(user=self.tutee).fields)

    def test_download_hours_requires_program_for_tutor(self):
        self.client.force_login(self.tutor)
        today = timezone.localdate()
        response = self.client.post(
            reverse("tutoring:download_hours"),
            {
                "mode": "range", "starts_on": today - timedelta(days=10), "ends_on": today,
                "version": "summary", "language": "zh",
            },
        )
        self.assertRedirects(response, f"{reverse('accounts:dashboard')}#hours")
        messages = list(response.wsgi_request._messages)
        self.assertTrue(any("實習計劃" in str(message) for message in messages))

    def test_tutor_can_download_ntnu_certificate_via_dropdown(self):
        self.client.force_login(self.tutor)
        today = timezone.localdate()
        response = self.client.post(
            reverse("tutoring:download_hours"),
            {
                "mode": "range", "starts_on": today - timedelta(days=10), "ends_on": today,
                "version": "summary", "program": self.ntnu_program.pk, "language": "zh",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("attachment", response["Content-Disposition"])

    def test_tutor_can_preview_certificate_inline_without_forcing_download(self):
        self.client.force_login(self.tutor)
        today = timezone.localdate()
        response = self.client.post(
            reverse("tutoring:download_hours"),
            {
                "mode": "range", "starts_on": today - timedelta(days=10), "ends_on": today,
                "version": "summary", "program": self.ntnu_program.pk, "intent": "preview", "language": "zh",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("inline", response["Content-Disposition"])
        log = AuditLog.objects.get(event_type="HOURS_PDF_PREVIEWED")
        self.assertEqual(log.actor, self.tutor)

    def test_ntnu_tutee_downloads_tutee_specific_template(self):
        from pypdf import PdfReader

        self.client.force_login(self.tutee)
        today = timezone.localdate()
        response = self.client.post(
            reverse("tutoring:download_hours"),
            {
                "mode": "range", "starts_on": today - timedelta(days=10), "ends_on": today,
                "version": "summary", "language": "zh",
            },
        )
        self.assertEqual(response.status_code, 200)
        text = PdfReader(BytesIO(response.content)).pages[0].extract_text()
        self.assertIn("接受華語輔導", text)
        self.assertIn("受輔導證明", text)

    def test_ntnu_tutor_same_month_period_is_not_repeated(self):
        from pypdf import PdfReader

        data = {
            "user": self.tutor,
            "starts_on": date(2026, 7, 1),
            "ends_on": date(2026, 7, 31),
            "sections": [],
            "total": 0,
            "generated_at": timezone.now(),
        }
        content = build_hours_pdf(data, version="summary", program=self.ntnu_program)
        extracted = PdfReader(BytesIO(content)).pages[0].extract_text()
        compact_text = extracted.replace(" ", "")
        self.assertIn("民國115年7月", compact_text)
        self.assertNotIn("7月-7月", compact_text)
        self.assertIn("學號PP-TUTOR，\n", compact_text)
        self.assertNotIn("PP-TUTOR\n，", compact_text)

    def test_tutor_can_download_maryland_certificate_now_that_template_is_shared(self):
        from pypdf import PdfReader

        maryland_tutee_roster = RosterEntry.objects.create(
            student_id="PP-TUTEE-MD2", name_zh="方案馬里蘭學生二", role=Role.TUTEE,
            education_level=EducationLevel.NOT_APPLICABLE, identity_category=IdentityCategory.INTERNATIONAL,
            program=self.maryland_program,
        )
        maryland_tutee = User.objects.create_user(
            username="PP-TUTEE-MD2", password="Password-2026", role=Role.TUTEE, roster_entry=maryland_tutee_roster
        )
        maryland_pairing = Pairing.objects.create(semester=self.semester, tutor=self.tutor, tutee=maryland_tutee)
        ClassSession.objects.create(
            pairing=maryland_pairing, class_date=timezone.localdate() - timedelta(days=15),
            start_time=time(14), duration=1, created_by=self.tutor,
        )
        self.client.force_login(self.tutor)
        today = timezone.localdate()
        response = self.client.post(
            reverse("tutoring:download_hours"),
            {
                "mode": "range", "starts_on": today - timedelta(days=10), "ends_on": today,
                "version": "summary", "program": self.maryland_program.pk, "language": "zh",
            },
        )
        self.assertEqual(response.status_code, 200)
        text = PdfReader(BytesIO(response.content)).pages[0].extract_text()
        self.assertIn("語言交換服務證明", text)

    def _make_verified_session(self, pairing, other_party, class_date):
        session = ClassSession.objects.create(
            pairing=pairing, class_date=class_date, start_time=time(10), duration=1, created_by=self.tutor,
        )
        signed_at = self.aware_datetime(class_date, time(10, 5))
        for participant in (self.tutor, other_party):
            Attendance.objects.create(session=session, participant=participant, signed_at=signed_at)
        for author in (self.tutor, other_party):
            ClassRecord.objects.create(
                session=session, author=author, location="測試教室", topic="會話練習",
                content="練習內容", reflection="回饋內容",
            )
        for reviewer, subject in ((self.tutor, other_party), (other_party, self.tutor)):
            ClassConfirmation.objects.create(
                session=session, reviewer=reviewer, subject=subject,
                attendance_confirmed=True, record_confirmed=True, status=ConfirmationStatus.CONFIRMED,
            )
        return session

    def aware_datetime(self, day, clock):
        return timezone.make_aware(datetime.combine(day, clock), timezone.get_current_timezone())

    def test_download_hours_only_counts_selected_programs_sessions(self):
        maryland_tutee_roster = RosterEntry.objects.create(
            student_id="PP-TUTEE-MD3", name_zh="方案馬里蘭學生三", role=Role.TUTEE,
            education_level=EducationLevel.NOT_APPLICABLE, identity_category=IdentityCategory.INTERNATIONAL,
            program=self.maryland_program,
        )
        maryland_tutee = User.objects.create_user(
            username="PP-TUTEE-MD3", password="Password-2026", role=Role.TUTEE, roster_entry=maryland_tutee_roster
        )
        maryland_pairing = Pairing.objects.create(semester=self.semester, tutor=self.tutor, tutee=maryland_tutee)
        past_date = timezone.localdate() - timedelta(days=12)
        self._make_verified_session(self.pairing, self.tutee, past_date)
        self._make_verified_session(maryland_pairing, maryland_tutee, past_date)

        self.client.force_login(self.tutor)
        today = timezone.localdate()
        response = self.client.post(
            reverse("tutoring:download_hours"),
            {
                "mode": "range", "starts_on": today - timedelta(days=20), "ends_on": today,
                "version": "summary", "program": self.ntnu_program.pk, "language": "zh",
            },
        )
        self.assertEqual(response.status_code, 200)
        from pypdf import PdfReader
        text = PdfReader(BytesIO(response.content)).pages[0].extract_text()
        self.assertIn("總計授課 1 小時", text)

    def test_hour_adjustment_rejects_non_positive_hours_and_wrong_role(self):
        admin = User.objects.create_superuser(username="ADJ-ADMIN", password="Admin-password-2026")
        adjustment = HourAdjustment(
            user=self.tutor, semester=self.semester, program=self.ntnu_program,
            hours=Decimal("0"), reason="測試", created_by=admin,
        )
        with self.assertRaises(ValidationError):
            adjustment.full_clean()

        admin_as_subject = HourAdjustment(
            user=admin, semester=self.semester, program=self.ntnu_program,
            hours=Decimal("1"), reason="測試", created_by=admin,
        )
        with self.assertRaises(ValidationError):
            admin_as_subject.full_clean()

    def test_hour_adjustment_raises_certificate_total_only_for_matching_program_and_semester(self):
        admin = User.objects.create_superuser(username="ADJ-ADMIN2", password="Admin-password-2026")
        past_date = timezone.localdate() - timedelta(days=12)
        self._make_verified_session(self.pairing, self.tutee, past_date)
        HourAdjustment.objects.create(
            user=self.tutor, semester=self.semester, program=self.ntnu_program,
            hours=Decimal("2.5"), reason="舊紙本資料補登", created_by=admin,
        )
        HourAdjustment.objects.create(
            user=self.tutor, semester=self.semester, program=self.maryland_program,
            hours=Decimal("9"), reason="不同計畫，不應被算入", created_by=admin,
        )

        self.client.force_login(self.tutor)
        today = timezone.localdate()
        response = self.client.post(
            reverse("tutoring:download_hours"),
            {
                "mode": "range", "starts_on": today - timedelta(days=20), "ends_on": today,
                "version": "summary", "program": self.ntnu_program.pk, "language": "zh",
            },
        )
        self.assertEqual(response.status_code, 200)
        from pypdf import PdfReader
        text = PdfReader(BytesIO(response.content)).pages[0].extract_text()
        self.assertIn("總計授課 3.5 小時", text)

    def test_tutor_available_programs_includes_adjustment_only_program(self):
        admin = User.objects.create_superuser(username="ADJ-ADMIN3", password="Admin-password-2026")
        self.assertNotIn("MARYLAND", {program.code for program in tutor_available_programs(self.tutor)})
        HourAdjustment.objects.create(
            user=self.tutor, semester=self.semester, program=self.maryland_program,
            hours=Decimal("4"), reason="舊紙本資料，無資料庫課程紀錄", created_by=admin,
        )
        self.assertIn("MARYLAND", {program.code for program in tutor_available_programs(self.tutor)})

    def test_admin_creating_hour_adjustment_writes_audit_log(self):
        admin = User.objects.create_superuser(username="ADJ-ADMIN4", password="Admin-password-2026")
        self.client.force_login(admin)
        response = self.client.post(
            reverse("admin:tutoring_houradjustment_add"),
            {
                "user": self.tutor.pk, "semester": self.semester.pk, "program": self.ntnu_program.pk,
                "hours": "2.0", "reason": "舊紙本資料補登",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(HourAdjustment.objects.filter(user=self.tutor).count(), 1)
        adjustment = HourAdjustment.objects.get(user=self.tutor)
        self.assertEqual(adjustment.created_by, admin)
        self.assertTrue(
            AuditLog.objects.filter(event_type="HOUR_ADJUSTMENT_CREATED", target_user=self.tutor).exists()
        )

    def test_certificate_language_field_controls_filename_and_audit_log(self):
        self.client.force_login(self.tutor)
        today = timezone.localdate()
        response = self.client.post(
            reverse("tutoring:download_hours"),
            {
                "mode": "range", "starts_on": today - timedelta(days=10), "ends_on": today,
                "version": "summary", "program": self.ntnu_program.pk, "language": "en",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(f"-en-{today}.pdf", response["Content-Disposition"])
        log = AuditLog.objects.get(event_type="HOURS_PDF_DOWNLOADED", target_user=self.tutor)
        self.assertEqual(log.metadata["language"], "en")

    def test_english_certificate_uses_only_english_text_and_gregorian_date(self):
        from pypdf import PdfReader

        data = {
            "user": self.tutor, "starts_on": date(2026, 2, 1), "ends_on": date(2026, 7, 31),
            "sections": [], "total": 2, "generated_at": timezone.now(),
        }
        content = build_hours_pdf(data, version="summary", program=self.ntnu_program, language="en")
        text = PdfReader(BytesIO(content)).pages[0].extract_text()
        self.assertIn("Certificate of Counseling Practicum", text)
        self.assertNotIn("實習證明", text)
        self.assertNotIn("民國", text)

    def test_certificate_shows_bilingual_name_when_both_names_present_in_both_languages(self):
        """Regression test: <b>陳安然</b> alone (no explicit font) renders blank inside an
        English-default Paragraph, because ReportLab resolves <b> through the paragraph's
        registered font family, and CertificateSerif's bold face has no CJK glyphs."""
        from pypdf import PdfReader

        self.tutor.name_zh = "陳安然"
        self.tutor.name_en = "Jamie Chen"
        self.tutor.save()
        data = {
            "user": self.tutor, "starts_on": date(2026, 2, 1), "ends_on": date(2026, 7, 31),
            "sections": [], "total": 2, "generated_at": timezone.now(),
        }
        for language in ("zh", "en"):
            content = build_hours_pdf(data, version="summary", program=self.ntnu_program, language=language)
            text = PdfReader(BytesIO(content)).pages[0].extract_text()
            self.assertIn("陳安然", text)
            self.assertIn("Jamie Chen", text)

    def test_certificate_single_name_shows_no_dangling_slash_in_both_languages(self):
        from pypdf import PdfReader

        self.tutor.name_zh = "陳安然"
        self.tutor.name_en = ""
        self.tutor.save()
        data = {
            "user": self.tutor, "starts_on": date(2026, 2, 1), "ends_on": date(2026, 7, 31),
            "sections": [], "total": 2, "generated_at": timezone.now(),
        }
        for language in ("zh", "en"):
            content = build_hours_pdf(data, version="summary", program=self.ntnu_program, language=language)
            text = PdfReader(BytesIO(content)).pages[0].extract_text()
            self.assertIn("陳安然", text)
            self.assertNotIn("/", text)

    def test_missing_english_certificate_text_raises_clear_error(self):
        self.ntnu_program.tutor_certificate_plan_name_en = ""
        self.ntnu_program.tutor_certificate_activity_text_en = ""
        self.ntnu_program.save()
        data = {
            "user": self.tutor, "starts_on": date(2026, 2, 1), "ends_on": date(2026, 7, 31),
            "sections": [], "total": 2, "generated_at": timezone.now(),
        }
        # The NTNU tutor branch has hardcoded English text and does not depend on the
        # per-program plan_name_en/activity_text_en fields, so it stays unaffected;
        # blank out its title instead to exercise the same validation path.
        self.ntnu_program.tutor_certificate_title_en = ""
        self.ntnu_program.save()
        with self.assertRaises(ValidationError) as ctx:
            build_hours_pdf(data, version="summary", program=self.ntnu_program, language="en")
        self.assertIn("請洽系辦設定", str(ctx.exception))

    def test_missing_english_certificate_text_raises_clear_error_for_generic_program(self):
        self.maryland_program.tutee_certificate_plan_name_en = ""
        self.maryland_program.save()
        maryland_tutee_roster = RosterEntry.objects.create(
            student_id="PP-TUTEE-MD4", name_zh="方案馬里蘭學生四", role=Role.TUTEE,
            education_level=EducationLevel.NOT_APPLICABLE, identity_category=IdentityCategory.INTERNATIONAL,
            program=self.maryland_program,
        )
        maryland_tutee = User.objects.create_user(
            username="PP-TUTEE-MD4", password="Password-2026", role=Role.TUTEE, roster_entry=maryland_tutee_roster
        )
        data = {
            "user": maryland_tutee, "starts_on": date(2026, 2, 1), "ends_on": date(2026, 7, 31),
            "sections": [], "total": 2, "generated_at": timezone.now(),
        }
        with self.assertRaises(ValidationError) as ctx:
            build_hours_pdf(data, version="summary", program=self.maryland_program, language="en")
        self.assertIn("請洽系辦設定", str(ctx.exception))

    def test_english_detailed_certificate_uses_english_table_headers_and_pagination_label(self):
        from pypdf import PdfReader

        past_date = timezone.localdate() - timedelta(days=12)
        self._make_verified_session(self.pairing, self.tutee, past_date)
        self.client.force_login(self.tutor)
        today = timezone.localdate()
        response = self.client.post(
            reverse("tutoring:download_hours"),
            {
                "mode": "range", "starts_on": today - timedelta(days=20), "ends_on": today,
                "version": "detailed", "program": self.ntnu_program.pk, "language": "en",
                "detail_fields": ["date", "nationality", "level", "hours"],
            },
        )
        self.assertEqual(response.status_code, 200)
        text = PdfReader(BytesIO(response.content)).pages[0].extract_text()
        self.assertIn("Hours Detail", text)
        self.assertIn("Page 1 of 1", text)
        self.assertIn("Nationality", text)
        self.assertIn("Chinese level", text)
        self.assertNotIn("輔導時數明細", text)

