from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0012_fix_is_deleted_db_default'),
    ]

    operations = [
        migrations.AddField(
            model_name='resume',
            name='file_hash',
            field=models.CharField(blank=True, db_index=True, max_length=64),
        ),
    ]
