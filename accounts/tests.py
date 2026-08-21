from datetime import timedelta
import io
import os
from unittest.mock import patch

import openpyxl
from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import transaction
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from tutoring.models import QualificationDocument, TuteeProfile, TutorProfile

from .forms import client_ip

from .models import (
    AccountStatus,
    AuditLog,
    EducationLevel,
    IdentityCategory,
    PartnerProgram,
    RegistrationDraft,
    Role,
    RosterEntry,
    SecurityQuestionAnswer,
    User,
)


def minimal_pdf_bytes():
    """A genuinely parseable single-page PDF (batch 6 item 1 added real content
    validation via pypdf, so a plain b"%PDF-1.4..." byte string with no actual PDF
    structure is no longer accepted as a valid upload in tests)."""
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


class CsrfFailureViewTests(TestCase):
    def test_invalid_csrf_token_uses_friendly_failure_page(self):
        client = Client(enforce_csrf_checks=True)
        response = client.post(reverse("accounts:login"), {"username": "nobody"})

        self.assertEqual(response.status_code, 403)
        self.assertTemplateUsed(response, "accounts/csrf_failure.html")
        self.assertContains(response, "頁面已過期", status_code=403)
        self.assertContains(response, "您的操作尚未送出", status_code=403)


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
            "email": "test.student@example.com",
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
                "registration_identity": "LOCAL",
                "password1": self.registration_data["password1"],
                "password2": self.registration_data["password2"],
            },
        )
        self.assertRedirects(response, reverse("accounts:register_confirm"))
        response = self.client.post(reverse("accounts:register_confirm"))
        self.assertRedirects(response, reverse("accounts:register_tutor"))
        return self.client.post(reverse("accounts:register_tutor"), data or self.registration_data)

    def test_registration_requires_roster_entry(self):
        response = self.client.post(reverse("accounts:register"), {"student_id": "UNKNOWN"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "找不到註冊學號，請聯絡系辦")
        self.assertFalse(User.objects.filter(username="UNKNOWN").exists())

    def test_registration_page_shows_fixed_identity_selector_beside_student_id(self):
        response = self.client.get(reverse("accounts:register"))
        self.assertContains(response, 'class="registration-fields-grid"')
        self.assertContains(response, "身分別 / Identity")
        self.assertContains(response, 'value="LOCAL"')
        self.assertContains(response, 'value="OVERSEAS"')
        self.assertContains(response, 'value="HONG_KONG_MACAO"')
        self.assertContains(response, 'value="MAINLAND"')
        self.assertContains(response, 'value="INTERNATIONAL"')
        self.assertContains(response, 'value="MARYLAND"')

    def test_registration_rejects_identity_that_does_not_match_roster(self):
        response = self.client.post(
            reverse("accounts:register"),
            {
                "student_id": "TEST1001",
                "registration_identity": "MARYLAND",
                "password1": self.registration_data["password1"],
                "password2": self.registration_data["password2"],
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "學號與身分別不符")
        self.assertFalse(RegistrationDraft.objects.filter(roster_entry=self.roster).exists())

    def test_registration_claims_roster_and_hashes_answers(self):
        response = self.register_tutor()
        self.assertRedirects(response, reverse("accounts:dashboard"))
        user = User.objects.get(username="TEST1001")
        self.roster.refresh_from_db()
        self.assertEqual(user.role, Role.TUTOR)
        self.assertTrue(user.check_password(self.registration_data["password1"]))
        self.assertEqual(user.email, "test.student@example.com")
        self.assertIsNotNone(self.roster.claimed_at)
        self.assertFalse(RegistrationDraft.objects.filter(roster_entry=self.roster).exists())
        self.assertTrue(TutorProfile.objects.filter(tutor=user).exists())
        self.assertNotIn("Alpha answer", user.security_questions.answer_1_hash)
        self.assertTrue(user.security_questions.check_answers(["alpha ANSWER", "Beta answer", "Gamma answer"]))

    def test_registration_cannot_overwrite_identity_verified_by_roster(self):
        data = self.registration_data | {"identity_category": IdentityCategory.INTERNATIONAL}
        response = self.register_tutor(data)
        self.assertRedirects(response, reverse("accounts:dashboard"))
        self.roster.refresh_from_db()
        self.assertEqual(self.roster.identity_category, IdentityCategory.LOCAL)

    def test_registration_rejects_invalid_email(self):
        data = self.registration_data | {"email": "not-an-email"}
        response = self.register_tutor(data)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username="TEST1001").exists())

    def test_tutor_registration_requires_english_name(self):
        data = self.registration_data | {"name_en": ""}
        response = self.register_tutor(data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "此欄位為必填欄位")
        self.assertFalse(User.objects.filter(username="TEST1001").exists())

    def test_retired_security_question_rejected_at_registration(self):
        data = self.registration_data | {"question_1": "Q4"}
        self.client.post(
            reverse("accounts:register"),
            {
                "student_id": "TEST1001",
                "registration_identity": "LOCAL",
                "password1": data["password1"],
                "password2": data["password2"],
            },
        )
        self.client.post(reverse("accounts:register_confirm"))
        response = self.client.post(reverse("accounts:register_tutor"), data)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username="TEST1001").exists())

    def test_security_questions_must_be_distinct(self):
        data = self.registration_data | {"question_3": "Q1"}
        self.client.post(
            reverse("accounts:register"),
            {
                "student_id": "TEST1001",
                "registration_identity": "LOCAL",
                "password1": data["password1"],
                "password2": data["password2"],
            },
        )
        self.client.post(reverse("accounts:register_confirm"))
        response = self.client.post(reverse("accounts:register_tutor"), data)
        self.assertContains(response, "安全問題不可重複")
        self.assertFalse(User.objects.filter(username="TEST1001").exists())

    def test_security_question_model_rejects_duplicate_questions(self):
        user = User.objects.create_user(username="SECURITY-CONSTRAINT", password="Test-password-2026")
        questions = SecurityQuestionAnswer(
            user=user,
            question_1="Q1",
            question_2="Q1",
            question_3="Q2",
            answer_1_hash="a",
            answer_2_hash="b",
            answer_3_hash="c",
        )
        with self.assertRaises(ValidationError):
            questions.full_clean()

    def test_account_does_not_exist_before_profile_setup(self):
        response = self.client.post(
            reverse("accounts:register"),
            {
                "student_id": "TEST1001",
                "registration_identity": "LOCAL",
                "password1": self.registration_data["password1"],
                "password2": self.registration_data["password2"],
            },
        )
        self.assertRedirects(response, reverse("accounts:register_confirm"))
        self.assertFalse(User.objects.filter(username="TEST1001").exists())
        self.assertTrue(RegistrationDraft.objects.filter(roster_entry=self.roster).exists())
        self.roster.refresh_from_db()
        self.assertIsNone(self.roster.claimed_at)

    def start_registration(self):
        return self.client.post(
            reverse("accounts:register"),
            {
                "student_id": "TEST1001",
                "registration_identity": "LOCAL",
                "password1": self.registration_data["password1"],
                "password2": self.registration_data["password2"],
            },
        )

    def test_stage_two_url_cannot_be_opened_directly_without_confirming(self):
        """Item 7 acceptance: visiting the stage-2 URL without having confirmed the
        student ID must not open the profile form."""
        self.start_registration()
        response = self.client.get(reverse("accounts:register_tutor"))
        self.assertRedirects(response, reverse("accounts:register_confirm"))
        self.assertFalse(User.objects.filter(username="TEST1001").exists())

    def test_confirm_page_shows_student_id_and_does_not_create_account(self):
        self.start_registration()
        response = self.client.get(reverse("accounts:register_confirm"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "TEST1001")
        self.assertFalse(User.objects.filter(username="TEST1001").exists())

    def test_refreshing_confirm_page_repeatedly_does_not_create_account(self):
        self.start_registration()
        for _ in range(3):
            response = self.client.get(reverse("accounts:register_confirm"))
            self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username="TEST1001").exists())

    def test_going_back_to_stage_one_discards_the_draft(self):
        """Item 7 acceptance: back/refresh must not accidentally build up an account. Landing
        back on the lookup form clears the in-progress draft and confirmation, so the stage-2
        URL is unreachable until stage 1 is redone."""
        self.start_registration()
        self.client.post(reverse("accounts:register_confirm"))
        self.client.get(reverse("accounts:register"))
        self.assertFalse(RegistrationDraft.objects.filter(roster_entry=self.roster).exists())
        response = self.client.get(reverse("accounts:register_tutor"))
        self.assertRedirects(response, reverse("accounts:register"))

    def test_confirming_does_not_extend_the_draft_expiry(self):
        """Item 7 acceptance: confirming keeps the original draft's time limit — it isn't a
        fresh 30-minute window."""
        self.start_registration()
        draft = RegistrationDraft.objects.get(roster_entry=self.roster)
        original_expiry = draft.expires_at
        self.client.post(reverse("accounts:register_confirm"))
        draft.refresh_from_db()
        self.assertEqual(draft.expires_at, original_expiry)

    def test_register_confirm_without_a_pending_draft_redirects_to_stage_one(self):
        response = self.client.get(reverse("accounts:register_confirm"))
        self.assertRedirects(response, reverse("accounts:register"))

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
                "registration_identity": "MARYLAND",
                "password1": "Another-secure-password-2026",
                "password2": "Another-secure-password-2026",
            },
        )
        self.assertRedirects(response, reverse("accounts:register_confirm"))
        response = self.client.post(reverse("accounts:register_confirm"))
        self.assertRedirects(response, reverse("accounts:register_tutee"))
        data = {
            "name_zh": "",
            "name_en": "Tutee Student",
            "identity_category": "INTERNATIONAL",
            "phone": "0900000000",
            "email": "tutee.student@example.com",
            "gender": "FEMALE",
            "native_language": "English",
            "nationality": "United States",
            "department": "Languages",
            "overall_level": "HSK9",
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
        form_response = self.client.get(reverse("accounts:register_tutee"))
        self.assertNotContains(form_response, "所屬計畫 / Program")
        self.assertNotContains(form_response, "University of Maryland")

        missing_english_response = self.client.post(
            reverse("accounts:register_tutee"), data | {"name_en": ""}
        )
        self.assertEqual(missing_english_response.status_code, 200)
        self.assertContains(missing_english_response, "此欄位為必填欄位")
        self.assertFalse(User.objects.filter(username="TUTEE1001").exists())

        response = self.client.post(reverse("accounts:register_tutee"), data)
        self.assertRedirects(response, reverse("accounts:dashboard"))
        user = User.objects.get(username="TUTEE1001")
        self.assertEqual(user.role, Role.TUTEE)
        self.assertEqual(user.name_zh, "")
        self.assertEqual(user.name_en, "Tutee Student")
        profile = TuteeProfile.objects.get(tutee=user)
        self.assertEqual(profile.overall_level, "HSK9")
        self.assertEqual(profile.target_skills, ["LISTENING", "SPEAKING"])


class AccountRecoveryTests(TestCase):
    def setUp(self):
        cache.clear()
        RegistrationTests.setUp(self)
        self.client.post(
            reverse("accounts:register"),
            {
                "student_id": "TEST1001",
                "registration_identity": "LOCAL",
                "password1": self.registration_data["password1"],
                "password2": self.registration_data["password2"],
            },
        )
        self.client.post(reverse("accounts:register_confirm"))
        self.client.post(reverse("accounts:register_tutor"), self.registration_data)
        self.client.post(reverse("accounts:logout"))

    def lookup_then_verify(self, verify_data):
        """The recovery flow is two separate POSTs to the same view: a lookup step (just
        student_id) that returns the account's own 3 questions, then a verify step
        (student_id + action=verify + the 3 answers) that actually checks them. The
        question text itself is never submitted by the client — the server already knows
        which questions belong to the user from SecurityQuestionAnswer."""
        lookup_response = self.client.post(reverse("accounts:recover"), {"student_id": "TEST1001"})
        self.assertEqual(lookup_response.status_code, 200)
        return self.client.post(reverse("accounts:recover"), {**verify_data, "action": "verify"})

    def test_valid_answers_allow_password_reset(self):
        lookup_response = self.client.post(
            reverse("accounts:recover"), {"student_id": "TEST1001", "action": "lookup"}
        )
        self.assertEqual(lookup_response.status_code, 200)
        self.assertContains(lookup_response, "我第一所就讀的小學名稱？")
        self.assertContains(lookup_response, "我最喜歡的食物？")
        self.assertContains(lookup_response, "我最喜歡的一本書？")
        self.assertNotContains(lookup_response, 'name="question_1"')
        verify_data = {
            "student_id": "TEST1001",
            "answer_1": "Alpha answer",
            "answer_2": "Beta answer",
            "answer_3": "Gamma answer",
            "action": "verify",
        }
        response = self.lookup_then_verify(verify_data)
        self.assertRedirects(response, reverse("accounts:set_recovered_password"))
        response = self.client.post(
            reverse("accounts:set_recovered_password"),
            {"new_password1": "A-brand-new-password-2026", "new_password2": "A-brand-new-password-2026"},
        )
        self.assertRedirects(response, reverse("accounts:login"))
        user = User.objects.get(username="TEST1001")
        self.assertTrue(user.check_password("A-brand-new-password-2026"))

    def test_existing_retired_question_still_works_for_recovery(self):
        user = User.objects.get(username="TEST1001")
        questions = user.security_questions
        questions.question_1 = "Q4"
        questions.set_answers(["Homeroom teacher answer", "Beta answer", "Gamma answer"])
        questions.save()
        lookup_response = self.client.post(
            reverse("accounts:recover"), {"student_id": "TEST1001", "action": "lookup"}
        )
        self.assertContains(lookup_response, "我第一位導師的姓氏？")
        verify_data = {
            "student_id": "TEST1001",
            "answer_1": "Homeroom teacher answer",
            "answer_2": "Beta answer",
            "answer_3": "Gamma answer",
            "action": "verify",
        }
        response = self.lookup_then_verify(verify_data)
        self.assertRedirects(response, reverse("accounts:set_recovered_password"))

    def test_wrong_answers_do_not_reveal_account(self):
        verify_data = {
            "student_id": "TEST1001",
            "answer_1": "wrong",
            "answer_2": "wrong",
            "answer_3": "wrong",
        }
        response = self.lookup_then_verify(verify_data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "資料無法驗證")

    def test_invalid_student_id_shows_a_question_form_like_a_real_one(self):
        """Item 4.4: a nonexistent student ID must get the same shape of response
        (status code, an answer form with the usual 3 fields) as a real one, not an
        immediate error that reveals the account doesn't exist."""
        response = self.client.post(reverse("accounts:recover"), {"student_id": "NOSUCHID999"})
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.context["answer_form"])
        for field_name in ("answer_1", "answer_2", "answer_3"):
            self.assertIn(field_name, response.context["answer_form"].fields)

    def test_invalid_student_id_verification_fails_generically_without_creating_a_session(self):
        self.client.post(reverse("accounts:recover"), {"student_id": "NOSUCHID999"})
        response = self.client.post(
            reverse("accounts:recover"),
            {"student_id": "NOSUCHID999", "action": "verify", "answer_1": "a", "answer_2": "b", "answer_3": "c"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "資料無法驗證")
        self.assertNotIn("recovery_user_id", self.client.session)

    def test_invalid_id_and_wrong_answer_responses_are_structurally_identical(self):
        """Both failure paths must look identical to an outside observer — same status
        code and the same generic message — so the response can't distinguish a real
        account with a wrong answer from a nonexistent one."""
        valid_wrong = self.lookup_then_verify(
            {"student_id": "TEST1001", "answer_1": "wrong", "answer_2": "wrong", "answer_3": "wrong"}
        )
        self.client.post(reverse("accounts:recover"), {"student_id": "NOSUCHID999"})
        invalid_response = self.client.post(
            reverse("accounts:recover"),
            {"student_id": "NOSUCHID999", "action": "verify", "answer_1": "wrong", "answer_2": "wrong", "answer_3": "wrong"},
        )
        self.assertEqual(valid_wrong.status_code, invalid_response.status_code)
        self.assertContains(valid_wrong, "資料無法驗證")
        self.assertContains(invalid_response, "資料無法驗證")

    def test_invalid_student_id_shows_stable_decoy_questions_across_lookups(self):
        """Decoy questions must be deterministic per student ID, not re-randomized on
        every request — instability itself would be a distinguishing signal."""
        first = self.client.post(reverse("accounts:recover"), {"student_id": "NOSUCHID999"})
        second = self.client.post(reverse("accounts:recover"), {"student_id": "NOSUCHID999"})
        for field_name in ("answer_1", "answer_2", "answer_3"):
            self.assertEqual(
                first.context["answer_form"].fields[field_name].label,
                second.context["answer_form"].fields[field_name].label,
            )

    def test_student_id_lookup_is_case_insensitive(self):
        lookup_response = self.client.post(reverse("accounts:recover"), {"student_id": "test1001"})
        self.assertEqual(lookup_response.status_code, 200)
        response = self.client.post(
            reverse("accounts:recover"),
            {
                "student_id": "test1001", "action": "verify",
                "answer_1": "Alpha answer", "answer_2": "Beta answer", "answer_3": "Gamma answer",
            },
        )
        self.assertRedirects(response, reverse("accounts:set_recovered_password"))

    def test_recovery_throttles_valid_and_invalid_ids_alike_after_five_attempts(self):
        """Item 4.4/batch 5: both the lookup and verify steps share one throttle, and it
        must apply the same way regardless of whether the student ID is real."""
        for _ in range(5):
            self.client.post(reverse("accounts:recover"), {"student_id": "TEST1001"})
        response = self.client.post(reverse("accounts:recover"), {"student_id": "TEST1001"})
        self.assertContains(response, "嘗試次數過多")

        for _ in range(5):
            self.client.post(reverse("accounts:recover"), {"student_id": "NOSUCHID999"})
        response = self.client.post(reverse("accounts:recover"), {"student_id": "NOSUCHID999"})
        self.assertContains(response, "嘗試次數過多")


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

    def test_login_student_id_is_case_insensitive(self):
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "login-lockout-test", "password": "Correct-password-2026"},
        )
        self.assertRedirects(response, reverse("accounts:dashboard"))
        self.assertEqual(response.wsgi_request.user, self.user)

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


