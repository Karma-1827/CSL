from datetime import time, timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from tutoring.models import ClassSession, Pairing, PairingStatus
from tutoring.services import schedule_classes


class Command(BaseCommand):
    help = "Add local-only V2 schedule examples to the existing demo pairing without changing passwords."

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("This demo command is disabled when DEBUG is false.")
        pairing = Pairing.objects.filter(
            tutor__username="DEMO-TUTOR", tutee__username="DEMO-TUTEE", status=PairingStatus.ACTIVE
        ).select_related("tutor", "semester").first()
        if not pairing:
            raise CommandError("Run seed_matching_demo first so the demo pairing exists.")

        today = timezone.localdate()
        first_monday = today + timedelta(days=(7 - today.weekday()) % 7 or 7)
        examples = [
            (first_monday, time(14), "1.0"),
            (first_monday + timedelta(days=7), time(18, 30), "1.5"),
        ]
        created = 0
        for class_date, start_time, duration in examples:
            if class_date > pairing.semester.ends_on:
                continue
            exists = ClassSession.objects.filter(
                pairing=pairing, class_date=class_date, start_time=start_time
            ).exists()
            if not exists:
                schedule_classes(
                    tutor=pairing.tutor,
                    pairing=pairing,
                    class_date=class_date,
                    start_time=start_time,
                    duration=duration,
                )
                created += 1
        self.stdout.write(self.style.SUCCESS(f"V2 demo schedule ready ({created} new class(es))."))
