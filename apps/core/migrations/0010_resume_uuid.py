import uuid

from django.db import migrations, models

def populate_uuid(apps, schema_editor):
    """Give every existing resume its own UUID before the unique constraint."""
    Resume = apps.get_model('core', 'Resume')
    for r in Resume.all_objects.all() if hasattr(Resume, 'all_objects') else Resume.objects.all():
        r.uuid = uuid.uuid4()
        r.save(update_fields=['uuid'])

class Migration(migrations.Migration):

    dependencies = [
        ('core', '0009_job_owner'),
    ]

    operations = [
        migrations.AddField(
            model_name='resume',
            name='uuid',
            field=models.UUIDField(editable=False, null=True),
        ),
        migrations.RunPython(populate_uuid, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='resume',
            name='uuid',
            field=models.UUIDField(default=uuid.uuid4, editable=False, null=True, unique=True),
        ),
    ]
