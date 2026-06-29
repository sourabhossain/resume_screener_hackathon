
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

def backfill_owner(apps, schema_editor):
    """Assign any pre-existing jobs to the first superuser (else first user)."""
    Job = apps.get_model('core', 'Job')
    User = apps.get_model(settings.AUTH_USER_MODEL.split('.')[0], settings.AUTH_USER_MODEL.split('.')[1])
    owner = User.objects.filter(is_superuser=True).order_by('id').first() or User.objects.order_by('id').first()
    if owner is not None:
        Job.objects.filter(owner__isnull=True).update(owner=owner)

class Migration(migrations.Migration):

    dependencies = [
        ('core', '0008_alter_job_slug'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='job',
            name='owner',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='jobs', to=settings.AUTH_USER_MODEL),
        ),
        migrations.RunPython(backfill_owner, migrations.RunPython.noop),
    ]
