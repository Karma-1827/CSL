from django.db import migrations


# English counterparts for the existing Chinese-only certificate plan name / activity text
# (item 13 of MEETING_CHANGE_REQUIREMENTS_2026-08-04.md needs a real English sentence to build a
# monolingual English certificate from). First-draft wording, same status as the rest of the
# certificate copy in migrations 0005/0006 — 系辦 may want to adjust exact phrasing later.
ENGLISH_TEXT = {
    "NTNU": {
        "tutee_certificate_plan_name_en": "NTNU International Student Chinese Tutoring Program",
        "tutee_certificate_activity_text_en": "received Chinese language tutoring",
        "tutor_certificate_plan_name_en": "NTNU International Student Chinese Tutoring Program",
        "tutor_certificate_activity_text_en": "served as a Chinese tutoring assistant and completed tutoring service",
    },
    "MARYLAND": {
        "tutee_certificate_plan_name_en": "Chinese Language Exchange Program",
        "tutee_certificate_activity_text_en": "completed language exchange",
        "tutor_certificate_plan_name_en": "Chinese Language Exchange Program",
        "tutor_certificate_activity_text_en": "provided language exchange service",
    },
    "OTHER": {
        "tutee_certificate_plan_name_en": "Partner Program",
        "tutee_certificate_activity_text_en": "completed partner program activities",
        "tutor_certificate_plan_name_en": "Partner Program",
        "tutor_certificate_activity_text_en": "provided partner program services",
    },
}


def populate_english_text(apps, schema_editor):
    PartnerProgram = apps.get_model("accounts", "PartnerProgram")
    for code, fields in ENGLISH_TEXT.items():
        PartnerProgram.objects.filter(code=code).update(**fields)


def clear_english_text(apps, schema_editor):
    PartnerProgram = apps.get_model("accounts", "PartnerProgram")
    for code in ENGLISH_TEXT:
        PartnerProgram.objects.filter(code=code).update(
            tutee_certificate_plan_name_en="",
            tutee_certificate_activity_text_en="",
            tutor_certificate_plan_name_en="",
            tutor_certificate_activity_text_en="",
        )


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0011_partnerprogram_tutee_certificate_activity_text_en_and_more"),
    ]

    operations = [
        migrations.RunPython(populate_english_text, clear_english_text),
    ]
