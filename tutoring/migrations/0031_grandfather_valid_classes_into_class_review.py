from django.db import migrations
from django.utils import timezone


GRANDFATHER_NOTE = (
    "此課程於 2026-09-10「所有課程皆須管理員審核」規則生效前，已完成雙方簽到、課堂紀錄與互相確"
    "認並計入有效時數，系統於規則變更當下自動核准（不溯及既往）。 / This class had already "
    "completed mutual check-in, records, and confirmation and counted as valid hours before the "
    "2026-09-10 rule change requiring admin review for every class; the system auto-approved it "
    "at migration time so the new rule only applies going forward."
)


def grandfather_already_valid_classes(apps, schema_editor):
    ClassSession = apps.get_model("tutoring", "ClassSession")
    ClassReview = apps.get_model("tutoring", "ClassReview")
    now = timezone.now()
    candidates = ClassSession.objects.filter(status="SCHEDULED", class_review__isnull=True)
    for session in candidates:
        if session.attendances.count() != 2 or session.class_records.count() != 2:
            continue
        confirmed_count = session.confirmations.filter(
            status="CONFIRMED", attendance_confirmed=True, record_confirmed=True
        ).count()
        if confirmed_count != 2:
            continue
        ClassReview.objects.create(
            session=session,
            status="APPROVED",
            reviewed_by=None,
            review_note=GRANDFATHER_NOTE,
            reviewed_at=now,
        )


def noop_reverse(apps, schema_editor):
    """Not reversible in a meaningful way: we can't tell a grandfathered APPROVED row
    apart from one a human admin later approved for real once time has passed. Leaving
    the rows in place on reverse is safer than guessing which ones to delete."""


class Migration(migrations.Migration):

    dependencies = [
        ("tutoring", "0030_rename_makeupreview_classreview"),
    ]

    operations = [
        migrations.RunPython(grandfather_already_valid_classes, noop_reverse),
    ]