class AdminLoginThrottleTests(TestCase):
    """Batch 4 item 6 (docs/VULNERABILITY_SCAN_IMPROVEMENTS.md): Django Admin's own login
    view has no rate limiting by default, so /system-admin/ needs the same standard of
    protection as the main site login."""

    def setUp(self):
        cache.clear()
        self.password = "Admin-password-2026"
        self.admin = User.objects.create_superuser(username="ADMIN-THROTTLE-TEST", password=self.password)

    def test_admin_login_locks_after_five_failed_attempts(self):
        for _ in range(5):
            response = self.client.post(
                reverse("admin:login"), {"username": "ADMIN-THROTTLE-TEST", "password": "wrong-password"}
            )
            self.assertEqual(response.status_code, 200)
        response = self.client.post(
            reverse("admin:login"), {"username": "ADMIN-THROTTLE-TEST", "password": self.password}
        )
        self.assertContains(response, "嘗試次數過多")
        self.assertFalse(response.wsgi_request.user.is_authenticated)

    def test_admin_login_throttle_is_independent_of_main_site_login_throttle(self):
        """Failing the main site's login form 5 times must not lock out the admin login
        for the same account, since the two forms use separate cache key prefixes."""
        for _ in range(5):
            self.client.post(
                reverse("accounts:login"), {"username": "ADMIN-THROTTLE-TEST", "password": "wrong-password"}
            )
        response = self.client.post(
            reverse("admin:login"), {"username": "ADMIN-THROTTLE-TEST", "password": self.password}
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(self.client.session.get("_auth_user_id"))

    def test_successful_admin_login_clears_throttle_counter(self):
        for _ in range(3):
            self.client.post(
                reverse("admin:login"), {"username": "ADMIN-THROTTLE-TEST", "password": "wrong-password"}
            )
        response = self.client.post(
            reverse("admin:login"), {"username": "ADMIN-THROTTLE-TEST", "password": self.password}
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(self.client.session.get("_auth_user_id"))


class ClientIpTrustedProxyTests(TestCase):
    """Batch 5 (docs/VULNERABILITY_SCAN_IMPROVEMENTS.md): client_ip() must not trust a
    client-supplied X-Forwarded-For unless the deployment explicitly says how many
    reverse-proxy hops are in front of it."""

    def make_request(self, remote_addr="203.0.113.5", forwarded_for=None):
        request = RequestFactory().get("/", REMOTE_ADDR=remote_addr)
        if forwarded_for is not None:
            request.META["HTTP_X_FORWARDED_FOR"] = forwarded_for
        return request

    @override_settings(TRUSTED_PROXY_COUNT=0)
    def test_default_ignores_x_forwarded_for_even_if_present(self):
        request = self.make_request(forwarded_for="198.51.100.1")
        self.assertEqual(client_ip(request), "203.0.113.5")

    @override_settings(TRUSTED_PROXY_COUNT=1)
    def test_trusts_the_single_hop_when_configured(self):
        request = self.make_request(forwarded_for="198.51.100.1")
        self.assertEqual(client_ip(request), "198.51.100.1")

    @override_settings(TRUSTED_PROXY_COUNT=1)
    def test_falls_back_to_remote_addr_when_header_missing(self):
        request = self.make_request(forwarded_for=None)
        self.assertEqual(client_ip(request), "203.0.113.5")

    @override_settings(TRUSTED_PROXY_COUNT=1)
    def test_takes_the_hop_the_trusted_proxy_would_have_set_not_a_spoofed_earlier_one(self):
        # deploy/nginx/proxy_params_mpts.conf overwrites X-Forwarded-For outright, so in
        # the real deployment there's only ever one value here — but if some other value
        # is already present (e.g. Django reachable directly, bypassing nginx), taking
        # the last position is what a single real trusted hop would produce.
        request = self.make_request(forwarded_for="1.2.3.4, 203.0.113.5")
        self.assertEqual(client_ip(request), "203.0.113.5")


class CrossIpThrottleTests(TestCase):
    """Batch 5: alongside the existing IP+identifier throttle, a wider identifier-only
    counter should catch a slow attack spread across many source IPs, without making
    different accounts behind the same shared IP/NAT lock each other out."""

    def setUp(self):
        cache.clear()
        self.password = "Correct-password-2026"
        self.user = User.objects.create_user(username="CROSS-IP-TEST", password=self.password, role=Role.TUTOR)

    def test_login_failures_distributed_across_many_ips_eventually_lock_the_account(self):
        for index in range(20):
            self.client.post(
                reverse("accounts:login"),
                {"username": "CROSS-IP-TEST", "password": "wrong-password"},
                REMOTE_ADDR=f"10.0.0.{index + 1}",
            )
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "CROSS-IP-TEST", "password": self.password},
            REMOTE_ADDR="10.0.0.255",
        )
        self.assertContains(response, "嘗試次數過多")
        self.assertFalse(response.wsgi_request.user.is_authenticated)

    def test_different_accounts_behind_the_same_ip_do_not_lock_each_other(self):
        User.objects.create_user(username="CROSS-IP-OTHER", password=self.password, role=Role.TUTOR)
        for _ in range(5):
            self.client.post(
                reverse("accounts:login"),
                {"username": "CROSS-IP-TEST", "password": "wrong-password"},
                REMOTE_ADDR="10.1.1.1",
            )
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "CROSS-IP-OTHER", "password": self.password},
            REMOTE_ADDR="10.1.1.1",
        )
        self.assertRedirects(response, reverse("accounts:dashboard"))

    def test_recovery_failures_distributed_across_many_ips_eventually_lock_the_account(self):
        # No SecurityQuestionAnswer set up for self.user on purpose: the throttle check
        # happens before the view ever looks at whether the account has real security
        # questions (accounts/views.py::recover_account falls back to
        # _FakeSecurityQuestions either way), so this exercises the throttle in
        # isolation from that lookup.
        for index in range(20):
            self.client.post(
                reverse("accounts:recover"),
                {"student_id": "CROSS-IP-TEST"},
                REMOTE_ADDR=f"10.2.2.{index + 1}",
            )
        response = self.client.post(
            reverse("accounts:recover"),
            {"student_id": "CROSS-IP-TEST"},
            REMOTE_ADDR="10.2.2.255",
        )
        self.assertContains(response, "嘗試次數過多")

    def test_admin_login_failures_distributed_across_many_ips_eventually_lock_the_account(self):
        User.objects.create_superuser(username="CROSS-IP-ADMIN", password=self.password)
        for index in range(20):
            self.client.post(
                reverse("admin:login"),
                {"username": "CROSS-IP-ADMIN", "password": "wrong-password"},
                REMOTE_ADDR=f"10.5.5.{index + 1}",
            )
        response = self.client.post(
            reverse("admin:login"),
            {"username": "CROSS-IP-ADMIN", "password": self.password},
            REMOTE_ADDR="10.5.5.255",
        )
        self.assertContains(response, "嘗試次數過多")
        self.assertFalse(response.wsgi_request.user.is_authenticated)


