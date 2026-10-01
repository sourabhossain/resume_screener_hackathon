"""Fixes from the go-live review: sends, sessions, sweeps and small edges."""
import json
from datetime import timedelta
from unittest import mock

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.core.form_utils import clean_person_text
from apps.core.models import Resume


@pytest.fixture
def hr_client(client, django_user_model):
    django_user_model.objects.create_user(username='hr', password='hrpass123', is_staff=True)
    client.login(username='hr', password='hrpass123')
    return client


# ── assessment send ──────────────────────────────────────────────────────
@pytest.mark.django_db
@pytest.mark.parametrize('status', ['new', 'shortlisted', 'rejected', 'withdrawn', 'hired'])
def test_the_assessment_cannot_be_sent_outside_assessment_and_later(hr_client, sample_job, status):
    from django.core import mail
    from apps.sei_assessment import instruments
    sample_job.assessments = [instruments.PE]
    sample_job.save(update_fields=['assessments'])
    resume = Resume.objects.create(job=sample_job, candidate_name='Out Of Window',
                                   email='window@example.com', recruiter_status=status)

    hr_client.post(reverse('sei_assessment:send', kwargs={'uuid': resume.uuid}))

    assert mail.outbox == []
    assert not hasattr(Resume.objects.get(pk=resume.pk), 'assessment_invitation') or \
        Resume.objects.get(pk=resume.pk).assessment_invitation.invited_at is None


@pytest.mark.django_db
def test_a_double_click_on_the_first_assessment_send_queues_one_email(sample_job):
    from apps.sei_assessment import instruments, services
    sample_job.assessments = [instruments.PE]
    sample_job.save(update_fields=['assessments'])
    resume = Resume.objects.create(job=sample_job, candidate_name='Double Click',
                                   email='double@example.com', recruiter_status='assessment')
    with mock.patch('apps.sei_assessment.tasks.send_assessment_invite.delay') as delay:
        services.issue_invite(resume)
        with pytest.raises(services.InviteError, match='a moment ago'):
            services.issue_invite(resume)
    assert delay.call_count == 1


@pytest.mark.django_db
def test_an_autosave_that_is_not_an_object_is_refused_not_a_server_error(client, sample_job):
    from apps.sei_assessment.tests.test_portal import _begin, _enter, _invite, _part, _url, PE
    invitation = _invite(sample_job, [PE])
    _enter(client, invitation)
    _begin(client, invitation, PE)
    url = _url('save_part', invitation, part=_part(invitation, PE).token)

    for body in ([], {'answers': [1, 2]}):
        response = client.post(url, data=json.dumps(body), content_type='application/json')
        assert response.status_code == 400


# ── HR resend keeps a verified session ───────────────────────────────────
@pytest.mark.django_db
def test_hr_resending_the_form_does_not_throw_out_a_candidate_part_way_through(sample_job):
    from apps.employee_form.models import EmployeeForm
    from apps.employee_form.tasks import send_employee_form_invite
    resume = Resume.objects.create(job=sample_job, candidate_name='Mid Form', email='mid@example.com')
    verified = timezone.now() - timedelta(minutes=5)
    form = EmployeeForm.objects.create(resume=resume, otp_verified_at=verified)

    send_employee_form_invite(form.pk)

    form.refresh_from_db()
    assert form.otp_verified_at == verified
    assert form.invite_count == 1


# ── reference requests ───────────────────────────────────────────────────
@pytest.mark.django_db
def test_a_reference_request_refuses_a_malformed_or_already_used_address(sample_job):
    from apps.reference_checks import services
    resume = Resume.objects.create(job=sample_job, candidate_name='Two Refs', email='c@example.com')
    with mock.patch.object(services, 'contact_for', return_value={'permitted': True, 'title': 'Referee'}), \
            mock.patch.object(services, 'verification_refused', return_value=False):
        with pytest.raises(services.SendError, match='not a valid email'):
            services.issue_request(resume, 'reference_1', kind='professional', recipient_name='A',
                                   recipient_email='not-an-email')
        services.issue_request(resume, 'reference_1', kind='professional', recipient_name='A',
                               recipient_email='same@acme.com')
        with pytest.raises(services.SendError, match='already has a request'):
            services.issue_request(resume, 'reference_2', kind='professional', recipient_name='B',
                                   recipient_email='SAME@acme.com')


# ── names ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize('name', ['র‍্যাব', 'মো: রহিম', 'Abu Sayeed (Rony)', 'Md. Rahim, Jr.'])
def test_real_bangla_and_english_names_are_accepted(name):
    assert clean_person_text(name, required=True) == name


# ── rejection email ──────────────────────────────────────────────────────
@pytest.mark.django_db
def test_a_second_rejection_task_running_alongside_the_first_sends_nothing(sample_job):
    from django.core import mail
    from apps.core.tasks import send_rejection_email
    from apps.core.utils import claim_send
    resume = Resume.objects.create(job=sample_job, candidate_name='Once Only',
                                   email='once@example.com', recruiter_status='rejected')
    claim_send('rejection-sending', resume.pk, seconds=600)

    assert send_rejection_email(resume.pk) == 'in_progress'
    assert mail.outbox == []


