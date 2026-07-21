from datetime import date, datetime, time, timedelta
from io import BytesIO

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import EducationLevel, IdentityCategory, ProgramSource, Role, RosterEntry, User
from .forms import HoursDownloadForm, ScheduleClassForm, SemesterCreateForm
from .reporting import build_hours_pdf

from .models import (
    InvitationStatus,
    MatchingInvitation,
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
    ClassAlert,
    ClassAlertReason,
    ClassAlertStatus,
    ClassSession,
    ConfirmationStatus,
    MakeupReviewStatus,
)
from .services import (
    anonymous_tutee_candidates,
    archive_expired_semesters,
    check_in,
    cancel_class_alert,
    class_is_valid,
    confirm_counterpart,
    respond_to_invitation,
    review_makeup,
    report_class_alert,
    process_pending_pairing_releases,
    review_pairing_release_request,
    reschedule_class,
    schedule_classes,
    send_invitation,
    submit_pairing_release_request,
    submit_class_record,
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

    def test_create_form_only_asks_for_semester_dates(self):
        self.assertEqual(
            list(SemesterCreateForm().fields),
            ["name_zh", "name_en", "starts_on", "ends_on"],
        )

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


class MatchingTests(TestCase):
    def setUp(self):
        today = timezone.localdate()
        self.semester = Semester.objects.create(
            name_zh="115 學年度第 1 學期",
            name_en="Fall 2026",
            starts_on=today - timedelta(days=7),
            ends_on=today + timedelta(days=90),
            is_active=True,
        )
        self.tutor = self.make_tutor("TUTOR100", "知名小老師", "Known Tutor")
        self.tutee = self.make_tutee("TUTEE100", "知名外籍生", "Known Tutee", ProgramSource.NTNU)
        self.maryland = self.make_tutee("MARY100", "馬里蘭學生", "Maryland Student", ProgramSource.MARYLAND)

    def make_tutor(self, student_id, name_zh, name_en):
        roster = RosterEntry.objects.create(
            student_id=student_id,
            name_zh=name_zh,
            name_en=name_en,
            role=Role.TUTOR,
            education_level=EducationLevel.MASTER,
            identity_category=IdentityCategory.LOCAL,
            program_source=ProgramSource.NOT_APPLICABLE,
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

    def make_tutee(self, student_id, name_zh, name_en, program):
        roster = RosterEntry.objects.create(
            student_id=student_id,
            name_zh=name_zh,
            name_en=name_en,
            role=Role.TUTEE,
            education_level=EducationLevel.NOT_APPLICABLE,
            identity_category=IdentityCategory.INTERNATIONAL,
            program_source=program,
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

    def test_maryland_dashboard_hides_tutor_identity(self):
        self.client.force_login(self.maryland)
        response = self.client.get(reverse("accounts:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "知名小老師")
        self.assertNotContains(response, "Known Tutor")
        self.assertNotContains(response, "TUTOR100")
        self.assertContains(response, "Mandarin Chinese")

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
        pairing = Pairing.objects.create(semester=self.semester, tutor=self.tutor, tutee=self.tutee)

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
            initiator=self.maryland, tutor_id=self.tutor.pk, tutee_id=self.maryland.pk
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
        second = self.make_tutee("TUTEE200", "第二位學生", "Second Tutee", ProgramSource.NTNU)
        third = self.make_tutee("TUTEE300", "第三位學生", "Third Tutee", ProgramSource.NTNU)
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

    def test_auto_eligible_release_ends_pairing_after_three_days_and_cancels_future_class(self):
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
            requested_at + timedelta(days=3),
            delta=timedelta(seconds=1),
        )
        self.assertEqual(process_pending_pairing_releases(now=requested_at + timedelta(days=3, seconds=1)), 1)
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
        self.assertNotContains(response, "管理員三日內未處理時自動解除")
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


class ClassWorkflowTests(TestCase):
    def setUp(self):
        today = timezone.localdate()
        self.semester = Semester.objects.create(
            name_zh="V2 測試學期", name_en="V2 test semester",
            starts_on=today - timedelta(days=7), ends_on=today + timedelta(days=90),
            is_active=True,
        )
        tutor_roster = RosterEntry.objects.create(
            student_id="CLASS-TUTOR", name_zh="課程老師", name_en="Class Tutor", role=Role.TUTOR,
            education_level=EducationLevel.MASTER, identity_category=IdentityCategory.LOCAL,
            program_source=ProgramSource.NOT_APPLICABLE,
        )
        tutee_roster = RosterEntry.objects.create(
            student_id="CLASS-TUTEE", name_zh="課程學生", name_en="Class Student", role=Role.TUTEE,
            education_level=EducationLevel.NOT_APPLICABLE, identity_category=IdentityCategory.INTERNATIONAL,
            program_source=ProgramSource.NTNU,
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


class V2FeatureTests(TestCase):
    def setUp(self):
        today = timezone.localdate()
        self.semester = Semester.objects.create(
            name_zh="目前學期", name_en="Current semester",
            starts_on=today - timedelta(days=20), ends_on=today + timedelta(days=20),
            is_active=True,
        )
        tutor_roster = RosterEntry.objects.create(
            student_id="V2-TUTOR", name_zh="V2老師", role=Role.TUTOR,
            education_level=EducationLevel.MASTER, identity_category=IdentityCategory.LOCAL,
            program_source=ProgramSource.NOT_APPLICABLE,
        )
        tutee_roster = RosterEntry.objects.create(
            student_id="V2-TUTEE", name_zh="V2學生", role=Role.TUTEE,
            education_level=EducationLevel.NOT_APPLICABLE, identity_category=IdentityCategory.INTERNATIONAL,
            program_source=ProgramSource.NTNU,
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

    def test_admin_export_can_filter_by_semester_and_selected_user(self):
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
        self.assertEqual(response["Content-Type"], "application/vnd.ms-excel")
        self.assertIn(str(session.class_date).encode(), response.content)

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
        summary = build_hours_pdf(data, version="summary")
        detailed = build_hours_pdf(data, version="detailed", detail_fields=["date", "hours"])
        self.assertTrue(summary.startswith(b"%PDF"))
        self.assertTrue(detailed.startswith(b"%PDF"))
        self.assertEqual(len(PdfReader(BytesIO(summary)).pages), 1)
        self.assertIn("輔導實習時數證明書", PdfReader(BytesIO(summary)).pages[0].extract_text())