class SharedCacheBackendTests(TestCase):
    """Batch 5: the throttle cache must be backed by something shared across processes
    (PostgreSQL here) rather than Django's default per-process LocMemCache, or different
    Gunicorn workers would each keep their own attempt counts and effectively multiply the
    real limit by the worker count."""

    def test_default_cache_uses_the_shared_database_backend(self):
        self.assertEqual(
            settings.CACHES["default"]["BACKEND"],
            "django.core.cache.backends.db.DatabaseCache",
        )


class RosterLookupThrottleTests(TestCase):
    """Batch 5 item "名冊查詢限制": registration's roster lookup must not let one source
    enumerate an unlimited number of student IDs."""

    def setUp(self):
        cache.clear()

    def test_many_lookups_from_one_ip_get_throttled(self):
        for index in range(10):
            self.client.post(
                reverse("accounts:register"),
                {"student_id": f"NOSUCH-{index}", "password1": "irrelevant", "password2": "irrelevant"},
                REMOTE_ADDR="10.3.3.3",
            )
        response = self.client.post(
            reverse("accounts:register"),
            {"student_id": "NOSUCH-999", "password1": "irrelevant", "password2": "irrelevant"},
            REMOTE_ADDR="10.3.3.3",
        )
        self.assertContains(response, "嘗試次數過多")

    def test_lookups_from_different_ips_are_not_throttled_together(self):
        for index in range(10):
            self.client.post(
                reverse("accounts:register"),
                {"student_id": f"NOSUCH-{index}", "password1": "irrelevant", "password2": "irrelevant"},
                REMOTE_ADDR=f"10.4.4.{index + 1}",
            )
        response = self.client.post(
            reverse("accounts:register"),
            {"student_id": "NOSUCH-999", "password1": "irrelevant", "password2": "irrelevant"},
            REMOTE_ADDR="10.4.4.255",
        )
        self.assertNotContains(response, "嘗試次數過多")