# ── background sweeps ────────────────────────────────────────────────────
@pytest.mark.django_db
def test_a_lost_link_check_is_released_after_an_hour(sample_job):
    from apps.core.tasks import release_stale_screenings
    resume = Resume.objects.create(job=sample_job, candidate_name='Stuck Links',
                                   screening_status='completed', verification_status='processing')
    Resume.objects.filter(pk=resume.pk).update(updated_at=timezone.now() - timedelta(hours=2))

    assert release_stale_screenings()['links_released'] == 1
    resume.refresh_from_db()
    assert resume.verification_status == 'failed'


@pytest.mark.django_db
def test_the_status_can_be_changed_while_links_are_still_being_checked(authenticated_client, sample_job):
    resume = Resume.objects.create(job=sample_job, candidate_name='Checking Links',
                                   screening_status='completed', verification_status='processing')
    html = authenticated_client.get(reverse('core:resume_detail', kwargs={'uuid': resume.uuid})).content.decode()
    assert 'name="recruiter_status"' in html


# ── dashboard ────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_an_upcoming_interview_counts_whatever_date_range_is_picked(sample_job):
    from apps.core import dashboard
    from apps.interviews.models import Interview
    resume = Resume.objects.create(job=sample_job, candidate_name='Applied Long Ago')
    Resume.objects.filter(pk=resume.pk).update(created_at=timezone.now() - timedelta(days=200))
    Interview.objects.create(resume=resume, scheduled_date=timezone.localdate() + timedelta(days=1))

    summary = dashboard.interview_summary(Resume.objects.none())

    assert summary['upcoming'] == 1


# ── checklist and api ────────────────────────────────────────────────────
@pytest.mark.django_db
def test_checklist_times_are_read_back_as_dates_not_strings(sample_job):
    resume = Resume.objects.create(job=sample_job, candidate_name='Checklist', onboarding_checklist={
        'id_card': {'at': '2026-09-30T20:30:00+00:00', 'by': None, 'by_name': 'HR'}})
    item = next(i for i in resume.onboarding_items if i['key'] == 'id_card')
    assert timezone.localtime(item['at']).date().isoformat() == '2026-10-01'


@pytest.mark.django_db
def test_the_api_answers_a_bad_job_filter_with_an_empty_list(authenticated_client):
    response = authenticated_client.get('/api/resumes/?job=abc')
    assert response.status_code == 200


@pytest.mark.django_db
def test_ticking_the_last_checklist_item_unlocks_onboarded_without_a_reload(authenticated_client, sample_job):
    done = {key: {'at': timezone.now().isoformat(), 'by': None, 'by_name': 'HR'}
            for key, _ in Resume.ONBOARDING_CHECKLIST[:-1]}
    resume = Resume.objects.create(job=sample_job, candidate_name='Last Item', recruiter_status='pre_onboarding',
                                   screening_status='completed', verification_status='completed',
                                   onboarding_checklist=done)
    last = Resume.ONBOARDING_CHECKLIST[-1][0]

    html = authenticated_client.post(reverse('core:resume_onboarding_toggle', kwargs={'uuid': resume.uuid}),
                                     {'item': last}, HTTP_HX_REQUEST='true').content.decode()

    control = html[html.index('id="rs-status-card"'):]
    assert 'hx-swap-oob="true"' in control[:80]
    onboarded = control[control.index('value="hired"'):][:300]
    assert 'disabled' not in onboarded


@pytest.mark.django_db
def test_correcting_a_candidates_email_closes_the_links_sent_to_the_old_one(authenticated_client, sample_job):
    from apps.core.forms import ResumeEditForm
    from apps.employee_form.models import EmployeeForm
    from apps.sei_assessment.models import AssessmentInvitation
    resume = Resume.objects.create(job=sample_job, candidate_name='Typo Email', email='tpyo@example.com',
                                   screening_status='completed')
    form = EmployeeForm.objects.create(resume=resume, otp_verified_at=timezone.now())
    invitation = AssessmentInvitation.objects.create(resume=resume, otp_verified_at=timezone.now(),
                                                     token_expires_at=timezone.now() + timedelta(days=3))
    old_tokens = form.token, invitation.token

    authenticated_client.post(reverse('core:resume_edit', kwargs={'uuid': resume.uuid}), {
        'candidate_name': 'Typo Email', 'email': 'typo@example.com',
        'scores_seen': ResumeEditForm.score_signature(resume)})

    form.refresh_from_db()
    invitation.refresh_from_db()
    assert (form.token, invitation.token) != old_tokens
    assert form.otp_verified_at is None and invitation.otp_verified_at is None
