from datetime import timedelta

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

BEFORE = [('sei_assessment', '0003_alter_seiassessment_resume')]
AFTER = [('sei_assessment', '0004_assessmentinvitation')]


def _state(target):
    executor = MigrationExecutor(connection)
    executor.migrate(target)
    executor.loader.build_graph()
    return executor.loader.project_state(target).apps


@pytest.mark.django_db(transaction=True)
def test_sittings_are_grouped_with_the_latest_code_and_the_first_token():
    old = _state(BEFORE)
    Job = old.get_model('core', 'Job')
    Resume = old.get_model('core', 'Resume')
    Sitting = old.get_model('sei_assessment', 'SEIAssessment')
    User = old.get_model('auth', 'User')

    owner = User.objects.create(username='mig-owner')
    job = Job.objects.create(owner=owner, title='Analyst', description='x', slug='mig-analyst')
    two = Resume.objects.create(job=job, candidate_name='Two', email='two@example.com')
    one = Resume.objects.create(job=job, candidate_name='One', email='one@example.com')
    now = timezone.now()
    common = dict(token_expires_at=now + timedelta(days=7))
    sei = Sitting.objects.create(resume=two, instrument='sei', otp_hash='sei-hash',
                                 invited_at=now - timedelta(hours=2), invite_count=1, **common)
    pe = Sitting.objects.create(resume=two, instrument='pe', otp_hash='pe-hash',
                                invited_at=now - timedelta(hours=1), invite_count=2,
                                otp_verified_at=now, **common)
    solo = Sitting.objects.create(resume=one, instrument='pe', otp_hash='solo', **common)

    new = _state(AFTER)
    Invitation = new.get_model('sei_assessment', 'AssessmentInvitation')
    NewSitting = new.get_model('sei_assessment', 'SEIAssessment')

    grouped = Invitation.objects.get(resume_id=two.pk)
    assert grouped.token == sei.token
    assert grouped.otp_hash == 'pe-hash'
    assert grouped.otp_verified_at is not None
    assert grouped.invite_count == 2
    assert set(NewSitting.objects.filter(invitation=grouped).values_list('pk', flat=True)) == {sei.pk, pe.pk}

    single = Invitation.objects.get(resume_id=one.pk)
    assert single.token == solo.token and single.otp_hash == 'solo'
    assert not NewSitting.objects.filter(invitation__isnull=True).exists()

    _state(executor_latest())


def executor_latest():
    return MigrationExecutor(connection).loader.graph.leaf_nodes()