class PrivateNoStoreMiddlewareTests(TestCase):
    """Authenticated and public identity flows must never be browser-cacheable."""

    def setUp(self):
        self.tutor = User.objects.create_user(username="NOSTORE-TUTOR", password="Test-password-2026", role=Role.TUTOR)

    def test_authenticated_page_gets_private_no_store(self):
        self.client.force_login(self.tutor)
        response = self.client.get(reverse("accounts:dashboard"))
        self.assertEqual(response["Cache-Control"], "private, no-store")

    def test_admin_page_gets_private_no_store(self):
        admin = User.objects.create_superuser(username="NOSTORE-ADMIN", password="Admin-password-2026")
        self.client.force_login(admin)
        response = self.client.get(reverse("admin:index"))
        self.assertEqual(response["Cache-Control"], "private, no-store")

    def test_public_identity_pages_get_private_no_store(self):
        view_names = (
            "accounts:login",
            "accounts:register",
            "accounts:register_confirm",
            "accounts:register_tutor",
            "accounts:register_tutee",
            "accounts:recover",
            "accounts:set_recovered_password",
        )
        for view_name in view_names:
            with self.subTest(view_name=view_name):
                response = self.client.get(reverse(view_name))
                self.assertEqual(response["Cache-Control"], "private, no-store")
                self.assertEqual(response["Pragma"], "no-cache")
                self.assertEqual(response["Expires"], "0")

    def test_unrelated_public_page_is_not_forced_no_store(self):
        response = self.client.get("/this-page-does-not-exist/")
        self.assertNotEqual(response.get("Cache-Control"), "private, no-store")


