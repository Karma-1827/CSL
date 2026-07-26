from datetime import date

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.models import EducationLevel, IdentityCategory, PartnerProgram, Role, RosterEntry, User
from tutoring.models import QualificationDocument, QualificationStatus, Semester, TuteeProfile, TutorProfile


class Command(BaseCommand):
    help = "Create local-only V1.1 matching demo accounts and profiles."

    def add_arguments(self, parser):
        parser.add_argument("--password", required=True, help="Password for all local demo accounts")

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("This demo command is disabled when DEBUG is false.")

        password = options["password"]
        Semester.objects.filter(is_active=True).update(is_active=False)
        Semester.objects.update_or_create(
            name_zh="114學年度第3學期",
            defaults={
                "name_en": "114-3 Semester",
                "starts_on": date(2026, 7, 1),
                "ends_on": date(2026, 8, 31),
                "is_active": True,
            },
        )

        ntnu_program, _ = PartnerProgram.objects.get_or_create(
            code="NTNU", defaults={"name_zh": "師大外籍生", "name_en": "NTNU international student"}
        )
        maryland_program, _ = PartnerProgram.objects.get_or_create(
            code="MARYLAND", defaults={"name_zh": "馬里蘭大學", "name_en": "University of Maryland"}
        )
        demo_rows = [
            ("DEMO-TUTOR", "王小華", "Alex Wang", Role.TUTOR, None),
            ("DEMO-TUTOR2", "陳安然", "Jamie Chen", Role.TUTOR, None),
            ("DEMO-TUTEE", "林安娜", "Anna Lin", Role.TUTEE, ntnu_program),
            ("DEMO-MARYLAND", "測試交換生", "Taylor Demo", Role.TUTEE, maryland_program),
        ]
        for index, (student_id, name_zh, name_en, role, program) in enumerate(demo_rows, start=1):
            roster, _ = RosterEntry.objects.update_or_create(
                student_id=student_id,
                defaults={
                    "name_zh": name_zh,
                    "name_en": name_en,
                    "role": role,
                    "education_level": EducationLevel.MASTER if role == Role.TUTOR else EducationLevel.NOT_APPLICABLE,
                    "identity_category": IdentityCategory.LOCAL if role == Role.TUTOR else IdentityCategory.INTERNATIONAL,
                    "program": program,
                    "is_enabled": True,
                    "claimed_at": timezone.now(),
                },
            )
            user, _ = User.objects.update_or_create(
                username=student_id,
                defaults={
                    "role": role,
                    "roster_entry": roster,
                    "name_zh": name_zh,
                    "name_en": name_en,
                    "phone": f"09000000{index:02d}",
                    "is_active": True,
                },
            )
            user.set_password(password)
            user.save(update_fields=["password"])

            if role == Role.TUTOR:
                TutorProfile.objects.update_or_create(
                    tutor=user,
                    defaults={
                        "gender": "MALE" if index == 1 else "FEMALE",
                        "native_language": "Mandarin Chinese",
                        "nationality": "Taiwan",
                        "department": "華語文教學系",
                        "level_listening": 4,
                        "level_speaking": 5,
                        "level_reading": 4,
                        "level_writing": 4,
                        "available_days": ["MON", "WED"],
                        "available_time_slots": ["13:00-15:00", "17:00-19:00"],
                    },
                )
                QualificationDocument.objects.update_or_create(
                    tutor=user,
                    defaults={
                        "file": "qualifications/demo-local-proof.pdf",
                        "original_filename": "demo-local-proof.pdf",
                        "status": QualificationStatus.APPROVED,
                    },
                )
            else:
                TuteeProfile.objects.update_or_create(
                    tutee=user,
                    defaults={
                        "gender": "FEMALE",
                        "native_language": "English",
                        "nationality": "United States",
                        "department": "Languages",
                        "overall_level": "B1" if program == ntnu_program else "A1",
                        "learning_duration": "1_TO_2_YEARS" if program == ntnu_program else "3_TO_6_MONTHS",
                        "target_skills": ["LISTENING", "SPEAKING"],
                        "skills_to_improve": "希望加強日常會話、課堂討論與口語表達。",
                        "preferred_days": ["TUE", "THU"],
                        "preferred_time_slots": ["15:00-17:00"],
                    },
                )

        self.stdout.write(self.style.SUCCESS("V1.1 local matching demo data is ready."))
        self.stdout.write("Accounts: DEMO-TUTOR, DEMO-TUTOR2, DEMO-TUTEE, DEMO-MARYLAND")
