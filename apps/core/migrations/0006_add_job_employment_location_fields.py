
from django.db import migrations, models

class Migration(migrations.Migration):

    dependencies = [
        ('core', '0005_resume_achievement_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='job',
            name='employment_type',
            field=models.CharField(blank=True, choices=[('full_time', 'Full-time'), ('part_time', 'Part-time'), ('contract', 'Contract'), ('freelance', 'Freelance'), ('internship', 'Internship')], max_length=20),
        ),
        migrations.AddField(
            model_name='job',
            name='location',
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name='job',
            name='location_type',
            field=models.CharField(blank=True, choices=[('on_site', 'On-site'), ('remote', 'Remote'), ('hybrid', 'Hybrid')], max_length=10),
        ),
    ]
