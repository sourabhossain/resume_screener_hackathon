"""An evaluator is shown by the account's full name, else its username."""
from datetime import date

import pytest

from apps.interviews.models import Interview, InterviewEvaluation


@pytest.fixture
def interview(sample_resume):
    return Interview.objects.create(resume=sample_resume, scheduled_date=date(2026, 10, 12), status='completed')


def _evaluation(interview, **fields):
    return InterviewEvaluation.objects.create(interview=interview, recommendation='yes', is_submitted=True,
                                              scores={'adaptability': 4}, **fields)


@pytest.mark.django_db
def test_the_full_name_is_shown_and_follows_the_account(interview, django_user_model):
    panel = django_user_model.objects.create_user('panel', 'panel@sslwireless.com', 'x')
    evaluation = _evaluation(interview, evaluator=panel, interviewer_name='panel')
    assert evaluation.display_name == 'panel'

    panel.first_name, panel.last_name = 'Sourab', 'Hossain'
    panel.save()
    evaluation.refresh_from_db()
    assert evaluation.display_name == 'Sourab Hossain' == str(evaluation).split(' → ')[0]


@pytest.mark.django_db
def test_an_outside_evaluator_or_a_removed_account_keeps_the_recorded_name(interview, django_user_model):
    outside = _evaluation(interview, interviewer_name='Guest Panelist')
    assert outside.display_name == 'Guest Panelist'
    gone = django_user_model.objects.create_user('gone', 'gone@sslwireless.com', 'x', first_name='Old', last_name='Name')
    removed = _evaluation(interview, evaluator=gone, interviewer_name='Old Name')
    gone.delete()
    removed.refresh_from_db()
    assert removed.evaluator is None and removed.display_name == 'Old Name'


@pytest.mark.django_db
def test_the_interview_page_shows_the_full_name(authenticated_client, interview, django_user_model):
    panel = django_user_model.objects.create_user('hr.user', 'hr@sslwireless.com', 'x',
                                                  first_name='Sourab', last_name='Hossain')
    _evaluation(interview, evaluator=panel, interviewer_name='hr.user')
    html = authenticated_client.get(f'/interviews/{interview.pk}/').content.decode()
    assert 'Sourab Hossain' in html and '>hr.user<' not in html
