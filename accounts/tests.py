from datetime import timedelta
import io
from unittest.mock import patch

import openpyxl
from django.conf import settings
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from tutoring.models import QualificationDocument, TuteeProfile, TutorProfile

from .models import (
    AccountStatus,
    AuditLog,
    EducationLevel,
    IdentityCategory,
    PartnerProgram,
    RegistrationDraft,
    Role,
    RosterEntry,
    User,
)


class RegistrationTests(TestCase):
    def setUp(self):
        self.roster = RosterEntry.objects.create(
            student_id="TEST1001",
            name_zh="測試學生",
            name_en="Test Student",
            role=Role.TUTOR,
            education_level=EducationLevel.MASTER,
            identity_category=IdentityCategory.LOCAL,
        )
        self.registration_data = {
            "name_zh": "測試學生",
            "name_en": "Test Student",
            "identity_category": "LOCAL",
            "education_level": "MASTER",
            "phone": "0912345678",
            "gender": "MALE",
            "native_language": "Mandarin Chinese",
            "nationality": "Taiwan",
            "department": "華語文教學系",
            "level_listening": "4",
            "level_speaking": "4",
            "level_reading": "4",
            "level_writing": "4",
            "teaching_notes": "可協助華語會話",
            "available_days": ["MON", "WED"],
            "available_time_slots": ["13:00-15:00"],
            "password1": "A-secure-local-password-2026",
            "password2": "A-secure-local-password-2026",
            "question_1": "Q1",
            "answer_1": "Alpha answer",
            "question_2": "Q2",
            "answer_2": "Beta answer",
            "question_3": "Q3",
            "answer_3": "Gamma answer",
            "agree": "on",
        }

    def register_tutor(self, data=None):
        response = self.client.post(
            reverse("accounts:register"),
            {
                "student_id": "TEST1001",
                "password1": self.registration_data["password1"],
                "password2": self.registration_data["password2"],
            },
        )
        self.assertRedirects(response, reverse("accounts:register_tutor"))
        return self.client.post(reverse("accounts:register_tutor"), data or self.registration_data)

    def test_registration_requires_roster_entry(self):
        response = self.client.post(reverse("accounts:register"), {"student_id": "UNKNOWN"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "找不到註冊學號，請聯絡系辦")
        self.assertFalse(User.objects.filter(username="UNKNOWN").exists())

    def test_registration_claims_roster_and_hashes_answers(self):
        response = self.register_tutor()
        self.assertRedirects(response, reverse("accounts:dashboard"))
        user = User.objects.get(username="TEST1001")
        self.roster.refresh_from_db()
        self.assertEqual(user.role, Role.TUTOR)
        self.assertTrue(user.check_password(self.registration_data["password1"]))
        self.assertIsNotNone(self.roster.claimed_at)
        self.assertFalse(RegistrationDraft.objects.filter(roster_entry=self.roster).exists())
        self.assertTrue(TutorProfile.objects.filter(tutor=user).exists())
        self.assertNotIn("Alpha answer", user.security_questions.answer_1_hash)
        self.assertTrue(user.security_questions.check_answers(["alpha ANSWER", "Beta answer", "Gamma answer"]))

    def test_security_questions_must_be_distinct(self):
        data = self.registration_data | {"question_3": "Q1"}
        self.client.post(
            reverse("accounts:register"),
            {"student_id": "TEST1001", "password1": data["password1"], "password2": data["password2"]},
        )
        response = self.client.post(reverse("accounts:register_tutor"), data)
        self.assertContains(response, "三題不可重複")
        self.assertFalse(User.objects.filter(username="TEST1001").exists())

    def test_account_does_not_exist_before_profile_setup(self):
        response = self.client.post(
            reverse("accounts:register"),
            {
                "student_id": "TEST1001",
                "password1": self.registration_data["password1"],
                "password2": self.registration_data["password2"],
            },
        )
        self.assertRedirects(response, reverse("accounts:register_tutor"))
        self.assertFalse(User.objects.filter(username="TEST1001").exists())
        self.assertTrue(RegistrationDraft.objects.filter(roster_entry=self.roster).exists())
        self.roster.refresh_from_db()
        self.assertIsNone(self.roster.claimed_at)

    def test_tutee_is_sent_to_tutee_form_and_profile_is_created(self):
        maryland = PartnerProgram.objects.get(code="MARYLAND")
        RosterEntry.objects.create(
            student_id="TUTEE1001",
            name_zh="受輔導學生",
            name_en="Tutee Student",
            role=Role.TUTEE,
            education_level=EducationLevel.NOT_APPLICABLE,
            identity_category=IdentityCategory.INTERNATIONAL,
            program=maryland,
        )
        response = self.client.post(
            reverse("accounts:register"),
            {
                "student_id": "TUTEE1001",
                "password1": "Another-secure-password-2026",
                "password2": "Another-secure-password-2026",
            },
        )
        self.assertRedirects(response, reverse("accounts:register_tutee"))
        data = {
            "name_zh": "受輔導學生",
            "name_en": "Tutee Student",
            "identity_category": "INTERNATIONAL",
            "phone": "0900000000",
            "gender": "FEMALE",
            "native_language": "English",
            "nationality": "United States",
            "department": "Languages",
            "overall_level": "B1",
            "learning_duration": "1_TO_2_YEARS",
            "level_listening": "3",
            "level_speaking": "2",
            "level_reading": "4",
            "level_writing": "3",
            "target_skills": ["LISTENING", "SPEAKING"],
            "skills_to_improve": "Conversation",
            "preferred_days": ["TUE"],
            "preferred_time_slots": ["15:00-17:00"],
            "password1": "Another-secure-password-2026",
            "password2": "Another-secure-password-2026",
            "question_1": "Q1",
            "answer_1": "First answer",
            "question_2": "Q2",
            "answer_2": "Second answer",
            "question_3": "Q3",
            "answer_3": "Third answer",
            "agree": "on",
        }
        response = self.client.post(reverse("accounts:register_tutee"), data)
        self.assertRedirects(response, reverse("accounts:dashboard"))
        user = User.objects.get(username="TUTEE1001")
        self.assertEqual(user.role, Role.TUTEE)
        self.assertEqual(TuteeProfile.objects.get(tutee=user).target_skills, ["LISTENING", "SPEAKING"])


class AccountRecoveryTests(TestCase):
    def setUp(self):
        RegistrationTests.setUp(self)
        self.client.post(
            reverse("accounts:register"),
            {
                "student_id": "TEST1001",
                "password1": self.registration_data["password1"],
                "password2": self.registration_data["password2"],
            },
        )
        self.client.post(reverse("accounts:register_tutor"), self.registration_data)
        self.client.post(reverse("accounts:logout"))

    def test_valid_answers_allow_password_reset(self):
        verify_data = {
            "student_id": "TEST1001",
            "question_1": "Q1",
            "answer_1": "Alpha answer",
            "question_2": "Q2",
            "answer_2": "Beta answer",
            "question_3": "Q3",
            "answer_3": "Gamma answer",
        }
        response = self.client.post(reverse("accounts:recover"), verify_data)
        self.assertRedirects(response, reverse("accounts:set_recovered_password"))
        response = self.client.post(
            reverse("accounts:set_recovered_password"),
            {"new_password1": "A-brand-new-password-2026", "new_password2": "A-brand-new-password-2026"},
        )
        self.assertRedirects(response, reverse("accounts:login"))
        user = User.objects.get(username="TEST1001")
        self.assertTrue(user.check_password("A-brand-new-password-2026"))

    def test_wrong_answers_do_not_reveal_account(self):
        response = self.client.post(
            reverse("accounts:recover"),
            {
                "student_id": "TEST1001",
                "question_1": "Q1",
                "answer_1": "wrong",
                "question_2": "Q2",
                "answer_2": "wrong",
                "question_3": "Q3",
                "answer_3": "wrong",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "資料無法驗證")


class LoginLockoutTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(username="LOGIN-LOCKOUT-TEST", password="Correct-password-2026", role=Role.TUTOR)

    def test_login_locks_after_five_failed_attempts(self):
        for _ in range(5):
            response = self.client.post(
                reverse("accounts:login"), {"username": "LOGIN-LOCKOUT-TEST", "password": "wrong-password"}
            )
            self.assertEqual(response.status_code, 200)
        response = self.client.post(
            reverse("accounts:login"), {"username": "LOGIN-LOCKOUT-TEST", "password": "Correct-password-2026"}
        )
        self.assertContains(response, "嘗試次數過多")
        self.assertFalse(response.wsgi_request.user.is_authenticated)

    def test_successful_login_clears_failed_attempt_count(self):
        for _ in range(3):
            self.client.post(reverse("accounts:login"), {"username": "LOGIN-LOCKOUT-TEST", "password": "wrong-password"})
        response = self.client.post(
            reverse("accounts:login"), {"username": "LOGIN-LOCKOUT-TEST", "password": "Correct-password-2026"}
        )
        self.assertRedirects(response, reverse("accounts:dashboard"))
        self.client.post(reverse("accounts:logout"))
        for _ in range(3):
            self.client.post(reverse("accounts:login"), {"username": "LOGIN-LOCKOUT-TEST", "password": "wrong-password"})
        response = self.client.post(
            reverse("accounts:login"), {"username": "LOGIN-LOCKOUT-TEST", "password": "Correct-password-2026"}
        )
        self.assertRedirects(response, reverse("accounts:dashboard"))


class QualificationTests(TestCase):
    def setUp(self):
        self.tutor = User.objects.create_user(username="TUTOR1", password="Tutor-password-2026", role=Role.TUTOR)
        self.admin = User.objects.create_superuser(username="ADMIN1", password="Admin-password-2026")

    def test_tutor_can_upload_valid_document(self):
        self.client.force_login(self.tutor)
        upload = SimpleUploadedFile("proof.pdf", b"%PDF-1.4\nsmall test file", content_type="application/pdf")
        response = self.client.post(reverse("accounts:upload_qualification"), {"file": upload})
        self.assertRedirects(response, reverse("accounts:dashboard"))
        document = QualificationDocument.objects.get(tutor=self.tutor)
        self.assertEqual(document.original_filename, "proof.pdf")

    def test_tutee_cannot_upload_qualification(self):
        tutee = User.objects.create_user(username="TUTEE1", password="Tutee-password-2026", role=Role.TUTEE)
        self.client.force_login(tutee)
        upload = SimpleUploadedFile("proof.pdf", b"%PDF-1.4\nsmall", content_type="application/pdf")
        response = self.client.post(reverse("accounts:upload_qualification"), {"file": upload})
        self.assertRedirects(response, reverse("accounts:dashboard"))
        self.assertFalse(QualificationDocument.objects.filter(tutor=tutee).exists())


@override_settings(DEBUG=True)
class RegistrationPreviewTests(TestCase):
    def test_tutor_preview_opens_without_registration_draft(self):
        response = self.client.get(reverse("accounts:preview_tutor"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "預覽模式")
        self.assertContains(response, "PREVIEW-TUTOR")

    def test_tutee_preview_opens_without_registration_draft(self):
        response = self.client.get(reverse("accounts:preview_tutee"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "預覽模式")
        self.assertContains(response, "PREVIEW-TUTEE")

    @override_settings(DEBUG=False)
    def test_preview_is_not_available_in_production(self):
        response = self.client.get(reverse("accounts:preview_tutor"))
        self.assertEqual(response.status_code, 404)


class ProfilePageTests(TestCase):
    def setUp(self):
        self.tutor = User.objects.create_user(
            username="PROFILE-TUTOR",
            password="Tutor-password-2026",
            role=Role.TUTOR,
            name_zh="王老師",
            name_en="Alex Wang",
        )
        TutorProfile.objects.create(
            tutor=self.tutor,
            gender="MALE",
            native_language="Mandarin Chinese",
            nationality="Taiwan",
            department="華語文教學系",
            level_listening=4,
            level_speaking=5,
            level_reading=4,
            level_writing=3,
            teaching_notes="重視口語互動",
            available_days=["MON", "WED"],
            available_time_slots=["13:00-15:00"],
        )
        self.tutee = User.objects.create_user(
            username="PROFILE-STUDENT",
            password="Student-password-2026",
            role=Role.TUTEE,
            name_zh="學生甲",
            name_en="Student A",
        )
        TuteeProfile.objects.create(
            tutee=self.tutee,
            gender="FEMALE",
            native_language="English",
            nationality="United States",
            department="Languages",
            overall_level="B1",
            learning_duration="1_TO_2_YEARS",
            target_skills=["LISTENING", "SPEAKING"],
            skills_to_improve="希望練習日常會話",
            preferred_days=["TUE"],
            preferred_time_slots=["15:00-17:00"],
        )

    def test_profile_requires_login(self):
        response = self.client.get(reverse("accounts:profile"))
        self.assertRedirects(response, f"{reverse('accounts:login')}?next={reverse('accounts:profile')}")

    def test_tutor_profile_shows_teaching_information_and_menu(self):
        self.client.force_login(self.tutor)
        response = self.client.get(reverse("accounts:profile"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "教學資料")
        self.assertContains(response, "重視口語互動")
        self.assertContains(response, reverse("accounts:handbook"))

    def test_tutee_profile_shows_learning_information(self):
        self.client.force_login(self.tutee)
        response = self.client.get(reverse("accounts:profile"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "學習資料")
        self.assertContains(response, "TOCFL B1")
        self.assertContains(response, "1～2 年")
        self.assertContains(response, "希望練習日常會話")

    def test_handbook_uses_signed_in_role(self):
        self.client.force_login(self.tutor)
        response = self.client.get(reverse("accounts:handbook"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "尋找學生")
        self.assertNotContains(response, "主動尋找老師")


class AdminDashboardNavigationTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="NAV-ADMIN", password="Admin-password-2026", name_zh="導覽管理員"
        )
        User.objects.create_user(username="NAV-TUTOR", password="Tutor-password-2026", role=Role.TUTOR)
        User.objects.create_user(username="NAV-TUTEE", password="Tutee-password-2026", role=Role.TUTEE)
        self.client.force_login(self.admin)

    def test_overview_stat_cards_link_to_filtered_management_views(self):
        response = self.client.get(reverse("accounts:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("admin:accounts_rosterentry_changelist"))
        self.assertContains(response, "?role__in=TUTOR%2CTUTEE")
        self.assertContains(response, "?role__exact=TUTOR")
        self.assertContains(response, "?role__exact=TUTEE")
        self.assertContains(response, 'data-dashboard-target="matching"', count=3)

    def test_registered_user_filter_is_accepted_by_django_admin(self):
        response = self.client.get(
            f"{reverse('admin:accounts_user_changelist')}?role__in=TUTOR%2CTUTEE"
        )
        self.assertEqual(response.status_code, 200)
        usernames = {user.username for user in response.context["cl"].result_list}
        self.assertEqual(usernames, {"NAV-TUTOR", "NAV-TUTEE"})


class IdleAccountFilterTests(TestCase):
    """Checklist item 3: idle accounts are flagged for manual review, never auto-disabled."""

    def setUp(self):
        self.admin = User.objects.create_superuser(username="IDLE-ADMIN", password="Admin-password-2026")
        self.client.force_login(self.admin)
        now = timezone.now()
        self.recent = User.objects.create_user(
            username="IDLE-RECENT", password="Password-2026", role=Role.TUTOR,
        )
        self.recent.last_login = now - timedelta(days=10)
        self.recent.save(update_fields=["last_login"])
        self.idle = User.objects.create_user(
            username="IDLE-STALE", password="Password-2026", role=Role.TUTOR,
        )
        self.idle.last_login = now - timedelta(days=200)
        self.idle.save(update_fields=["last_login"])
        self.never_logged_in = User.objects.create_user(
            username="IDLE-NEVER", password="Password-2026", role=Role.TUTEE,
        )

    def test_idle_filter_shows_only_accounts_past_threshold(self):
        response = self.client.get(f"{reverse('admin:accounts_user_changelist')}?idle=idle")
        self.assertEqual(response.status_code, 200)
        usernames = {user.username for user in response.context["cl"].result_list}
        self.assertEqual(usernames, {"IDLE-STALE"})

    def test_never_logged_in_filter_excludes_users_with_a_login(self):
        response = self.client.get(f"{reverse('admin:accounts_user_changelist')}?idle=never")
        self.assertEqual(response.status_code, 200)
        usernames = {user.username for user in response.context["cl"].result_list}
        self.assertEqual(usernames, {"IDLE-NEVER"})

    def test_idle_accounts_are_not_auto_suspended(self):
        self.idle.refresh_from_db()
        self.never_logged_in.refresh_from_db()
        self.assertEqual(self.idle.account_status, AccountStatus.ACTIVE)
        self.assertEqual(self.never_logged_in.account_status, AccountStatus.ACTIVE)


class RosterImportTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(username="IMPORT-ADMIN", password="Admin-password-2026")
        self.tutor = User.objects.create_user(username="IMPORT-TUTOR", password="Tutor-password-2026", role=Role.TUTOR)

    CSV_HEADER = "student_id,name_zh,name_en,role,education_level,identity_category,program_code,is_enabled"

    def _csv_upload(self, filename, body):
        return SimpleUploadedFile(filename, body.encode("utf-8"), content_type="text/csv")

    def test_admin_can_import_valid_csv_roster(self):
        self.client.force_login(self.admin)
        body = (
            f"{self.CSV_HEADER}\n"
            "S10199001,王小明,Wang Xiao-Ming,TUTOR,MASTER,LOCAL,NA,TRUE\n"
            "S20299002,陳小美,Chen Xiao-Mei,TUTEE,NA,INTERNATIONAL,NTNU,TRUE\n"
        )
        response = self.client.post(
            reverse("accounts:roster_import"), {"file": self._csv_upload("roster.csv", body)}
        )
        self.assertRedirects(response, reverse("accounts:dashboard") + "#roster-import")
        self.assertEqual(RosterEntry.objects.filter(student_id__in=["S10199001", "S20299002"]).count(), 2)
        log = AuditLog.objects.get(event_type="ROSTER_IMPORTED")
        self.assertEqual(log.metadata["created_count"], 2)
        self.assertEqual(set(log.metadata["student_ids"]), {"S10199001", "S20299002"})

    def test_duplicate_student_id_within_file_is_deduplicated(self):
        self.client.force_login(self.admin)
        body = (
            f"{self.CSV_HEADER}\n"
            "S10199003,王小明,Wang Xiao-Ming,TUTOR,MASTER,LOCAL,NA,TRUE\n"
            "S10199003,王小明,Wang Xiao-Ming,TUTOR,MASTER,LOCAL,NA,TRUE\n"
        )
        response = self.client.post(
            reverse("accounts:roster_import"), {"file": self._csv_upload("roster.csv", body)}
        )
        self.assertRedirects(response, reverse("accounts:dashboard") + "#roster-import")
        self.assertEqual(RosterEntry.objects.filter(student_id="S10199003").count(), 1)
        self.assertTrue(AuditLog.objects.filter(event_type="ROSTER_IMPORTED").exists())

    def test_existing_student_id_is_skipped_and_new_ones_still_imported(self):
        RosterEntry.objects.create(
            student_id="S10199004",
            name_zh="已存在",
            role=Role.TUTOR,
            education_level=EducationLevel.MASTER,
            identity_category=IdentityCategory.LOCAL,
        )
        self.client.force_login(self.admin)
        body = (
            f"{self.CSV_HEADER}\n"
            "S10199004,已存在,,TUTOR,MASTER,LOCAL,NA,TRUE\n"
            "S10199005,新學生,,TUTEE,NA,LOCAL,NTNU,TRUE\n"
        )
        response = self.client.post(
            reverse("accounts:roster_import"), {"file": self._csv_upload("roster.csv", body)}
        )
        self.assertRedirects(response, reverse("accounts:dashboard") + "#roster-import")
        self.assertTrue(RosterEntry.objects.filter(student_id="S10199005").exists())
        existing = RosterEntry.objects.get(student_id="S10199004")
        self.assertEqual(existing.name_zh, "已存在")

    def test_invalid_role_rejects_entire_batch(self):
        self.client.force_login(self.admin)
        body = f"{self.CSV_HEADER}\nS10199006,錯誤身分,,ADMIN,NA,LOCAL,NA,TRUE\n"
        response = self.client.post(
            reverse("accounts:roster_import"), {"file": self._csv_upload("roster.csv", body)}
        )
        self.assertRedirects(response, reverse("accounts:dashboard") + "#roster-import")
        self.assertFalse(RosterEntry.objects.filter(student_id="S10199006").exists())

    def test_unsupported_file_extension_is_rejected(self):
        self.client.force_login(self.admin)
        upload = SimpleUploadedFile("roster.txt", b"not a real roster", content_type="text/plain")
        response = self.client.post(reverse("accounts:roster_import"), {"file": upload})
        self.assertRedirects(response, reverse("accounts:dashboard") + "#roster-import")
        self.assertEqual(RosterEntry.objects.count(), 0)

    def test_non_admin_cannot_import_roster(self):
        self.client.force_login(self.tutor)
        body = f"{self.CSV_HEADER}\nS10199007,新學生,,TUTEE,NA,LOCAL,NTNU,TRUE\n"
        response = self.client.post(
            reverse("accounts:roster_import"), {"file": self._csv_upload("roster.csv", body)}
        )
        self.assertRedirects(response, reverse("accounts:dashboard"))
        self.assertFalse(RosterEntry.objects.filter(student_id="S10199007").exists())

    def test_admin_can_download_csv_and_xlsx_templates(self):
        self.client.force_login(self.admin)
        csv_response = self.client.get(reverse("accounts:roster_import_template", args=["csv"]))
        self.assertEqual(csv_response.status_code, 200)
        self.assertEqual(csv_response["Content-Type"], "text/csv; charset=utf-8")

        xlsx_response = self.client.get(reverse("accounts:roster_import_template", args=["xlsx"]))
        self.assertEqual(xlsx_response.status_code, 200)
        self.assertIn("spreadsheetml", xlsx_response["Content-Type"])

    def test_invalid_template_format_is_404(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("accounts:roster_import_template", args=["pdf"]))
        self.assertEqual(response.status_code, 404)


class QuickRosterImportTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(username="QUICK-ADMIN", password="Admin-password-2026")
        self.tutor = User.objects.create_user(username="QUICK-TUTOR", password="Tutor-password-2026", role=Role.TUTOR)
        self.ntnu = PartnerProgram.objects.get(code="NTNU")
        self.maryland = PartnerProgram.objects.get(code="MARYLAND")

    def _csv_upload(self, filename, lines):
        body = "\n".join(lines)
        return SimpleUploadedFile(filename, body.encode("utf-8"), content_type="text/csv")

    def _xlsx_upload(self, filename, rows):
        workbook = openpyxl.Workbook()
        sheet = workbook.active
        for row in rows:
            sheet.append([row])
        buffer = io.BytesIO()
        workbook.save(buffer)
        return SimpleUploadedFile(
            filename,
            buffer.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    def test_quick_import_tutor_category_creates_roster_entries(self):
        self.client.force_login(self.admin)
        upload = self._csv_upload("tutor.csv", ["S30100001", "S30100002"])
        response = self.client.post(
            reverse("accounts:roster_import_quick", args=["TUTOR"]), {"file": upload}
        )
        self.assertRedirects(response, reverse("accounts:dashboard") + "#roster-import")
        entries = RosterEntry.objects.filter(student_id__in=["S30100001", "S30100002"])
        self.assertEqual(entries.count(), 2)
        self.assertTrue(all(entry.role == Role.TUTOR for entry in entries))
        self.assertTrue(all(entry.program_id is None for entry in entries))
        log = AuditLog.objects.get(event_type="ROSTER_IMPORTED")
        self.assertEqual(log.metadata["category"], "TUTOR")
        self.assertEqual(log.metadata["created_count"], 2)

    def test_quick_import_program_category_creates_tutee_entries(self):
        self.client.force_login(self.admin)
        upload = self._csv_upload("ntnu.csv", ["S30200001"])
        response = self.client.post(
            reverse("accounts:roster_import_quick", args=["NTNU"]), {"file": upload}
        )
        self.assertRedirects(response, reverse("accounts:dashboard") + "#roster-import")
        entry = RosterEntry.objects.get(student_id="S30200001")
        self.assertEqual(entry.role, Role.TUTEE)
        self.assertEqual(entry.program_id, self.ntnu.pk)

    def test_quick_import_handles_messy_xlsx_with_title_and_header_rows(self):
        self.client.force_login(self.admin)
        upload = self._xlsx_upload(
            "tutor學號.xlsx",
            ["華語系碩士班", "學  號", "60984011I", "60984011I", "60984022A"],
        )
        response = self.client.post(
            reverse("accounts:roster_import_quick", args=["TUTOR"]), {"file": upload}
        )
        self.assertRedirects(response, reverse("accounts:dashboard") + "#roster-import")
        self.assertEqual(RosterEntry.objects.filter(student_id="60984011I").count(), 1)
        self.assertTrue(RosterEntry.objects.filter(student_id="60984022A").exists())
        # "華語系碩士班" and "學  號" are not valid student-ID-shaped rows, so
        # they should be silently skipped rather than imported as bogus IDs.
        self.assertFalse(RosterEntry.objects.filter(student_id="華語系碩士班").exists())

    def test_quick_import_normalizes_lowercase_student_id(self):
        self.client.force_login(self.admin)
        upload = self._csv_upload("tutor.csv", ["s30300001"])
        self.client.post(reverse("accounts:roster_import_quick", args=["TUTOR"]), {"file": upload})
        self.assertTrue(RosterEntry.objects.filter(student_id="S30300001").exists())

    def test_quick_import_skips_existing_ids_and_imports_new_ones(self):
        RosterEntry.objects.create(student_id="S30400001", role=Role.TUTOR)
        self.client.force_login(self.admin)
        upload = self._csv_upload("tutor.csv", ["S30400001", "S30400002"])
        self.client.post(reverse("accounts:roster_import_quick", args=["TUTOR"]), {"file": upload})
        self.assertTrue(RosterEntry.objects.filter(student_id="S30400002").exists())
        log = AuditLog.objects.get(event_type="ROSTER_IMPORTED")
        self.assertEqual(log.metadata["created_count"], 1)
        self.assertEqual(log.metadata["skipped_existing_count"], 1)

    def test_quick_import_invalid_format_row_is_skipped_with_warning(self):
        self.client.force_login(self.admin)
        upload = self._csv_upload("tutor.csv", ["S30500001", "!!invalid!!"])
        response = self.client.post(
            reverse("accounts:roster_import_quick", args=["TUTOR"]), {"file": upload}, follow=True
        )
        self.assertTrue(RosterEntry.objects.filter(student_id="S30500001").exists())
        warning_messages = [str(message) for message in response.context["messages"]]
        self.assertTrue(any("!!invalid!!" in message for message in warning_messages))

    def test_quick_import_unknown_program_code_is_404(self):
        self.client.force_login(self.admin)
        upload = self._csv_upload("tutor.csv", ["S30600001"])
        response = self.client.post(
            reverse("accounts:roster_import_quick", args=["NOT-A-PROGRAM"]), {"file": upload}
        )
        self.assertEqual(response.status_code, 404)

    def test_non_admin_cannot_use_quick_import(self):
        self.client.force_login(self.tutor)
        upload = self._csv_upload("tutor.csv", ["S30700001"])
        response = self.client.post(
            reverse("accounts:roster_import_quick", args=["TUTOR"]), {"file": upload}
        )
        self.assertRedirects(response, reverse("accounts:dashboard"))
        self.assertFalse(RosterEntry.objects.filter(student_id="S30700001").exists())


class ProfileEditTests(TestCase):
    def setUp(self):
        self.tutor = User.objects.create_user(
            username="EDIT-TUTOR",
            password="Tutor-password-2026",
            role=Role.TUTOR,
            name_zh="王老師",
            name_en="Alex Wang",
            phone="0900000000",
        )
        self.tutor_profile = TutorProfile.objects.create(
            tutor=self.tutor,
            gender="MALE",
            native_language="Mandarin Chinese",
            nationality="Taiwan",
            department="華語文教學系",
            level_listening=4,
            level_speaking=5,
            level_reading=4,
            level_writing=3,
            teaching_notes="重視口語互動",
            available_days=["MON", "WED"],
            available_time_slots=["13:00-15:00"],
        )
        self.tutee = User.objects.create_user(
            username="EDIT-STUDENT",
            password="Student-password-2026",
            role=Role.TUTEE,
            name_zh="學生甲",
            name_en="Student A",
        )
        self.tutee_profile = TuteeProfile.objects.create(
            tutee=self.tutee,
            gender="FEMALE",
            native_language="English",
            nationality="United States",
            department="Languages",
            overall_level="B1",
            learning_duration="1_TO_2_YEARS",
            target_skills=["LISTENING", "SPEAKING"],
            skills_to_improve="希望練習日常會話",
            preferred_days=["TUE"],
            preferred_time_slots=["15:00-17:00"],
        )

    def test_tutor_can_update_profile_fields(self):
        self.client.force_login(self.tutor)
        response = self.client.post(
            reverse("accounts:update_profile"),
            {
                "phone": "0911222333",
                "gender": "MALE",
                "native_language": "Mandarin Chinese",
                "nationality": "Taiwan",
                "department": "應用華語文學系",
                "level_listening": 5,
                "level_speaking": 5,
                "level_reading": 5,
                "level_writing": 5,
                "teaching_notes": "更新後的教學簡介",
                "available_days": ["MON", "TUE", "THU"],
                "available_time_slots": ["09:00-11:00"],
            },
        )
        self.assertRedirects(response, reverse("accounts:profile") + "#edit-profile")
        self.tutor.refresh_from_db()
        self.tutor_profile.refresh_from_db()
        self.assertEqual(self.tutor.phone, "0911222333")
        self.assertEqual(self.tutor_profile.department, "應用華語文學系")
        self.assertEqual(self.tutor_profile.level_listening, 5)
        self.assertEqual(self.tutor_profile.teaching_notes, "更新後的教學簡介")
        self.assertEqual(sorted(self.tutor_profile.available_days), ["MON", "THU", "TUE"])
        log = AuditLog.objects.get(event_type="PROFILE_UPDATED")
        self.assertIn("department", log.metadata["fields"])

    def test_tutee_can_update_profile_fields(self):
        self.client.force_login(self.tutee)
        response = self.client.post(
            reverse("accounts:update_profile"),
            {
                "phone": "",
                "gender": "FEMALE",
                "native_language": "English",
                "nationality": "United States",
                "department": "Languages",
                "overall_level": "B2",
                "learning_duration": "GT_2_YEARS",
                "level_listening": 4,
                "level_speaking": 4,
                "level_reading": 4,
                "level_writing": 4,
                "target_skills": ["READING"],
                "skills_to_improve": "希望加強寫作",
                "preferred_days": ["WED"],
                "preferred_time_slots": ["11:00-13:00"],
            },
        )
        self.assertRedirects(response, reverse("accounts:profile") + "#edit-profile")
        self.tutee_profile.refresh_from_db()
        self.assertEqual(self.tutee_profile.overall_level, "B2")
        self.assertEqual(self.tutee_profile.skills_to_improve, "希望加強寫作")
        self.assertEqual(self.tutee_profile.preferred_days, ["WED"])

    def test_name_and_student_id_cannot_be_changed_via_profile_form(self):
        self.client.force_login(self.tutor)
        self.client.post(
            reverse("accounts:update_profile"),
            {
                "name_zh": "偽造姓名",
                "username": "FAKE-ID",
                "phone": "0900000000",
                "gender": "MALE",
                "native_language": "Mandarin Chinese",
                "nationality": "Taiwan",
                "department": "華語文教學系",
                "level_listening": 4,
                "level_speaking": 5,
                "level_reading": 4,
                "level_writing": 3,
                "teaching_notes": "重視口語互動",
                "available_days": ["MON", "WED"],
                "available_time_slots": ["13:00-15:00"],
            },
        )
        self.tutor.refresh_from_db()
        self.assertEqual(self.tutor.name_zh, "王老師")
        self.assertEqual(self.tutor.username, "EDIT-TUTOR")

    def test_missing_required_field_rejects_update(self):
        self.client.force_login(self.tutor)
        response = self.client.post(
            reverse("accounts:update_profile"),
            {
                "phone": "0900000000",
                "native_language": "Mandarin Chinese",
                "nationality": "Taiwan",
                "department": "華語文教學系",
                "level_listening": 4,
                "level_speaking": 5,
                "level_reading": 4,
                "level_writing": 3,
                "teaching_notes": "重視口語互動",
                "available_days": ["MON", "WED"],
                "available_time_slots": ["13:00-15:00"],
            },
        )
        self.assertRedirects(response, reverse("accounts:profile") + "#edit-profile")
        self.tutor_profile.refresh_from_db()
        self.assertEqual(self.tutor_profile.department, "華語文教學系")
        self.assertFalse(AuditLog.objects.filter(event_type="PROFILE_UPDATED").exists())

    def test_admin_cannot_access_update_profile(self):
        admin = User.objects.create_superuser(username="EDIT-ADMIN", password="Admin-password-2026")
        self.client.force_login(admin)
        response = self.client.post(reverse("accounts:update_profile"), {})
        self.assertEqual(response.status_code, 404)


class AuditLogResilienceTests(TestCase):
    def test_record_returns_saved_entry_on_success(self):
        log = AuditLog.record(event_type="TEST_EVENT", description="test")
        self.assertIsNotNone(log)
        self.assertTrue(AuditLog.objects.filter(pk=log.pk).exists())

    def test_record_swallows_failure_without_poisoning_outer_transaction(self):
        with transaction.atomic():
            with patch.object(AuditLog.objects, "create", side_effect=Exception("boom")):
                result = AuditLog.record(event_type="TEST_EVENT", description="boom test")
            self.assertIsNone(result)
            # A failed AuditLog.record() call must not break the caller's own
            # @transaction.atomic block; further ORM operations here must still work.
            User.objects.create_user(username="AUDIT-RESILIENCE-TEST", password="Password-2026")
        self.assertTrue(User.objects.filter(username="AUDIT-RESILIENCE-TEST").exists())


class ProductionErrorPageTests(TestCase):
    """Checklist item 45: error pages must not leak stack traces/paths when DEBUG=False."""

    @override_settings(DEBUG=False, ALLOWED_HOSTS=["testserver"])
    def test_unhandled_exception_shows_generic_page_not_debug_traceback(self):
        roster = RosterEntry.objects.create(
            student_id="ERRPAGE-TUTOR", name_zh="錯誤頁測試", role=Role.TUTOR,
            education_level=EducationLevel.MASTER, identity_category=IdentityCategory.LOCAL,
        )
        user = User.objects.create_user(username="ERRPAGE-TUTOR", password="Password-2026", roster_entry=roster)
        client = Client(raise_request_exception=False)
        client.force_login(user)
        with patch("accounts.views.render", side_effect=Exception("Simulated failure for error-page test")):
            response = client.get(reverse("accounts:handbook"))
        self.assertEqual(response.status_code, 500)
        body = response.content.decode(errors="ignore")
        self.assertNotIn("Traceback", body)
        self.assertNotIn(str(settings.BASE_DIR), body)
        self.assertNotIn("Simulated failure", body)
