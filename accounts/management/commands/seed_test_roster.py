from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import EducationLevel, IdentityCategory, ProgramSource, RegistrationDraft, Role, RosterEntry, User


TEST_ROSTER = [
    {
        "student_id": "TEST-TUTOR-MASTER",
        "name_zh": "測試碩士生",
        "name_en": "Master Tutor Test",
        "role": Role.TUTOR,
        "education_level": EducationLevel.MASTER,
        "identity_category": IdentityCategory.LOCAL,
        "program_source": ProgramSource.NOT_APPLICABLE,
    },
    {
        "student_id": "TEST-TUTOR-BACHELOR",
        "name_zh": "測試大學部生",
        "name_en": "Bachelor Tutor Test",
        "role": Role.TUTOR,
        "education_level": EducationLevel.BACHELOR,
        "identity_category": IdentityCategory.LOCAL,
        "program_source": ProgramSource.NOT_APPLICABLE,
    },
    {
        "student_id": "TEST-TUTEE-NTNU",
        "name_zh": "測試師大外籍生",
        "name_en": "NTNU Tutee Test",
        "role": Role.TUTEE,
        "education_level": EducationLevel.NOT_APPLICABLE,
        "identity_category": IdentityCategory.INTERNATIONAL,
        "program_source": ProgramSource.NTNU,
    },
    {
        "student_id": "TEST-TUTEE-MARYLAND",
        "name_zh": "測試馬里蘭學生",
        "name_en": "Maryland Tutee Test",
        "role": Role.TUTEE,
        "education_level": EducationLevel.NOT_APPLICABLE,
        "identity_category": IdentityCategory.INTERNATIONAL,
        "program_source": ProgramSource.MARYLAND,
    },
]


class Command(BaseCommand):
    help = "Create unclaimed fake roster entries for local registration testing."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete accounts created from the fake roster and make all fake student IDs reusable.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        student_ids = [row["student_id"] for row in TEST_ROSTER]
        if options["reset"]:
            User.objects.filter(username__in=student_ids).delete()
            RegistrationDraft.objects.filter(roster_entry__student_id__in=student_ids).delete()
            RosterEntry.objects.filter(student_id__in=student_ids).update(claimed_at=None)
            self.stdout.write(self.style.WARNING("Existing fake registrations were reset."))
        for row in TEST_ROSTER:
            roster, created = RosterEntry.objects.get_or_create(student_id=row["student_id"], defaults=row)
            state = "created" if created else ("available" if not roster.is_claimed else "already registered")
            self.stdout.write(f"{roster.student_id}: {state}")
        self.stdout.write(self.style.SUCCESS("Local test roster is ready."))
