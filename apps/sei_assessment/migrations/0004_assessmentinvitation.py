import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

# Frozen copy of instruments.ORDER.
ORDER = ('sei', 'pe')


def group_sittings(apps, schema_editor):
    """One invitation per candidate: the first sitting lends its token, the
    most recently emailed one its code."""
    Sitting = apps.get_model('sei_assessment', 'SEIAssessment')
    Invitation = apps.get_model('sei_assessment', 'AssessmentInvitation')

    rank = {key: i for i, key in enumerate(ORDER)}
    by_resume = {}
    for sitting in Sitting.objects.order_by('pk'):
        by_resume.setdefault(sitting.resume_id, []).append(sitting)

    for resume_id, sittings in by_resume.items():
        sittings.sort(key=lambda s: (rank.get(s.instrument, len(ORDER)), s.pk))
        lead = sittings[0]
        coded = [s for s in sittings if s.otp_hash] or [lead]
        latest = max(coded, key=lambda s: (s.invited_at is not None, s.invited_at or s.created_at))
        verified = [s.otp_verified_at for s in sittings if s.otp_verified_at]
        invited = [s.invited_at for s in sittings if s.invited_at]
        errored = [s for s in sittings if s.last_error]
        invitation = Invitation.objects.create(
            resume_id=resume_id,
            token=lead.token,
            token_expires_at=max(s.token_expires_at for s in sittings),
            otp_hash=latest.otp_hash,
            otp_expires_at=latest.otp_expires_at,
            otp_attempts=latest.otp_attempts,
            otp_verified_at=max(verified) if verified else None,
            invited_at=min(invited) if invited else None,
            invite_count=max(s.invite_count for s in sittings),
            invited_by_id=lead.invited_by_id,
            last_error=errored[0].last_error if errored else '',
            last_error_at=errored[0].last_error_at if errored else None,
        )
        Invitation.objects.filter(pk=invitation.pk).update(
            created_at=min(s.created_at for s in sittings))
        Sitting.objects.filter(pk__in=[s.pk for s in sittings]).update(
            invitation=invitation)


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0019_job_assessments'),
        ('sei_assessment', '0003_alter_seiassessment_resume'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='AssessmentInvitation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('token', models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ('token_expires_at', models.DateTimeField()),
                ('otp_hash', models.CharField(blank=True, max_length=128)),
                ('otp_expires_at', models.DateTimeField(blank=True, null=True)),
                ('otp_attempts', models.PositiveSmallIntegerField(default=0)),
                ('otp_verified_at', models.DateTimeField(blank=True, null=True)),
                ('invited_at', models.DateTimeField(blank=True, null=True)),
                ('invite_count', models.PositiveSmallIntegerField(default=0)),
                ('last_error', models.TextField(blank=True)),
                ('last_error_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('invited_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('resume', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='assessment_invitation', to='core.resume')),
            ],
            options={
                'db_table': 'assessment_invitation',
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddField(
            model_name='seiassessment',
            name='invitation',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='sittings', to='sei_assessment.assessmentinvitation'),
        ),
        migrations.RunPython(group_sittings, migrations.RunPython.noop),
    ]
