import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tutoring', '0029_alter_tutorprofile_teaching_notes'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RenameModel(old_name='MakeupReview', new_name='ClassReview'),
        migrations.AlterField(
            model_name='classreview',
            name='session',
            field=models.OneToOneField(
                on_delete=django.db.models.deletion.CASCADE, related_name='class_review', to='tutoring.classsession'
            ),
        ),
        migrations.AlterField(
            model_name='classreview',
            name='reviewed_by',
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name='reviewed_class_sessions', to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
