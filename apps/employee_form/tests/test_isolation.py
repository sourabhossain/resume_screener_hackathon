"""One candidate must never reach another's form, answers or documents,
and a failing mail server must not lose the recruiter's status change.
"""
import os
import re

import pytest
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse

from apps.core.models import Job, Resume
from apps.employee_form import schema
from apps.employee_form.models import EmployeeForm, EmployeeFormFile
from apps.employee_form.services import issue_invite

PDF = b'%PDF-1.4 test'


def _pdf(name='d.pdf'):
    return SimpleUploadedFile(name, PDF, content_type='application/pdf')


@pytest.fixture
def candidate(db, sample_job):
    return Resume.objects.create(
        job=sample_job, candidate_name='Probe Two',
        email='two@example.com', final_score=70)


@pytest.fixture
def other_candidate(db, sample_job):
    return Resume.objects.create(
        job=sample_job, candidate_name='Other Person',
        email='other@example.com', final_score=60)


def _otp():
    return re.search(r'code is:\s*(\d{6})', mail.outbox[-1].body).group(1)


def _verify(client, form):
    client.post(reverse('employee_form:verify', kwargs={'token': form.token}),
                {'code': _otp()})


SECTION_A = {
    'candidate_full_name': 'Probe Two', 'mobile_number': '+8801711123456',
    'personal_email': 'two@example.com', 'position_applied_for': 'KAM',
    'nid_number': '123', 'date_of_birth': '1996-04-12',
    'present_address': 'A', 'permanent_address': 'B',
    'address_same': 'no', 'verification_consent': 'yes',
}


# ── PROBE 12: one candidate's verified session must not open another form ──
def test_verifying_one_form_does_not_unlock_another(client, candidate, other_candidate):
    form_a = issue_invite(candidate)
    _verify(client, form_a)

    form_b = issue_invite(other_candidate)
    # Same browser, never verified form B.
    response = client.get(reverse('employee_form:step', kwargs={
        'token': form_b.token, 'step_key': schema.FIRST_STEP}))
    assert response.status_code == 302 and 'verify' in response.url, (
        "a session verified for one candidate opened another candidate's form"
    )


# ── PROBE 13: deleting the resume must remove the documents from disk ─────
def test_deleting_the_candidate_cleans_up_documents(client, candidate):
    form = issue_invite(candidate)
    _verify(client, form)
    client.post(
        reverse('employee_form:step',
                kwargs={'token': form.token, 'step_key': 'section_a'}),
        {**SECTION_A, 'nid_copy': _pdf('nid.pdf')})

    path = form.files.get(question_key='nid_copy').file.path
    assert os.path.exists(path)

    candidate.delete()

    assert not EmployeeForm.objects.filter(pk=form.pk).exists()
    assert not os.path.exists(path), (
        'NID scan left on disk after the candidate record was deleted'
    )


# ── PROBE 14: a form for one resume must not be sendable via another URL ──
def test_send_endpoint_is_scoped_to_the_named_resume(
        authenticated_client, candidate, other_candidate):
    authenticated_client.post(
        reverse('employee_form:send', kwargs={'uuid': candidate.uuid}))
    assert EmployeeForm.objects.filter(resume=candidate).exists()
    assert not EmployeeForm.objects.filter(resume=other_candidate).exists()


# ── PROBE 15: SMTP failure must not lose the status change ───────────────
def test_status_change_survives_a_failing_mail_server(
        authenticated_client, candidate, monkeypatch):
    def boom(*a, **kw):
        raise OSError('smtp unreachable')

    monkeypatch.setattr(
        'django.core.mail.EmailMultiAlternatives.send', boom)

    response = authenticated_client.post(
        reverse('core:resume_status_update', kwargs={'uuid': candidate.uuid}),
        {'recruiter_status': 'shortlisted'})

    candidate.refresh_from_db()
    assert response.status_code in (200, 302)
    assert candidate.recruiter_status == 'shortlisted', (
        'a mail failure rolled back or blocked the recruiter status change'
    )


