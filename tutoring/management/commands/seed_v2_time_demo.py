from datetime import timedelta
from decimal import Decimal
import uuid

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from tutoring.models import ClassSession, ClassSessionStatus, Pairing, PairingStatus


PAST_DEMO_GROUP = uuid.UUID("00000000-0000-4000-8000-000000000201")
LIVE_DEMO_GROUP = uuid.UUID("00000000-0000-4000-8000-000000000202")


class Command(BaseCommand):
    help = "Create resettable local V2 makeup and live class test sessions."

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("This demo command is disabled when DEBUG is false.")

        pairing = Pairing.objects.filter(
            tutor__username="DEMO-TUTOR",
            tutee__username="DEMO-TUTEE",
            status=PairingStatus.ACTIVE,
        ).select_related("tutor", "semester").first()
        if not pairing:
            raise CommandError("The DEMO-TUTOR and DEMO-TUTEE active pairing does not exist.")

        now = timezone.localtime().replace(microsecond=0)
        past_start = now - timedelta(days=2, minutes=30)
        live_start = now - timedelta(minutes=25)

        past = self._reset_session(
            pairing=pairing,
            marker=PAST_DEMO_GROUP,
            starts_at=past_start,
            duration=Decimal("0.5"),
        )
        live = self._reset_session(
            pairing=pairing,
            marker=LIVE_DEMO_GROUP,
            starts_at=live_start,
            duration=Decimal("0.5"),
        )

        self.stdout.write(self.style.SUCCESS("V2 timed demo classes are ready."))
        self.stdout.write(
            f"MAKEUP: id={past.pk}, {past.class_date} {past.start_time:%H:%M}, ended more than 24 hours ago"
        )
        self.stdout.write(
            f"LIVE: id={live.pk}, {live.class_date} {live.start_time:%H:%M}, ends at {live.ends_at:%H:%M:%S} (about 5 minutes remaining)"
        )

    def _reset_session(self, *, pairing, marker, starts_at, duration):
        session, _ = ClassSession.objects.update_or_create(
            recurrence_group=marker,
            defaults={
                "pairing": pairing,
                "class_date": starts_at.date(),
                "start_time": starts_at.time(),
                "duration": duration,
                "status": ClassSessionStatus.SCHEDULED,
                "created_by": pairing.tutor,
                "cancellation_reason": "",
                "cancelled_by": None,
                "cancelled_at": None,
            },
        )
        session.attendances.all().delete()
        session.class_records.all().delete()
        session.confirmations.all().delete()
        session.class_alerts.all().delete()
        if hasattr(session, "makeup_review"):
            session.makeup_review.delete()
        return session
