from django.db import migrations


# First-phase rollout scope for item 5 (class documents) of
# MEETING_CHANGE_REQUIREMENTS_2026-08-04.md: only Maryland Tutees and Maryland-roster
# bachelor's Tutors should see the "上課文件 / Class documents" menu item for now.
def enable_maryland(apps, schema_editor):
    PartnerProgram = apps.get_model("accounts", "PartnerProgram")
    PartnerProgram.objects.filter(code="MARYLAND").update(class_documents_enabled=True)


def disable_maryland(apps, schema_editor):
    PartnerProgram = apps.get_model("accounts", "PartnerProgram")
    PartnerProgram.objects.filter(code="MARYLAND").update(class_documents_enabled=False)


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0013_partnerprogram_class_documents_enabled"),
    ]

    operations = [
        migrations.RunPython(enable_maryland, disable_maryland),
    ]