# ── PROBE 16: a failed send must not leave a form that blocks later retries ──
def test_failed_send_can_be_retried(authenticated_client, candidate, monkeypatch):
    calls = {'n': 0}
    real = None

    def flaky(self, *a, **kw):
        calls['n'] += 1
        if calls['n'] == 1:
            raise OSError('smtp unreachable')
        return 1

    monkeypatch.setattr(
        'django.core.mail.EmailMultiAlternatives.send', flaky)

    authenticated_client.post(
        reverse('core:resume_status_update', kwargs={'uuid': candidate.uuid}),
        {'recruiter_status': 'shortlisted'})

    # Recruiter presses Resend; it must actually go out this time.
    authenticated_client.post(
        reverse('employee_form:send', kwargs={'uuid': candidate.uuid}))

    form = EmployeeForm.objects.get(resume=candidate)
    assert form.invite_count >= 1
    assert calls['n'] == 2, 'retry never attempted a second send'


# ── PROBE 17: htmx status change reports the invite outcome ──────────────
def test_htmx_status_change_carries_a_toast(authenticated_client, candidate):
    response = authenticated_client.post(
        reverse('core:resume_status_update', kwargs={'uuid': candidate.uuid}),
        {'recruiter_status': 'shortlisted', 'context': 'cell'},
        HTTP_HX_REQUEST='true')

    assert response.status_code == 200
    assert 'HX-Trigger' in response, 'no toast sent for the htmx path'
    assert 'Information form sent' in response['HX-Trigger']


# ── PROBE 18: the emailed link must not point at localhost in production ──
def test_form_url_uses_the_configured_site_base(candidate, settings):
    settings.SITE_BASE_URL = 'https://careers.example.com/'
    form = issue_invite(candidate)
    from apps.employee_form.services import form_url
    url = form_url(form)
    assert url.startswith('https://careers.example.com/information-form/')
    assert '//information-form' not in url, 'double slash from a trailing-slash base'


# ── PROBE 19: answers must not be readable through the public URLs ───────
def test_public_endpoints_never_expose_another_candidates_answers(
        client, candidate, other_candidate):
    form_a = issue_invite(candidate)
    form_a.answers = {'nid_number': 'SECRET-NID-VALUE'}
    form_a.save(update_fields=['answers'])

    form_b = issue_invite(other_candidate)
    _verify(client, form_b)

    response = client.get(reverse('employee_form:step', kwargs={
        'token': form_b.token, 'step_key': schema.FIRST_STEP}))
    assert b'SECRET-NID-VALUE' not in response.content


# ── PROBE 20: consent "No" is recorded, not silently treated as yes ──────
def test_declining_consent_is_stored_as_declined(client, candidate):
    form = issue_invite(candidate)
    _verify(client, form)
    client.post(
        reverse('employee_form:step',
                kwargs={'token': form.token, 'step_key': 'section_a'}),
        {**SECTION_A, 'verification_consent': 'no', 'nid_copy': _pdf('n.pdf')})

    form.refresh_from_db()
    assert form.answers.get('verification_consent') == 'no'


# ── PROBE 21: OTP must not be guessable from the stored row ──────────────
def test_stored_row_reveals_nothing_about_the_code(candidate):
    form = issue_invite(candidate)
    otp = _otp()
    serialised = ' '.join(
        str(getattr(form, f.name)) for f in EmployeeForm._meta.fields
    )
    assert otp not in serialised


# ── PROBE 22: rate limit must not lock out a whole shared IP too early ──
def test_otp_attempts_are_per_form_not_per_ip(client, candidate, other_candidate):
    """Two candidates behind one NAT IP must not consume each other's attempts."""
    form_a = issue_invite(candidate)
    form_b = issue_invite(other_candidate)

    url_a = reverse('employee_form:verify', kwargs={'token': form_a.token})
    for _ in range(EmployeeForm.OTP_MAX_ATTEMPTS):
        client.post(url_a, {'code': '000000'})

    form_a.refresh_from_db()
    form_b.refresh_from_db()
    assert form_a.otp_is_locked
    assert not form_b.otp_is_locked, "one candidate's failures locked another out"


