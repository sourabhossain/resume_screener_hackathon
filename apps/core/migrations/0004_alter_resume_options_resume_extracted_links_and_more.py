
from django.db import migrations, models

class Migration(migrations.Migration):

    dependencies = [
        ('core', '0003_job_required_education_job_required_experience_and_more'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='resume',
            options={'ordering': [models.OrderBy(models.F('final_score'), descending=True, nulls_last=True), '-created_at']},
        ),
        migrations.AddField(
            model_name='resume',
            name='extracted_links',
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name='resume',
            name='verification_results',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name='resume',
            name='verification_score',
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='resume',
            name='verification_status',
            field=models.CharField(choices=[('pending', 'Pending'), ('processing', 'Processing'), ('completed', 'Completed'), ('failed', 'Failed'), ('skipped', 'Skipped')], default='pending', max_length=20),
        ),
        migrations.AddField(
            model_name='resume',
            name='verified_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddIndex(
            model_name='job',
            index=models.Index(fields=['status', 'is_deleted'], name='job_status_deleted_idx'),
        ),
        migrations.AddIndex(
            model_name='job',
            index=models.Index(fields=['-created_at'], name='job_created_idx'),
        ),
        migrations.AddIndex(
            model_name='job',
            index=models.Index(fields=['title'], name='job_title_idx'),
        ),
        migrations.AddIndex(
            model_name='resume',
            index=models.Index(fields=['job', 'is_deleted'], name='resume_job_deleted_idx'),
        ),
        migrations.AddIndex(
            model_name='resume',
            index=models.Index(fields=['tier'], name='resume_tier_idx'),
        ),
        migrations.AddIndex(
            model_name='resume',
            index=models.Index(fields=['-final_score'], name='resume_score_idx'),
        ),
        migrations.AddIndex(
            model_name='resume',
            index=models.Index(fields=['screening_status'], name='resume_status_idx'),
        ),
    ]
