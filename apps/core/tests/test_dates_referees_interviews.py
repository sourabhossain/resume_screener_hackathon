"""Joining and notice dates, referee addresses, and the interview's status."""
from datetime import timedelta
from unittest import mock

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.core.models import Resume


def _step_of(schema_module, key):
    keys = getattr(schema_module, 'STEP_KEYS', None) or [step['key'] for step in schema_module.STEPS]
    return next(step for step in keys
                if any(q['key'] == key for q in schema_module.get_step(step)['questions']))


def _eif_errors(data, key, **kwargs):
    from apps.employee_form import schema
    from apps.employee_form.forms import StepForm
    form = StepForm(data=data, step_key=_step_of(schema, key), context=kwargs.pop('context', {}), **kwargs)
    form.is_valid()
    return form.errors


def _day(offset):
    return (timezone.localdate() + timedelta(days=offset)).isoformat()


# ── dates ────────────────────────────────────────────────────────────────
def test_a_joining_date_in_the_past_is_refused():
    errors = _eif_errors({'earliest_joining_date': _day(-3)}, 'earliest_joining_date')
    assert 'This date cannot be in the past.' in errors.get('earliest_joining_date', [])


def test_a_joining_date_from_today_on_is_accepted():
    assert 'earliest_joining_date' not in _eif_errors({'earliest_joining_date': _day(0)},
                                                      'earliest_joining_date')


def test_a_last_working_day_already_gone_is_refused_while_serving_notice():
    errors = _eif_errors({'availability_status': 'serving_notice', 'last_working_day': _day(-1)},
                         'last_working_day')
    assert 'This date cannot be in the past.' in errors.get('last_working_day', [])


def test_nobody_joins_before_their_last_working_day():
    errors = _eif_errors({'availability_status': 'serving_notice', 'last_working_day': _day(30),
                          'earliest_joining_date': _day(10)}, 'earliest_joining_date')
    assert 'The joining date cannot be before your last working day.' in errors.get(
        'earliest_joining_date', [])


def test_the_hr_completion_date_cannot_precede_the_start_saved_in_another_section():
    from apps.hr_verification import schema
    from apps.hr_verification.forms import StepForm
    form = StepForm(data={'verification_completion_date': '2026-01-10'},
                    step_key=_step_of(schema, 'verification_completion_date'),
                    context={'verification_start_date': '2026-02-01'})
    form.is_valid()
    assert 'before the verification start date' in str(form.errors.get('verification_completion_date'))


def test_moving_the_hr_start_after_a_saved_completion_is_refused():
    from apps.hr_verification import schema
    from apps.hr_verification.forms import StepForm
    form = StepForm(data={'verification_start_date': '2026-03-01'},
                    step_key=_step_of(schema, 'verification_start_date'),
                    context={'verification_completion_date': '2026-02-01'})
    form.is_valid()
    assert 'after the verification completion date' in str(form.errors.get('verification_start_date'))


# ── referee addresses ────────────────────────────────────────────────────
def test_the_candidates_own_email_is_refused_as_a_referee():
    errors = _eif_errors({'reference_1_email': 'Me@Example.com'}, 'reference_1_email',
                         own_emails=('me@example.com',))
    assert 'This is your own email address' in str(errors.get('reference_1_email'))


def test_the_personal_email_saved_earlier_is_refused_for_an_employers_hr():
    errors = _eif_errors({'has_employment': 'yes', 'employer_1_hr_email': 'me@example.com'},
                         'employer_1_hr_email', own_emails=('', 'me@example.com'))
    assert 'This is your own email address' in str(errors.get('employer_1_hr_email'))


def test_both_references_cannot_be_the_same_person():
    errors = _eif_errors({'reference_2_email': 'REF@acme.com'}, 'reference_2_email',
                         context={'reference_1_email': 'ref@acme.com'})
    assert 'must be different people' in str(errors.get('reference_2_email'))


def test_a_real_referee_address_is_accepted():
    errors = _eif_errors({'reference_1_email': 'boss@acme.com'}, 'reference_1_email',
                         own_emails=('me@example.com',))
    assert 'This is your own email address' not in str(errors.get('reference_1_email', ''))