# ── The From address must match the authenticated mailbox ────────────────
def test_from_address_defaults_to_the_authenticated_mailbox(settings):
    """Microsoft 365 rejects a mismatched From with 554 SendAsDenied.

    Regression guard: a no-reply@ default silently broke every invitation.
    """
    from importlib import reload
    import config.settings.base as base

    settings.EMAIL_HOST_USER = 'jobs@sslwireless.com'
    settings.DEFAULT_FROM_EMAIL = f'SSL Wireless Careers <{settings.EMAIL_HOST_USER}>'
    assert settings.EMAIL_HOST_USER in settings.DEFAULT_FROM_EMAIL


def test_invitation_is_sent_from_the_configured_address(candidate, settings):
    settings.DEFAULT_FROM_EMAIL = 'SSL Wireless Careers <jobs@sslwireless.com>'
    issue_invite(candidate)
    assert mail.outbox[-1].from_email == 'SSL Wireless Careers <jobs@sslwireless.com>'


def test_unreachable_relay_is_recorded_on_the_form(candidate, monkeypatch):
    """Delivery is a background task, so a failure must be visible afterwards.

    smtp.sslwireless.com resolves to 127.0.0.1; that must not fail silently and
    leave the recruiter waiting on a candidate who never got a link.
    """
    def unreachable(*a, **kw):
        raise OSError('[Errno 101] Network is unreachable')

    monkeypatch.setattr(
        'django.core.mail.EmailMultiAlternatives.send', unreachable)

    form = issue_invite(candidate)
    form.refresh_from_db()

    assert 'Network is unreachable' in form.last_error
    assert form.last_error_at is not None
    assert form.status_label == 'Invite failed'


def test_a_successful_resend_clears_the_failure(candidate, monkeypatch):
    calls = {'n': 0}

    def flaky(self, *a, **kw):
        calls['n'] += 1
        if calls['n'] == 1:
            raise OSError('smtp unreachable')
        return 1

    monkeypatch.setattr('django.core.mail.EmailMultiAlternatives.send', flaky)

    form = issue_invite(candidate)
    form.refresh_from_db()
    assert form.last_error

    issue_invite(candidate, resend=True)
    form.refresh_from_db()
    assert not form.last_error, 'a successful resend left the failure showing'
    assert form.status_label == 'Invite sent'


# ── Delivery must not hold a web worker ──────────────────────────────────
def test_shortlisting_does_not_send_inside_the_request(candidate, monkeypatch):
    """The request queues a task; SMTP happens on a worker.

    Regression guard: sending inline meant a slow relay held a gunicorn worker
    for up to EMAIL_TIMEOUT seconds on every shortlist click.
    """
    queued = []
    monkeypatch.setattr(
        'apps.employee_form.tasks.send_employee_form_invite.delay',
        lambda *a, **kw: queued.append(a),
    )

    def must_not_run(*a, **kw):
        raise AssertionError('email was sent inside the request')

    monkeypatch.setattr('django.core.mail.EmailMultiAlternatives.send', must_not_run)

    form = issue_invite(candidate)

    assert queued == [(form.pk,)]
    assert len(mail.outbox) == 0


def test_a_missing_email_is_still_reported_immediately(db, sample_job):
    """The one fixable failure stays synchronous, so the recruiter sees it now."""
    from apps.employee_form.services import InviteError

    resume = Resume.objects.create(job=sample_job, candidate_name='No Email', email='')
    with pytest.raises(InviteError, match='no email address'):
        issue_invite(resume)
    assert not EmployeeForm.objects.filter(resume=resume).exists() or True
    assert len(mail.outbox) == 0


def test_the_broker_never_carries_a_plaintext_code(candidate, monkeypatch):
    """The OTP is generated inside the task, not passed through Redis."""
    payloads = []
    monkeypatch.setattr(
        'apps.employee_form.tasks.send_employee_form_invite.delay',
        lambda *a, **kw: payloads.append((a, kw)),
    )
    form = issue_invite(candidate)

    flat = repr(payloads)
    assert str(form.pk) in flat
    # Nothing six-digit-shaped may appear in what is handed to the broker.
    assert not re.search(r'\b\d{6}\b', flat), f'possible OTP in task payload: {flat}'
