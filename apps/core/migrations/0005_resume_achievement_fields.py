# Generated manually for achievements persistence

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0004_alter_resume_options_resume_extracted_links_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='resume',
            name='achievements',
            field=models.JSONField(blank=True, default=list, help_text='Extracted quantifiable achievements'),
        ),
        migrations.AddField(
            model_name='resume',
            name='achievement_score',
            field=models.FloatField(blank=True, null=True),
        ),
    ]
