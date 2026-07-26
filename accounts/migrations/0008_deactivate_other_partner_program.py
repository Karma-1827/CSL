from django.db import migrations


def deactivate_other(apps, schema_editor):
    PartnerProgram = apps.get_model("accounts", "PartnerProgram")
    PartnerProgram.objects.filter(code="OTHER").update(is_active=False)


def reactivate_other(apps, schema_editor):
    PartnerProgram = apps.get_model("accounts", "PartnerProgram")
    PartnerProgram.objects.filter(code="OTHER").update(is_active=True)


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0007_alter_rosterentry_identity_category_and_more"),
    ]

    operations = [
        migrations.RunPython(deactivate_other, reactivate_other),
    ]
