from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.management.commands._demo_guard import ensure_demo_seed_allowed
from accounts.models import EducationLevel, IdentityCategory, PartnerProgram, Role, RosterEntry


class Command(BaseCommand):
    help = "Create local-only demo users and roster entries."

    def add_arguments(self, parser):
        parser.add_argument("--password", required=True, help="Password for all demo accounts")

    @transaction.atomic
    def handle(self, *args, **options):
        ensure_demo_seed_allowed()
        password = options["password"]
        ntnu_program, _ = PartnerProgram.objects.get_or_create(
            code="NTNU",
            defaults={"name_zh": "師大外籍生", "name_en": "NTNU international student"},
        )
        roster_rows = [
            {
                "student_id": "DEMO-TUTOR",
                "name_zh": "王小華",
                "name_en": "Alex Wang",
                "role": Role.TUTOR,
                "education_level": EducationLevel.MASTER,
                "identity_category": IdentityCategory.LOCAL,
                "program": None,
            },
            {
                "student_id": "DEMO-TUTEE",
                "name_zh": "林安娜",
                "name_en": "Anna Lin",
                "role": Role.TUTEE,
                "education_level": EducationLevel.NOT_APPLICABLE,
                "identity_category": IdentityCategory.INTERNATIONAL,
                "program": ntnu_program,
            },
        ]
        for row in roster_rows:
            RosterEntry.objects.update_or_create(student_id=row["student_id"], defaults=row)

        User = get_user_model()
        admin, _ = User.objects.get_or_create(
            username="DEMO-ADMIN",
            defaults={"role": Role.ADMIN, "name_zh": "系統管理員", "name_en": "System Administrator", "is_staff": True, "is_superuser": True},
        )
        admin.set_password(password)
        admin.is_staff = True
        admin.is_superuser = True
        admin.role = Role.ADMIN
        admin.save()
        self.stdout.write(self.style.SUCCESS("Demo admin created: DEMO-ADMIN"))

