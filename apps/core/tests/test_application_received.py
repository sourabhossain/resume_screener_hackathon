"""A candidate who applies on the careers page gets one thank-you email."""
from unittest.mock import patch

import pytest
from django.core import mail
from django.urls import reverse

from apps.core.models import Resume
from apps.core.tests.test_careers import _fake_pdf, _post_apply


@pytest.mark.django_db
def test_applying_sends_one_thank_you_email(client, sample_job, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        assert _post_apply(client, sample_job).status_code == 302

    assert len(mail.outbox) == 1
    message = mail.outbox[0]
    assert message.to == ['ali@example.com'] and message.reply_to == ['jobs@sslwireless.com']
    assert message.subject == f'Thank you for applying for {sample_job.title} at SSL Wireless'
    assert 'Dear Ali Hassan' in message.body and sample_job.title in message.body
    assert sample_job.title in message.alternatives[0][0]


@pytest.mark.django_db
def test_the_email_goes_once_even_if_queued_twice(client, sample_job, django_capture_on_commit_callbacks):
    from apps.core.tasks import send_application_received_email
    with django_capture_on_commit_callbacks(execute=True):
        _post_apply(client, sample_job)
    resume = Resume.objects.get(email='ali@example.com')
    assert send_application_received_email(resume.pk) == 'already_sent'
    assert len(mail.outbox) == 1


@pytest.mark.django_db
def test_a_broker_outage_still_takes_the_application(client, sample_job, django_capture_on_commit_callbacks):
    with patch('apps.core.tasks.send_application_received_email.delay', side_effect=ConnectionError('down')) as delay, \
            django_capture_on_commit_callbacks(execute=True):
        response = _post_apply(client, sample_job)
    delay.assert_called_once()
    assert response.status_code == 302 and Resume.objects.filter(email='ali@example.com').exists()
    assert mail.outbox == []


@pytest.mark.django_db
def test_a_rejected_application_sends_nothing(client, sample_job, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        _post_apply(client, sample_job)
    mail.outbox.clear()
    with django_capture_on_commit_callbacks(execute=True):
        response = _post_apply(client, sample_job, {'candidate_name': 'Ali Again'})
    assert response.status_code == 200 and mail.outbox == []


@pytest.mark.django_db
def test_cvs_added_by_hr_get_no_thank_you(authenticated_client, sample_job, django_capture_on_commit_callbacks):
    with patch('apps.core.tasks.screen_resume_task.delay'), django_capture_on_commit_callbacks(execute=True):
        authenticated_client.post(reverse('core:resume_create', kwargs={'job_slug': sample_job.slug}),
                                  {'candidate_name': 'Added By HR', 'email': 'hr-added@example.com', 'file': _fake_pdf()})
    assert Resume.objects.filter(email='hr-added@example.com').exists()
    assert mail.outbox == []
