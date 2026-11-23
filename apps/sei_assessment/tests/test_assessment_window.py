"""The job decides how long a candidate has to finish the assessments, counted from the send."""
from datetime import timedelta
from unittest import mock

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.core.forms import JobForm
from apps.core.models import Job, Resume
from apps.sei_assessment.models import AssessmentInvitation
from apps.sei_assessment.services import issue_invite


@pytest.fixture
def candidate(sample_job):
    sample_job.assessments = ['pe']
    sample_job.save()
    return Resume.objects.create(job=sample_job, candidate_name='Nadia Islam', email='nadia@example.com',
                                 screening_status='completed')


def _send(resume, **kwargs):
    with mock.patch('apps.core.utils.queue_task', return_value=True):
        return issue_invite(resume, **kwargs)


def test_existing_jobs_keep_seven_days():
    assert Job._meta.get_field('assessment_window_hours').default == 168
    assert [h for h, _ in Job.ASSESSMENT_WINDOW_CHOICES] == [24, 48, 72, 168]


@pytest.mark.django_db
@pytest.mark.parametrize('hours', [24, 48, 72, 168])
def test_the_link_closes_the_chosen_time_after_it_is_sent(candidate, hours):
    Job.objects.filter(pk=candidate.job_id).update(assessment_window_hours=hours)
    candidate.refresh_from_db()
    before = timezone.now()
    invitation = _send(candidate)
    expected = before + timedelta(hours=hours)
    assert abs((invitation.token_expires_at - expected).total_seconds()) < 5


@pytest.mark.django_db
def test_the_window_starts_at_the_send_not_when_the_row_was_made(candidate):
    Job.objects.filter(pk=candidate.job_id).update(assessment_window_hours=24)
    candidate.refresh_from_db()
    stale = AssessmentInvitation.objects.create(resume=candidate)
    AssessmentInvitation.objects.filter(pk=stale.pk).update(token_expires_at=timezone.now() + timedelta(hours=2))
    invitation = _send(candidate)
    assert invitation.token_expires_at > timezone.now() + timedelta(hours=23)


@pytest.mark.django_db
def test_after_the_window_the_portal_shows_the_link_has_closed(client, candidate):
    Job.objects.filter(pk=candidate.job_id).update(assessment_window_hours=24)
    candidate.refresh_from_db()
    invitation = _send(candidate)
    AssessmentInvitation.objects.filter(pk=invitation.pk).update(
        token_expires_at=timezone.now() - timedelta(minutes=1))
    page = client.get(reverse('sei_assessment:entry', kwargs={'token': invitation.token}))
    assert 'has now closed' in page.content.decode()


@pytest.mark.django_db
def test_a_resend_after_it_closed_gives_the_full_window_again(candidate):
    Job.objects.filter(pk=candidate.job_id).update(assessment_window_hours=48)
    candidate.refresh_from_db()
    invitation = _send(candidate)
    AssessmentInvitation.objects.filter(pk=invitation.pk).update(
        token_expires_at=timezone.now() - timedelta(hours=1), invited_at=timezone.now() - timedelta(hours=49))
    with mock.patch('apps.core.utils.claim_send', return_value=True):
        again = _send(candidate, resend=True)
    assert again.token_expires_at > timezone.now() + timedelta(hours=47)


@pytest.mark.django_db
def test_the_job_form_saves_the_choice_and_offers_it(sample_job):
    data = {'title': 'Analyst', 'description': 'Numbers.', 'status': 'active', 'assessments': ['pe'],
            'assessment_window_hours': '24'}
    form = JobForm(data=data, instance=sample_job)
    assert form.is_valid(), form.errors
    assert form.save().assessment_window_hours == 24
    assert not JobForm(data={**data, 'assessment_window_hours': '5'}, instance=sample_job).is_valid()


@pytest.mark.django_db
def test_the_job_page_shows_the_time_to_complete_picker(authenticated_client, sample_job):
    html = authenticated_client.get(reverse('core:job_edit', kwargs={'slug': sample_job.slug})).content.decode()
    assert 'Time to complete' in html and "label: '24 hours'" in html and "label: '7 days'" in html


@pytest.mark.django_db
def test_a_post_without_the_field_keeps_the_jobs_window(sample_job):
    Job.objects.filter(pk=sample_job.pk).update(assessment_window_hours=48)
    sample_job.refresh_from_db()
    for extra in ({}, {'assessment_window_hours': ''}):
        form = JobForm(data={'title': 'Analyst', 'description': 'Numbers.', 'status': 'active', **extra},
                       instance=sample_job)
        assert form.is_valid(), form.errors
        assert form.save().assessment_window_hours == 48
