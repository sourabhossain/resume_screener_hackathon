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

    resumes = Resume.objects.all()
    ranks = dashboard.furthest_stages(resumes, dashboard.hr_answers(resumes))
    counts = {s['key']: s['count'] for s in dashboard.funnel(ranks)['stages']}

    assert counts == {'applied': 5, 'shortlisted': 4, 'phone_screen': 3,
                      'interviewing': 3, 'offer_extended': 2, 'hired': 1}


@pytest.mark.django_db
def test_without_hr_access_the_funnel_ignores_the_hr_form(sample_job):
    offered = _resume(sample_job, 'Offered then withdrew', 'withdrawn')
    HRVerification.objects.create(resume=offered, answers={'offer_letter_issued': 'yes'})

    ranks = dashboard.furthest_stages(Resume.objects.all())

    assert ranks[offered.pk] == 0


@pytest.mark.django_db
def test_a_cancelled_interview_does_not_count_as_interviewing(sample_job):
    resume = _resume(sample_job, 'Cancelled', 'rejected')
    Interview.objects.create(resume=resume, scheduled_date=date.today(), status='cancelled')

    assert dashboard.furthest_stages(Resume.objects.all())[resume.pk] == 0


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
    for accepted in ('yes', 'no', 'pending'):
        resume = _resume(sample_job, accepted)
        HRVerification.objects.create(resume=resume, answers={
            'offer_letter_issued': 'yes', 'offer_accepted': accepted})

    hr = dashboard.hr_answers(Resume.objects.all())
    assert dashboard._offer_stats(hr) == {'accepted': 1, 'declined': 1, 'pending': 1}


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



@pytest.mark.django_db
def test_hr_only_numbers_never_reach_a_recruiter(client, django_user_model, sample_job):
    django_user_model.objects.create_user(username='plain', password='p')
    resume = _resume(sample_job, 'Checked')
    HRVerification.objects.create(resume=resume, answers={
        'offer_letter_issued': 'yes', 'offer_accepted': 'yes', 'risk_rating': 'red'})
    client.login(username='plain', password='p')

    response = client.get(reverse('core:dashboard'))
    body = response.content.decode()

    assert 'Offer acceptance' not in body
    assert 'Reference checks' not in body
    assert 'Assessments' not in body
    assert [r['label'] for r in response.context['pipeline']] == ['Information form']
    assert response.context['bgv'] is None


@pytest.mark.django_db
def test_a_job_without_an_owner_reads_unassigned(sample_job):
    Job.objects.filter(pk=sample_job.pk).update(owner=None)
    _resume(sample_job, 'Someone')

    rows = dashboard.recruiter_table(Resume.objects.all(), {})

    assert rows[0]['name'] == 'Unassigned'


@pytest.mark.django_db
def test_a_draft_job_can_be_filtered_and_shows_as_selected(authenticated_client, user):
    draft = Job.objects.create(owner=user, title='Draft role', status='draft')

    response = authenticated_client.get(reverse('core:dashboard'), {'job': draft.slug})

    assert response.context['job'] == draft
    assert f'value="{draft.slug}" selected' in response.content.decode()


@pytest.mark.django_db
@pytest.mark.parametrize('range_key', ['7d', '30d', '90d', '12m'])
def test_the_kpi_and_the_trend_count_the_same_window(sample_job, range_key):
    for days in (0, 3, 20, 45, 80, 100, 200, 340, 400):
        _resume(sample_job, f'{days} days', days_ago=days)

    now = timezone.now()
    in_view = dashboard.scoped_resumes(range_key, None, now=now).count()

    assert dashboard.trend(range_key, None, now=now)['total'] == in_view


@pytest.mark.django_db
def test_a_retired_assessment_does_not_break_the_dashboard(sample_job):
    from apps.sei_assessment.models import AssessmentInvitation, SEIAssessment
    resume = _resume(sample_job, 'Old test')
    invitation = AssessmentInvitation.objects.create(resume=resume, invited_at=timezone.now())
    SEIAssessment.objects.create(resume=resume, invitation=invitation, instrument='retired')

    rows = dashboard.pipeline_progress(Resume.objects.all(), hr_view=True)

    assert {r['label'] for r in rows} >= {'Assessments'}


@pytest.mark.django_db
def test_expired_or_cancelled_evaluations_are_not_pending(sample_job):
    from apps.interviews.models import InterviewEvaluation
    resume = _resume(sample_job, 'Interviewed')
    live = Interview.objects.create(resume=resume, scheduled_date=date.today())
    cancelled = Interview.objects.create(resume=resume, scheduled_date=date.today(), status='cancelled')
    InterviewEvaluation.objects.create(interview=live, interviewer_name='A',
                                       token_expires_at=timezone.now() + timedelta(days=5))
    InterviewEvaluation.objects.create(interview=live, interviewer_name='B',
                                       token_expires_at=timezone.now() - timedelta(days=1))
    InterviewEvaluation.objects.create(interview=cancelled, interviewer_name='C',
                                       token_expires_at=timezone.now() + timedelta(days=5))

    assert dashboard.interview_summary(Resume.objects.all())['evaluations_pending'] == 1


@pytest.mark.django_db
def test_attention_counts_skip_deleted_jobs(sample_job):
    from apps.employee_form.models import EmployeeForm
    resume = _resume(sample_job, 'Gone')
    EmployeeForm.objects.create(resume=resume, last_error='SMTP down')
    sample_job.soft_delete()

    labels = {i['label'] for i in dashboard.attention_items(hr_view=True)}

    assert 'Invites failed to send' not in labels
