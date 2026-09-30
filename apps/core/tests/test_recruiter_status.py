"""The client's thirteen recruiter statuses: what each sends, blocks and records."""
from datetime import timedelta
from unittest import mock

import pytest
from django.core import mail
from django.urls import reverse
from django.utils import timezone

from apps.core import status as pipeline
from apps.core.models import Resume, StatusChange

CLIENT_LIST = [
    'New CV', 'Shortlisted', 'Phone Screening', 'Assessment / Test', 'Interviewing', 'Selected',
    'Candidate Information Received', 'Background Verification Completed', 'Offer Letter Sent',
    'Pre-Onboarding', 'Onboarded', 'Rejected', 'Withdrawn',
]


@pytest.fixture
def candidate(db, sample_job):
    sample_job.assessments = ['pe']
    sample_job.save(update_fields=['assessments'])
    return Resume.objects.create(job=sample_job, candidate_name='Mahin Chowdhury',
                                 email='mahin@example.com', screening_status='completed',
                                 verification_status='completed')


def _move(client, resume, status, htmx=False):
    extra = {'HTTP_HX_REQUEST': 'true'} if htmx else {}
    return client.post(reverse('core:resume_status_update', kwargs={'uuid': resume.uuid}),
                       {'recruiter_status': status, 'context': 'card'}, **extra)


def _subjects():
    return [m.subject.lower() for m in mail.outbox]


def test_the_statuses_are_the_clients_list_in_order():
    assert [label for _, label in Resume.RECRUITER_STATUS_CHOICES] == CLIENT_LIST


def test_stored_keys_keep_their_meaning():
    labels = dict(Resume.RECRUITER_STATUS_CHOICES)
    assert labels['new'] == 'New CV'
    assert labels['phone_screen'] == 'Phone Screening'
    assert labels['offer_extended'] == 'Offer Letter Sent'
    assert labels['hired'] == 'Onboarded'


def test_every_status_has_a_tone_that_has_css_and_a_hint():
    known_tones = {'zinc', 'sky', 'cyan', 'indigo', 'violet', 'emerald', 'rose', 'amber'}
    for key, _ in Resume.RECRUITER_STATUS_CHOICES:
        assert Resume.RECRUITER_STATUS_TONES[key] in known_tones, key
        assert Resume.RECRUITER_STATUS_HINTS[key], key


# ── what each status sends ───────────────────────────────────────────────
@pytest.mark.django_db
def test_shortlisting_sends_nothing(authenticated_client, candidate):
    mail.outbox = []
    _move(authenticated_client, candidate, 'shortlisted')
    assert mail.outbox == []


@pytest.mark.django_db
def test_assessment_status_sends_the_assessment_only(authenticated_client, candidate):
    mail.outbox = []
    _move(authenticated_client, candidate, 'assessment')
    assert any('assessment' in s for s in _subjects())
    assert not any('information form' in s for s in _subjects())


@pytest.mark.django_db
def test_selected_sends_the_information_form(authenticated_client, candidate):
    mail.outbox = []
    _move(authenticated_client, candidate, 'selected')
    assert any('information form' in s for s in _subjects())
    assert candidate.employee_form.invite_count == 1


@pytest.mark.django_db
def test_jumping_past_selected_still_sends_the_information_form_once(authenticated_client, candidate):
    mail.outbox = []
    _move(authenticated_client, candidate, 'bgv_completed')
    _move(authenticated_client, candidate, 'interviewing')
    _move(authenticated_client, candidate, 'offer_extended')
    assert sum('information form' in s for s in _subjects()) == 1


# ── history ──────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_every_change_is_recorded_with_who_and_from_what(authenticated_client, user, candidate):
    _move(authenticated_client, candidate, 'shortlisted')
    _move(authenticated_client, candidate, 'phone_screen')

    changes = list(candidate.status_changes.order_by('id'))
    assert [(c.from_status, c.to_status) for c in changes] == [('new', 'shortlisted'),
                                                               ('shortlisted', 'phone_screen')]
    assert all(c.changed_by == user and c.source == 'manual' for c in changes)


@pytest.mark.django_db
def test_the_same_status_twice_records_nothing(authenticated_client, candidate):
    _move(authenticated_client, candidate, 'shortlisted')
    _move(authenticated_client, candidate, 'shortlisted')
    assert candidate.status_changes.count() == 1


# ── automatic updates ────────────────────────────────────────────────────
@pytest.mark.django_db
def test_automatic_updates_only_move_forward(candidate):
    candidate.recruiter_status = 'offer_extended'
    candidate.save()
    assert pipeline.advance(candidate, 'info_received', reason='form') is False
    candidate.refresh_from_db()
    assert candidate.recruiter_status == 'offer_extended'


@pytest.mark.django_db
@pytest.mark.parametrize('outcome', ['rejected', 'withdrawn', 'hired'])
def test_automatic_updates_never_touch_an_outcome(candidate, outcome):
    Resume.objects.filter(pk=candidate.pk).update(recruiter_status=outcome)
    assert pipeline.advance(candidate, 'bgv_completed', reason='signed off') is False
    candidate.refresh_from_db()
    assert candidate.recruiter_status == outcome


@pytest.mark.django_db
def test_an_automatic_update_is_marked_as_such(candidate):
    candidate.recruiter_status = 'selected'
    candidate.save()
    assert pipeline.advance(candidate, 'info_received', reason='Information form submitted')
    change = candidate.status_changes.first()
    assert change.source == StatusChange.AUTO and change.changed_by is None
    assert change.reason == 'Information form submitted'