@pytest.mark.django_db
def test_hr_cannot_send_a_verification_request_to_the_candidate(sample_job):
    from apps.reference_checks import services
    resume = Resume.objects.create(job=sample_job, candidate_name='Imran', email='imran@example.com')
    with mock.patch.object(services, 'contact_for', return_value={'permitted': True, 'title': 'Employer 1'}), \
            mock.patch.object(services, 'verification_refused', return_value=False):
        with pytest.raises(services.SendError, match='belongs to Imran'):
            services.issue_request(resume, 'employer_1', kind='employer', recipient_name='X',
                                   recipient_email='IMRAN@example.com')


# ── interview status ─────────────────────────────────────────────────────
@pytest.fixture
def interview(db, sample_job):
    from apps.interviews.models import Interview
    resume = Resume.objects.create(job=sample_job, candidate_name='Panel Case')
    return Interview.objects.create(resume=resume, scheduled_date=timezone.localdate())


def _evaluation(interview, name='Panel A'):
    from apps.interviews.models import InterviewEvaluation
    return InterviewEvaluation.objects.create(interview=interview, interviewer_name=name,
                                              token_expires_at=timezone.now() + timedelta(days=3))


def _set(client, interview, action):
    return client.post(reverse('interviews:status', kwargs={'pk': interview.pk}), {'action': action})


@pytest.mark.django_db
def test_cancelling_closes_the_unused_evaluation_links(authenticated_client, client, interview):
    ev = _evaluation(interview)

    _set(authenticated_client, interview, 'cancel')

    interview.refresh_from_db()
    assert interview.status == 'cancelled'
    html = client.get(reverse('interviews:evaluate', kwargs={'token': ev.token})).content.decode()
    assert 'This Interview Was Cancelled' in html


@pytest.mark.django_db
def test_a_reopened_interview_takes_evaluations_again(authenticated_client, client, interview):
    ev = _evaluation(interview)
    _set(authenticated_client, interview, 'cancel')

    _set(authenticated_client, interview, 'reopen')

    interview.refresh_from_db()
    assert interview.status == 'scheduled'
    html = client.get(reverse('interviews:evaluate', kwargs={'token': ev.token})).content.decode()
    assert 'This Interview Was Cancelled' not in html


@pytest.mark.django_db
def test_the_last_submitted_evaluation_completes_the_interview(interview):
    first, second = _evaluation(interview, 'A'), _evaluation(interview, 'B')
    first.is_submitted = True
    first.save()
    assert interview.complete_if_all_submitted() is False

    second.is_submitted = True
    second.save()
    assert interview.complete_if_all_submitted() is True
    interview.refresh_from_db()
    assert interview.status == 'completed'


@pytest.mark.django_db
def test_a_cancelled_interview_takes_no_new_evaluators(authenticated_client, interview):
    _set(authenticated_client, interview, 'cancel')

    authenticated_client.post(reverse('interviews:detail', kwargs={'pk': interview.pk}),
                              {'interviewer_name': 'Late Panel'})

    assert not interview.evaluations.exists()


@pytest.mark.django_db
def test_a_cancelled_first_round_does_not_unlock_the_second(authenticated_client, interview):
    _set(authenticated_client, interview, 'cancel')

    authenticated_client.post(reverse('interviews:create', kwargs={'resume_uuid': interview.resume.uuid}),
                              {'phase': '2', 'scheduled_date': timezone.localdate().isoformat()})

    assert not interview.resume.interviews.filter(phase='2').exists()


@pytest.mark.django_db
def test_the_status_can_only_be_changed_by_post(authenticated_client, interview):
    response = authenticated_client.get(reverse('interviews:status', kwargs={'pk': interview.pk}))
    assert response.status_code == 405


@pytest.mark.django_db
def test_the_interview_page_offers_the_status_actions(authenticated_client, interview):
    html = authenticated_client.get(reverse('interviews:detail', kwargs={'pk': interview.pk})).content.decode()
    assert 'Cancel interview' in html and 'Mark completed' in html

    _set(authenticated_client, interview, 'cancel')
    html = authenticated_client.get(reverse('interviews:detail', kwargs={'pk': interview.pk})).content.decode()
    assert 'Reopen interview' in html and 'Cancelled' in html
