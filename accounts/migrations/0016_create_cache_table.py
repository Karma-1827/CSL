"""Creates the PostgreSQL-backed cache table used by CACHES["default"]
(config/settings.py, docs/VULNERABILITY_SCAN_IMPROVEMENTS.md batch 5).

Uses Django's own `createcachetable` management command rather than a hand-written
CreateModel, since the cache table's exact column layout is a Django cache-backend
implementation detail, not a project model — `createcachetable` is what Django itself
recommends and keeps this migration correct even if a future Django version changes that
layout.
"""

from django.core.management import call_command
from django.db import migrations


def create_cache_table(apps, schema_editor):
    call_command("createcachetable")


def drop_cache_table(apps, schema_editor):
    schema_editor.execute("DROP TABLE IF EXISTS django_cache_table")


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0015_alter_rosterentry_identity_category"),
    ]

    operations = [
        migrations.RunPython(create_cache_table, reverse_code=drop_cache_table),
    ]
