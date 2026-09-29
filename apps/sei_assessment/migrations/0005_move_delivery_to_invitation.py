import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sei_assessment', '0004_assessmentinvitation'),
    ]

    operations = [
        migrations.AlterField(
            model_name='seiassessment',
            name='invitation',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='sittings', to='sei_assessment.assessmentinvitation'),
        ),
        migrations.RemoveField(model_name='seiassessment', name='token_expires_at'),
        migrations.RemoveField(model_name='seiassessment', name='otp_hash'),
        migrations.RemoveField(model_name='seiassessment', name='otp_expires_at'),
        migrations.RemoveField(model_name='seiassessment', name='otp_attempts'),
        migrations.RemoveField(model_name='seiassessment', name='otp_verified_at'),
        migrations.RemoveField(model_name='seiassessment', name='invited_at'),
        migrations.RemoveField(model_name='seiassessment', name='invite_count'),
        migrations.RemoveField(model_name='seiassessment', name='invited_by'),
        migrations.RemoveField(model_name='seiassessment', name='last_error'),
        migrations.RemoveField(model_name='seiassessment', name='last_error_at'),
    ]