@pytest.mark.django_db
def test_scheduling_an_interview_moves_the_candidate_to_interviewing(authenticated_client, candidate):
    candidate.recruiter_status = 'assessment'
    candidate.save()
    authenticated_client.post(reverse('interviews:create', kwargs={'resume_uuid': candidate.uuid}),
                              {'phase': '1', 'scheduled_date': timezone.localdate().isoformat()})
    candidate.refresh_from_db()
    assert candidate.recruiter_status == 'interviewing'


# ── Pre-Onboarding checklist and Onboarded ───────────────────────────────
def _tick_all(client, resume):
    for key, _ in Resume.ONBOARDING_CHECKLIST:
        client.post(reverse('core:resume_onboarding_toggle', kwargs={'uuid': resume.uuid}),
                    {'item': key}, HTTP_HX_REQUEST='true')


@pytest.mark.django_db
def test_onboarded_is_refused_until_the_checklist_is_done(authenticated_client, candidate):
    candidate.recruiter_status = 'pre_onboarding'
    candidate.save()

    response = _move(authenticated_client, candidate, 'hired', htmx=True)

    candidate.refresh_from_db()
    assert candidate.recruiter_status == 'pre_onboarding'
    assert 'Pre-Onboarding checklist' in response['HX-Trigger']

    _tick_all(authenticated_client, candidate)
    _move(authenticated_client, candidate, 'hired')
    candidate.refresh_from_db()
    assert candidate.recruiter_status == 'hired'


@pytest.mark.django_db
def test_ticking_an_item_records_who_and_when(authenticated_client, user, candidate):
    candidate.recruiter_status = 'pre_onboarding'
    candidate.save()

    authenticated_client.post(reverse('core:resume_onboarding_toggle', kwargs={'uuid': candidate.uuid}),
                              {'item': 'laptop'}, HTTP_HX_REQUEST='true')

    candidate.refresh_from_db()
    assert candidate.onboarding_checklist['laptop']['by'] == user.pk
    assert candidate.onboarding_done_count == 1


@pytest.mark.django_db
def test_the_checklist_is_locked_once_onboarded(authenticated_client, candidate):
    candidate.recruiter_status = 'pre_onboarding'
    candidate.save()
    _tick_all(authenticated_client, candidate)
    _move(authenticated_client, candidate, 'hired')

    authenticated_client.post(reverse('core:resume_onboarding_toggle', kwargs={'uuid': candidate.uuid}),
                              {'item': 'laptop'}, HTTP_HX_REQUEST='true')

    candidate.refresh_from_db()
    assert candidate.onboarding_complete


@pytest.mark.django_db
def test_the_onboarded_option_is_shown_disabled_until_the_checklist_is_done(authenticated_client, candidate):
    candidate.recruiter_status = 'pre_onboarding'
    candidate.save()
    html = authenticated_client.get(reverse('core:resume_detail', kwargs={'uuid': candidate.uuid})).content.decode()
    assert 'Complete the Pre-Onboarding checklist first' in html
    assert 'Pre-Onboarding checklist' in html


# ── rejection email ──────────────────────────────────────────────────────
@pytest.mark.django_db
def test_a_rejected_candidate_shows_a_pending_rejection_email(authenticated_client, candidate):
    _move(authenticated_client, candidate, 'rejected')
    candidate.refresh_from_db()
    assert candidate.rejection_email_status == 'pending'
    html = authenticated_client.get(reverse('core:resume_detail', kwargs={'uuid': candidate.uuid})).content.decode()
    assert 'Send rejection email' in html


@pytest.mark.django_db
def test_sending_the_rejection_email_marks_it_sent_once(authenticated_client, user, candidate):
    _move(authenticated_client, candidate, 'rejected')
    mail.outbox = []

    authenticated_client.post(reverse('core:resume_rejection_send', kwargs={'uuid': candidate.uuid}))
    authenticated_client.post(reverse('core:resume_rejection_send', kwargs={'uuid': candidate.uuid}))

    candidate.refresh_from_db()
    assert candidate.rejection_email_status == 'sent'
    assert candidate.rejection_email_sent_by == user
    sent = [m for m in mail.outbox if 'your application for' in m.subject.lower()]
    assert len(sent) == 1
    assert sent[0].to == ['mahin@example.com']
    assert 'not to move forward' in sent[0].body


@pytest.mark.django_db
def test_no_rejection_email_for_a_candidate_not_rejected(authenticated_client, candidate):
    mail.outbox = []
    authenticated_client.post(reverse('core:resume_rejection_send', kwargs={'uuid': candidate.uuid}))
    candidate.refresh_from_db()
    assert candidate.rejection_email_sent_at is None and mail.outbox == []


@pytest.mark.django_db
def test_a_failed_rejection_email_is_shown_and_stays_pending(authenticated_client, candidate):
    _move(authenticated_client, candidate, 'rejected')
    with mock.patch('django.core.mail.EmailMultiAlternatives.send', side_effect=OSError('smtp down')):
        authenticated_client.post(reverse('core:resume_rejection_send', kwargs={'uuid': candidate.uuid}))
    candidate.refresh_from_db()
    assert candidate.rejection_email_status == 'pending'
    assert 'smtp down' in candidate.rejection_email_error


# ── dashboard ────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_the_dashboard_flags_pending_rejection_emails_and_open_checklists(candidate, sample_job):
    from apps.core import dashboard
    Resume.objects.filter(pk=candidate.pk).update(recruiter_status='rejected')
    Resume.objects.create(job=sample_job, candidate_name='Joining Soon', recruiter_status='pre_onboarding')

    labels = {i['label'] for i in dashboard.attention_items(hr_view=False)}

    assert 'Rejection emails not sent' in labels
    assert 'Pre-onboarding checklists open' in labels
