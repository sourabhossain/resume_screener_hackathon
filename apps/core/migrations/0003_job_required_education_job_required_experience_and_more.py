
from django.db import migrations, models

class Migration(migrations.Migration):

    dependencies = [
        ('core', '0002_job_deleted_at_job_description_job_file_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='job',
            name='required_education',
            field=models.JSONField(blank=True, default=list, help_text='Required education levels'),
        ),
        migrations.AddField(
            model_name='job',
            name='required_experience',
            field=models.FloatField(blank=True, help_text='Required years of experience', null=True),
        ),
        migrations.AddField(
            model_name='job',
            name='required_skills',
            field=models.JSONField(blank=True, default=list, help_text='Required skills for matching'),
        ),
        migrations.AddField(
            model_name='resume',
            name='certification_score',
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='resume',
            name='certifications',
            field=models.JSONField(blank=True, default=list, help_text='Extracted certifications'),
        ),
        migrations.AddField(
            model_name='resume',
            name='education',
            field=models.JSONField(blank=True, default=list, help_text='Extracted education'),
        ),
        migrations.AddField(
            model_name='resume',
            name='experience_years',
            field=models.FloatField(blank=True, help_text='Total years of experience', null=True),
        ),
        migrations.AddField(
            model_name='resume',
            name='reasoning',
            field=models.TextField(blank=True, help_text='AI reasoning for recommendation'),
        ),
        migrations.AddField(
            model_name='resume',
            name='screening_status',
            field=models.CharField(choices=[('pending', 'Pending'), ('processing', 'Processing'), ('completed', 'Completed'), ('failed', 'Failed')], default='pending', max_length=20),
        ),
        migrations.AddField(
            model_name='resume',
            name='skills',
            field=models.JSONField(blank=True, default=list, help_text='Extracted skills from resume'),
        ),
    ]
