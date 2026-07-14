
from django.db import migrations, models

class Migration(migrations.Migration):

    dependencies = [
        ('core', '0007_job_slug'),
    ]

    operations = [
        migrations.AlterField(
            model_name='job',
            name='slug',
            field=models.SlugField(blank=True, max_length=255, null=True, unique=True),
        ),
    ]