class ContentSecurityPolicyMiddlewareTests(TestCase):
    """The enforcing CSP is present on every response without unsafe fallbacks."""

    def test_login_page_carries_enforcing_csp_header(self):
        response = self.client.get(reverse("accounts:login"))
        header = response["Content-Security-Policy"]
        self.assertIn("default-src 'self'", header)
        self.assertIn("script-src-attr 'none'", header)
        self.assertIn("frame-ancestors 'none'", header)
        self.assertNotIn("unsafe-inline", header)
        self.assertNotIn("Content-Security-Policy-Report-Only", response.headers)
        self.assertIn("camera=()", response["Permissions-Policy"])
        self.assertIn("microphone=()", response["Permissions-Policy"])

    def test_authenticated_dashboard_also_carries_the_policy(self):
        tutor = User.objects.create_user(username="CSP-TUTOR", password="Test-password-2026", role=Role.TUTOR)
        self.client.force_login(tutor)
        response = self.client.get(reverse("accounts:dashboard"))
        self.assertIn("default-src 'self'", response["Content-Security-Policy"])


class QualificationTests(TestCase):
    def setUp(self):
        self.tutor = User.objects.create_user(username="TUTOR1", password="Tutor-password-2026", role=Role.TUTOR)
        self.admin = User.objects.create_superuser(username="ADMIN1", password="Admin-password-2026")

    def test_tutor_can_upload_valid_document(self):
        self.client.force_login(self.tutor)
        upload = SimpleUploadedFile("proof.pdf", minimal_pdf_bytes(), content_type="application/pdf")
        response = self.client.post(reverse("accounts:upload_qualification"), {"file": upload})
        self.assertRedirects(response, reverse("accounts:dashboard") + "#qualification")
        document = QualificationDocument.objects.get(tutor=self.tutor)
        self.assertEqual(document.original_filename, "proof.pdf")

    def test_oversized_upload_returns_to_qualification_tab_with_error(self):
        """The upload form lives on the dashboard's #qualification tab; a rejected
        upload (e.g. over the 1 MB limit) must redirect back to that same tab rather
        than dropping the user onto #overview, which used to happen because the
        redirect target had no fragment at all."""
        self.client.force_login(self.tutor)
        oversized = SimpleUploadedFile(
            "too_big.pdf", minimal_pdf_bytes() + b"0" * 1_000_001, content_type="application/pdf"
        )
        response = self.client.post(reverse("accounts:upload_qualification"), {"file": oversized})
        self.assertRedirects(response, reverse("accounts:dashboard") + "#qualification")
        self.assertFalse(QualificationDocument.objects.filter(tutor=self.tutor).exists())

    def test_tutee_cannot_upload_qualification(self):
        tutee = User.objects.create_user(username="TUTEE1", password="Tutee-password-2026", role=Role.TUTEE)
        self.client.force_login(tutee)
        upload = SimpleUploadedFile("proof.pdf", minimal_pdf_bytes(), content_type="application/pdf")
        response = self.client.post(reverse("accounts:upload_qualification"), {"file": upload})
        self.assertRedirects(response, reverse("accounts:dashboard"))
        self.assertFalse(QualificationDocument.objects.filter(tutor=tutee).exists())

    def upload_and_get_document(self):
        self.client.force_login(self.tutor)
        upload = SimpleUploadedFile("proof.pdf", minimal_pdf_bytes(), content_type="application/pdf")
        self.client.post(reverse("accounts:upload_qualification"), {"file": upload})
        return QualificationDocument.objects.get(tutor=self.tutor)

    def test_stored_filename_is_randomized_but_original_name_is_kept_for_display(self):
        """Batch 3 item 5: new uploads use a UUID-based server-side filename so stored
        paths aren't predictable/enumerable; original_filename (already tracked) is what
        gets shown and used for Content-Disposition."""
        document = self.upload_and_get_document()
        self.assertEqual(document.original_filename, "proof.pdf")
        self.assertNotIn("proof", document.file.name)

    def test_owner_can_download_with_private_headers(self):
        document = self.upload_and_get_document()
        self.client.force_login(self.tutor)
        response = self.client.get(reverse("accounts:download_qualification", args=[document.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment", response["Content-Disposition"])
        self.assertIn("proof.pdf", response["Content-Disposition"])
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")

    def test_admin_can_download_qualification(self):
        document = self.upload_and_get_document()
        self.client.force_login(self.admin)
        response = self.client.get(reverse("accounts:download_qualification", args=[document.pk]))
        self.assertEqual(response.status_code, 200)

    def test_other_tutor_cannot_download_qualification(self):
        document = self.upload_and_get_document()
        other_tutor = User.objects.create_user(username="TUTOR2", password="Tutor-password-2026", role=Role.TUTOR)
        self.client.force_login(other_tutor)
        response = self.client.get(reverse("accounts:download_qualification", args=[document.pk]))
        self.assertEqual(response.status_code, 404)

    def test_tutee_cannot_download_qualification(self):
        document = self.upload_and_get_document()
        tutee = User.objects.create_user(username="TUTEE2", password="Tutee-password-2026", role=Role.TUTEE)
        self.client.force_login(tutee)
        response = self.client.get(reverse("accounts:download_qualification", args=[document.pk]))
        self.assertEqual(response.status_code, 404)

    def test_unauthenticated_user_cannot_download_qualification(self):
        document = self.upload_and_get_document()
        self.client.logout()
        response = self.client.get(reverse("accounts:download_qualification", args=[document.pk]))
        self.assertNotEqual(response.status_code, 200)


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

    def test_roster_admin_shows_visible_filter_bar(self):
        response = self.client.get(reverse("admin:accounts_rosterentry_changelist"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "篩選名冊 / Filter roster")
        self.assertContains(response, 'name="role__exact"')
        self.assertContains(response, 'name="identity_category__exact"')
        self.assertContains(response, 'name="program__id__exact"')
        self.assertContains(response, 'name="claimed"')

    def test_roster_admin_combines_role_identity_and_claimed_filters(self):
        matching = RosterEntry.objects.create(
            student_id="FILTER-TUTOR",
            role=Role.TUTOR,
            education_level=EducationLevel.MASTER,
            identity_category=IdentityCategory.LOCAL,
            claimed_at=timezone.now(),
        )
        RosterEntry.objects.create(
            student_id="FILTER-OTHER",
            role=Role.TUTOR,
            education_level=EducationLevel.MASTER,
            identity_category=IdentityCategory.INTERNATIONAL,
        )

        response = self.client.get(
            reverse("admin:accounts_rosterentry_changelist"),
            {
                "role__exact": Role.TUTOR,
                "identity_category__exact": IdentityCategory.LOCAL,
                "claimed": "yes",
            },
        )

        self.assertEqual(response.status_code, 200)
        result_ids = {entry.pk for entry in response.context["cl"].result_list}
        self.assertEqual(result_ids, {matching.pk})


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


class AdminAuditLogMirrorTests(TestCase):
    """Checklist item 15: Django Admin CRUD should also land in our own AuditLog."""

    def setUp(self):
        self.admin = User.objects.create_superuser(username="MIRROR-ADMIN", password="Admin-password-2026")
        self.client.force_login(self.admin)

    def test_admin_addition_is_mirrored_into_audit_log(self):
        response = self.client.post(
            reverse("admin:accounts_partnerprogram_add"),
            {"code": "MIRROR-TEST", "name_zh": "測試計畫", "name_en": "Test program"},
        )
        self.assertEqual(response.status_code, 302)
        log = AuditLog.objects.get(event_type="ADMIN_ADDED_PARTNERPROGRAM")
        self.assertEqual(log.actor, self.admin)
        self.assertIn("測試計畫", log.description)
        self.assertEqual(log.metadata["model"], "PartnerProgram")

    def test_admin_change_to_user_sets_target_user(self):
        subject = User.objects.create_user(username="MIRROR-SUBJECT", password="Password-2026", role=Role.TUTOR)
        response = self.client.post(
            reverse("admin:accounts_user_change", args=[subject.pk]),
            {
                "username": subject.username, "role": Role.TUTOR, "account_status": AccountStatus.ACTIVE,
                "date_joined_0": "2026-01-01", "date_joined_1": "00:00:00",
            },
        )
        self.assertEqual(response.status_code, 302)
        log = AuditLog.objects.get(event_type="ADMIN_CHANGED_USER")
        self.assertEqual(log.actor, self.admin)
        self.assertEqual(log.target_user, subject)


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
            sheet.append(list(row) if isinstance(row, (list, tuple)) else [row])
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

    def test_quick_import_reads_student_id_and_identity_from_two_column_xlsx(self):
        self.client.force_login(self.admin)
        upload = self._xlsx_upload(
            "ST101.xlsx",
            [
                ("學號", "入學身份"),
                ("S30210001", "僑生"),
                ("S30210002", "港澳生"),
                ("S30210003", "陸生"),
                ("S30210004", "外國學生"),
                ("S30210005", "本地生"),
            ],
        )
        response = self.client.post(
            reverse("accounts:roster_import_quick", args=["NTNU"]), {"file": upload}
        )
        self.assertRedirects(response, reverse("accounts:dashboard") + "#roster-import")
        expected = {
            "S30210001": IdentityCategory.OVERSEAS,
            "S30210002": IdentityCategory.HONG_KONG_MACAO,
            "S30210003": IdentityCategory.MAINLAND,
            "S30210004": IdentityCategory.INTERNATIONAL,
            "S30210005": IdentityCategory.LOCAL,
        }
        actual = dict(
            RosterEntry.objects.filter(student_id__in=expected).values_list(
                "student_id", "identity_category"
            )
        )
        self.assertEqual(actual, expected)

    def test_quick_import_backfills_blank_identity_without_overwriting_existing_value(self):
        blank_entry = RosterEntry.objects.create(
            student_id="S30220001", role=Role.TUTEE, program=self.ntnu
        )
        existing_entry = RosterEntry.objects.create(
            student_id="S30220002",
            role=Role.TUTEE,
            program=self.ntnu,
            identity_category=IdentityCategory.LOCAL,
        )
        self.client.force_login(self.admin)
        upload = self._xlsx_upload(
            "ST101.xlsx",
            [
                ("學號", "入學身份"),
                (blank_entry.student_id, "僑生"),
                (existing_entry.student_id, "外國學生"),
            ],
        )
        response = self.client.post(
            reverse("accounts:roster_import_quick", args=["NTNU"]),
            {"file": upload},
            follow=True,
        )
        blank_entry.refresh_from_db()
        existing_entry.refresh_from_db()
        self.assertEqual(blank_entry.identity_category, IdentityCategory.OVERSEAS)
        self.assertEqual(existing_entry.identity_category, IdentityCategory.LOCAL)
        self.assertContains(response, "已補上 1 筆")
        self.assertContains(response, "保留系統原資料")
        log = AuditLog.objects.get(event_type="ROSTER_IMPORTED")
        self.assertEqual(log.metadata["updated_count"], 1)

    def test_quick_import_skips_unknown_identity_value(self):
        self.client.force_login(self.admin)
        upload = self._xlsx_upload(
            "unknown_identity.xlsx",
            [("學號", "入學身份"), ("S30230001", "未知身分")],
        )
        response = self.client.post(
            reverse("accounts:roster_import_quick", args=["NTNU"]),
            {"file": upload},
            follow=True,
        )
        self.assertFalse(RosterEntry.objects.filter(student_id="S30230001").exists())
        self.assertContains(response, "無法識別身分別")

    def test_quick_import_tutor_program_category_creates_maryland_tutor_roster_entries(self):
        """Item 4: a program-scoped Tutor import card (e.g. Maryland's course roster) creates
        TUTOR roster entries with that program set, distinct from the plain TUTOR category."""
        self.client.force_login(self.admin)
        upload = self._csv_upload("maryland_tutors.csv", ["S30250001"])
        response = self.client.post(
            reverse("accounts:roster_import_quick", args=["TUTOR:MARYLAND"]), {"file": upload}
        )
        self.assertRedirects(response, reverse("accounts:dashboard") + "#roster-import")
        entry = RosterEntry.objects.get(student_id="S30250001")
        self.assertEqual(entry.role, Role.TUTOR)
        self.assertEqual(entry.program_id, self.maryland.pk)
        log = AuditLog.objects.get(event_type="ROSTER_IMPORTED")
        self.assertEqual(log.metadata["category"], "TUTOR:MARYLAND")

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
                "email": "tutor.edit@example.com",
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
        self.assertEqual(self.tutor.email, "tutor.edit@example.com")
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
                "email": "tutee.edit@example.com",
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
                "email": "forged.name@example.com",
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
                "email": "missing.field@example.com",
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


class DemoSeedGuardTests(TestCase):
    """Vulnerability scan prep (docs/VULNERABILITY_SCAN_IMPROVEMENTS.md batch 1): every
    seed/demo command must require DEBUG=True AND an explicit ALLOW_DEMO_SEED=1, not just
    DEBUG, so a production host misconfigured with DJANGO_DEBUG=1 can't still be used to
    create a persistent DEMO-ADMIN superuser or self-registerable TEST roster entries."""

    # seed_matching_demo/seed_admin_demo/seed_demo require --password; seed_test_roster,
    # seed_v2_demo, and seed_v2_time_demo take no arguments at all.
    SEED_COMMAND_KWARGS = {
        "seed_demo": {"password": "Password-2026"},
        "seed_test_roster": {},
        "seed_matching_demo": {"password": "Password-2026"},
        "seed_admin_demo": {"password": "Password-2026"},
        "seed_v2_demo": {},
        "seed_v2_time_demo": {},
    }

    def assert_blocked(self, command_name):
        with self.assertRaises(CommandError):
            call_command(command_name, **self.SEED_COMMAND_KWARGS[command_name])

    @override_settings(DEBUG=True)
    def test_blocked_when_debug_true_but_allow_flag_missing(self):
        os.environ.pop("ALLOW_DEMO_SEED", None)
        for command_name in self.SEED_COMMAND_KWARGS:
            with self.subTest(command=command_name):
                self.assert_blocked(command_name)

    @override_settings(DEBUG=False)
    def test_blocked_when_allow_flag_set_but_debug_false(self):
        with patch.dict(os.environ, {"ALLOW_DEMO_SEED": "1"}):
            for command_name in self.SEED_COMMAND_KWARGS:
                with self.subTest(command=command_name):
                    self.assert_blocked(command_name)

    @override_settings(DEBUG=False)
    def test_blocked_when_both_conditions_missing(self):
        os.environ.pop("ALLOW_DEMO_SEED", None)
        for command_name in self.SEED_COMMAND_KWARGS:
            with self.subTest(command=command_name):
                self.assert_blocked(command_name)

    def test_seed_demo_runs_when_both_conditions_met(self):
        with override_settings(DEBUG=True), patch.dict(os.environ, {"ALLOW_DEMO_SEED": "1"}):
            call_command("seed_demo", password="Password-2026")
        self.assertTrue(User.objects.filter(username="DEMO-ADMIN").exists())
