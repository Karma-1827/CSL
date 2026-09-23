from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("tutoring", "0036_remove_incidentreport_session_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="MatchingExclusion",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("reason", models.TextField(max_length=500, verbose_name="內部原因 / Internal reason")),
                ("is_active", models.BooleanField(default=True, verbose_name="生效中 / Active")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("revoked_at", models.DateTimeField(blank=True, null=True, verbose_name="解除時間 / Revoked at")),
                (
                    "created_by",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="created_matching_exclusions",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="建立者 / Created by",
                    ),
                ),
                (
                    "revoked_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="revoked_matching_exclusions",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="解除者 / Revoked by",
                    ),
                ),
                (
                    "semester",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="matching_exclusions",
                        to="tutoring.semester",
                    ),
                ),
                (
                    "tutee",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="tutee_matching_exclusions",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "tutor",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="tutor_matching_exclusions",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "配對排除 / Matching exclusion",
                "verbose_name_plural": "配對排除 / Matching exclusions",
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddConstraint(
            model_name="matchingexclusion",
            constraint=models.UniqueConstraint(
                condition=models.Q(("is_active", True)),
                fields=("semester", "tutor", "tutee"),
                name="unique_active_matching_exclusion",
            ),
        ),
    ]
