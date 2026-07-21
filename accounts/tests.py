from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from tutoring.models import QualificationDocument, TuteeProfile, TutorProfile

from .models import EducationLevel, IdentityCategory, ProgramSource, RegistrationDraft, Role, RosterEntry, User


class RegistrationTests(TestCase):
    def setUp(self):
        self.roster = RosterEntry.objects.create(
            student_id="TEST1001",
            name_zh="測試學生",
            name_en="Test Student",
            role=Role.TUTOR,
            education_level=EducationLevel.MASTER,
            identity_category=IdentityCategory.LOCAL,
            program_source=ProgramSource.NOT_APPLICABLE,
        )
        self.registration_data = {
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
        RosterEntry.objects.create(
            student_id="TUTEE1001",
            name_zh="受輔導學生",
            name_en="Tutee Student",
            role=Role.TUTEE,
            education_level=EducationLevel.NOT_APPLICABLE,
            identity_category=IdentityCategory.INTERNATIONAL,
            program_source=ProgramSource.MARYLAND,
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
