"""The recruiter dashboard: its numbers, filters and who sees what."""
from datetime import date, timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.core import dashboard
from apps.core.models import Job, Resume
from apps.employee_form.models import EmployeeForm
from apps.hr_verification.models import HRVerification
from apps.interviews.models import Interview


def _resume(job, name, status='new', score=None, tier='', days_ago=0):
    resume = Resume.objects.create(job=job, candidate_name=name, recruiter_status=status,
                                   final_score=score, tier=tier,
                                   screening_status='completed' if score is not None else 'pending')
    if days_ago:
        Resume.objects.filter(pk=resume.pk).update(
            created_at=timezone.now() - timedelta(days=days_ago))
    return resume


@pytest.mark.django_db
def test_the_funnel_counts_the_furthest_stage_a_rejected_candidate_reached(sample_job):
    interviewed = _resume(sample_job, 'Interviewed then rejected', 'rejected')
    Interview.objects.create(resume=interviewed, scheduled_date=date.today())
    shortlisted = _resume(sample_job, 'Shortlisted then rejected', 'rejected')
    EmployeeForm.objects.create(resume=shortlisted)
    offered = _resume(sample_job, 'Offered then withdrew', 'withdrawn')
    HRVerification.objects.create(resume=offered, answers={'offer_letter_issued': 'yes'})
    _resume(sample_job, 'Hired', 'hired')
    _resume(sample_job, 'Never progressed', 'rejected')

    ranks = dashboard.furthest_stages(Resume.objects.all())
    counts = {s['key']: s['count'] for s in dashboard.funnel(ranks)['stages']}

    assert counts == {'applied': 5, 'shortlisted': 4, 'phone_screen': 3,
                      'interviewing': 3, 'offer_extended': 2, 'hired': 1}


@pytest.mark.django_db
def test_step_rates_are_relative_to_the_previous_stage(sample_job):
    for i in range(4):
        _resume(sample_job, f'New {i}')
    _resume(sample_job, 'Shortlisted', 'shortlisted')

    stages = dashboard.funnel(dashboard.furthest_stages(Resume.objects.all()))['stages']

    assert stages[1]['step_rate'] == 20.0
    assert stages[0]['step_rate'] is None


@pytest.mark.django_db
def test_the_date_range_scopes_the_candidates(sample_job):
    _resume(sample_job, 'Recent', days_ago=2)
    _resume(sample_job, 'Old', days_ago=60)

    assert dashboard.scoped_resumes('7d', None).count() == 1
    assert dashboard.scoped_resumes('90d', None).count() == 2
    assert dashboard.scoped_resumes('all', None).count() == 2


@pytest.mark.django_db
def test_the_job_filter_scopes_the_candidates(sample_job, user):
    other = Job.objects.create(owner=user, title='Designer', status='active')
    _resume(sample_job, 'Python person')
    _resume(other, 'Design person')

    assert dashboard.scoped_resumes('all', other).count() == 1


@pytest.mark.django_db
def test_offer_acceptance_reads_the_hr_form(sample_job):
    for accepted in ('yes', 'pending'):
        resume = _resume(sample_job, accepted)
        HRVerification.objects.create(resume=resume, answers={
            'offer_letter_issued': 'yes', 'offer_accepted': accepted})

    assert dashboard._offer_stats(Resume.objects.all()) == {'issued': 2, 'accepted': 1}


@pytest.mark.django_db
def test_score_distribution_bins_and_marks_one_peak(sample_job):
    for score in (55, 57, 81, 100):
        _resume(sample_job, str(score), score=score)

    bars = dashboard.score_distribution(Resume.objects.all())['bars']

    assert [b['count'] for b in bars] == [0, 0, 0, 0, 0, 2, 0, 0, 1, 1]
    assert [b['is_peak'] for b in bars].count(True) == 1


@pytest.mark.parametrize('value,ceiling', [(0, 4), (3, 4), (8, 8), (9, 12), (41, 60), (99, 100)])
def test_axis_ceilings_split_into_whole_number_ticks(value, ceiling):
    assert dashboard._nice_max(value) == ceiling
    assert all(isinstance(t, int) for t in dashboard._ticks(ceiling))


@pytest.mark.django_db
def test_the_dashboard_renders_with_filters(authenticated_client, sample_job):
    _resume(sample_job, 'Someone', 'shortlisted', score=72, tier='mid')

    response = authenticated_client.get(reverse('core:dashboard'), {'range': '30d', 'job': sample_job.slug})

    assert response.status_code == 200
    body = response.content.decode()
    assert 'Recruitment funnel' in body
    assert 'Applications over time' in body
    assert f'value="{sample_job.slug}" selected' in body


@pytest.mark.django_db
def test_an_unknown_filter_falls_back_instead_of_failing(authenticated_client):
    response = authenticated_client.get(reverse('core:dashboard'), {'range': 'forever', 'job': 'nope'})
    assert response.status_code == 200


@pytest.mark.django_db
def test_background_verification_results_are_hr_only(client, django_user_model, sample_job):
    django_user_model.objects.create_user(username='recruiter', password='p')
    django_user_model.objects.create_user(username='hr', password='p', is_staff=True)
    resume = _resume(sample_job, 'Checked')
    HRVerification.objects.create(resume=resume, answers={'risk_rating': 'red'})

    client.login(username='recruiter', password='p')
    assert 'Overall risk rating' not in client.get(reverse('core:dashboard')).content.decode()

    client.login(username='hr', password='p')
    assert 'Overall risk rating' in client.get(reverse('core:dashboard')).content.decode()


@pytest.mark.django_db
def test_an_empty_system_renders_empty_states(authenticated_client):
    body = authenticated_client.get(reverse('core:dashboard')).content.decode()
    assert 'No candidates in this period.' in body
