"""Regressions for the gaps found in the full-system review before go-live."""
from datetime import timedelta
from unittest import mock

import pytest
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.core.models import Job, Resume

PDF = b'%PDF-1.4 test file'


def _pdf(name='cv.pdf', body=PDF):
    return SimpleUploadedFile(name, body, content_type='application/pdf')


# ── screening that never comes back ──────────────────────────────────────
@pytest.mark.django_db
def test_a_broker_outage_marks_the_application_failed_not_a_server_error(client, sample_job):
    with mock.patch('apps.core.tasks.screen_resume_task.delay', side_effect=ConnectionError('redis down')):
        response = client.post(reverse('core:careers_apply', kwargs={'slug': sample_job.slug}), {
            'candidate_name': 'Rafiq Ahmed', 'email': 'rafiq@example.com',
            'phone': '+8801711000000', 'file': _pdf()})

    resume = Resume.objects.get(email='rafiq@example.com')
    assert response.status_code == 302
    assert resume.screening_status == 'failed'


@pytest.mark.django_db
def test_a_lost_screening_is_released_for_a_re_run(sample_job):
    from apps.core.tasks import release_stale_screenings
    stuck = Resume.objects.create(job=sample_job, candidate_name='Stuck', screening_status='processing')
    fresh = Resume.objects.create(job=sample_job, candidate_name='Fresh', screening_status='processing')
    Resume.objects.filter(pk=stuck.pk).update(updated_at=timezone.now() - timedelta(hours=1))

    assert release_stale_screenings()['released'] == 1

    stuck.refresh_from_db(); fresh.refresh_from_db()
    assert stuck.screening_status == 'failed'
    assert fresh.screening_status == 'processing'


@pytest.mark.django_db
def test_a_stale_processing_row_can_be_re_screened(authenticated_client, sample_job):
    stuck = Resume.objects.create(job=sample_job, candidate_name='Stuck', screening_status='processing')
    Resume.objects.filter(pk=stuck.pk).update(updated_at=timezone.now() - timedelta(hours=1))

    with mock.patch('apps.core.tasks.screen_resume_task.delay') as delay:
        authenticated_client.post(reverse('core:resume_rescreen', kwargs={'uuid': stuck.uuid}))

    delay.assert_called_once_with(stuck.id)


@pytest.mark.django_db
def test_bulk_re_screen_queues_each_row_once(authenticated_client, sample_job):
    failed = Resume.objects.create(job=sample_job, candidate_name='F', screening_status='failed')

    with mock.patch('apps.core.tasks.screen_resume_task.delay') as delay:
        authenticated_client.post(reverse('core:screening_rescreen_bulk'), {'scope': 'all'})
        authenticated_client.post(reverse('core:screening_rescreen_bulk'), {'scope': 'all'})

    assert delay.call_count == 1
    failed.refresh_from_db()
    assert failed.screening_status == 'processing'


def test_a_model_outage_is_a_failure_not_a_review_request():
    from apps.core.services import ai_screener
    with mock.patch.object(ai_screener, 'detect_job_type_with_reason',
                           side_effect=ai_screener.JobTypeDetectionError('boom')):
        result = ai_screener.screen_resume('text', 'Job description', resume_id=1, job_type='')
    assert result['error'] and not result.get('needs_review')


# ── what the AI may overwrite ────────────────────────────────────────────
@pytest.mark.django_db
def test_the_model_does_not_replace_a_name_the_candidate_typed(sample_job):
    from apps.core.services.resume_service import ResumeService
    resume = Resume.objects.create(job=sample_job, candidate_name='Nusrat Jahan', file_name='cv.pdf')
    with mock.patch('apps.core.tasks.verify_resume_links_task.delay'):
        ResumeService.apply_screening_result(resume, {'candidate_name': 'Unknown', 'final_score': 70})
    resume.refresh_from_db()
    assert resume.candidate_name == 'Nusrat Jahan'


@pytest.mark.django_db
def test_the_model_fills_a_name_guessed_from_the_file_name(sample_job):
    from apps.core.services.resume_service import ResumeService
    resume = Resume.objects.create(job=sample_job, candidate_name='cv final 2024', file_name='cv_final-2024.pdf')
    with mock.patch('apps.core.tasks.verify_resume_links_task.delay'):
        ResumeService.apply_screening_result(resume, {'candidate_name': 'Tanvir Hasan', 'final_score': 70})
    resume.refresh_from_db()
    assert resume.candidate_name == 'Tanvir Hasan'


@pytest.mark.django_db
def test_a_formula_from_the_model_is_never_stored_as_a_name(sample_job):
    from apps.core.services.resume_service import ResumeService
    resume = Resume.objects.create(job=sample_job, candidate_name='', file_name='x.pdf')
    with mock.patch('apps.core.tasks.verify_resume_links_task.delay'):
        ResumeService.apply_screening_result(resume, {'candidate_name': '=HYPERLINK("x")', 'final_score': 70})
    resume.refresh_from_db()
    assert not resume.candidate_name.startswith('=')


@pytest.mark.django_db
def test_a_re_screen_clears_the_manual_edit_mark_and_review_clears_the_score(sample_job):
    from apps.core.services.resume_service import ResumeService
    resume = Resume.objects.create(job=sample_job, candidate_name='A', final_score=90,
                                   score_manually_edited=True)
    ResumeService.apply_screening_result(resume, {'needs_review': True, 'reasoning': 'unclear'})
    resume.refresh_from_db()
    assert resume.final_score is None and resume.recommendation == ''

    with mock.patch('apps.core.tasks.verify_resume_links_task.delay'):
        ResumeService.apply_screening_result(resume, {'final_score': 65})
    resume.refresh_from_db()
    assert resume.score_manually_edited is False


# ── public pages ─────────────────────────────────────────────────────────
@pytest.mark.django_db
@pytest.mark.parametrize('href', ['\x01javascript:alert(1)', ' javascript:alert(1)',
                                  '​javascript:alert(1)', '//evil.example', 'data:text/html,x'])
def test_job_description_links_only_allow_safe_schemes(href):
    from apps.core.templatetags.md import markdown
    html = str(markdown(f'# Role\n[apply]({href})'))
    assert 'href="#"' in html


def test_ordinary_links_in_a_job_description_survive():
    from apps.core.templatetags.md import markdown
    html = str(markdown('# Role\n[apply](https://sslwireless.com/careers) or [mail](mailto:jobs@sslwireless.com)'))
    assert 'href="https://sslwireless.com/careers"' in html
    assert 'href="mailto:jobs@sslwireless.com"' in html


@pytest.mark.django_db
def test_a_draft_title_is_not_shown_on_the_public_thank_you_page(client, user):
    draft = Job.objects.create(owner=user, title='Secret Draft Role', status='draft')
    assert client.get(reverse('core:careers_thanks', kwargs={'slug': draft.slug})).status_code == 404


@pytest.mark.django_db
def test_a_job_past_its_closing_date_leaves_the_public_list(client, user):
    Job.objects.create(owner=user, title='Old Role', status='active',
                       closing_date=timezone.localdate() - timedelta(days=1))
    assert 'Old Role' not in client.get(reverse('core:careers')).content.decode()


@pytest.mark.django_db
def test_the_apply_form_carries_a_privacy_notice(client, sample_job):
    html = client.get(reverse('core:careers_apply', kwargs={'slug': sample_job.slug})).content.decode()
    assert 'for recruitment purposes only' in html


# ── deleted jobs and candidates ──────────────────────────────────────────
@pytest.mark.django_db
def test_candidates_of_a_deleted_job_are_gone_from_every_staff_page(authenticated_client, sample_job):
    resume = Resume.objects.create(job=sample_job, candidate_name='Gone', recommendation='talent_pool',
                                   final_score=70)
    sample_job.soft_delete()

    assert authenticated_client.get(reverse('core:resume_detail', kwargs={'uuid': resume.uuid})).status_code == 404
    assert 'Gone' not in authenticated_client.get(reverse('core:talent_pool')).content.decode()
    response = authenticated_client.post(reverse('core:resume_status_update', kwargs={'uuid': resume.uuid}),
                                         {'recruiter_status': 'shortlisted'})
    assert response.status_code == 404


@pytest.mark.django_db
def test_a_deleted_candidates_public_links_stop_working(client, sample_job):
    from apps.employee_form.models import EmployeeForm
    from apps.interviews.models import Interview, InterviewEvaluation
    from apps.reference_checks.models import ReferenceCheck
    resume = Resume.objects.create(job=sample_job, candidate_name='Gone', email='g@example.com')
    form = EmployeeForm.objects.create(resume=resume)
    check = ReferenceCheck.objects.create(resume=resume, kind='employer', source_key='employer_1',
                                          recipient_name='R', recipient_email='r@example.com',
                                          token_expires_at=timezone.now() + timedelta(days=3))
    ev = InterviewEvaluation.objects.create(
        interview=Interview.objects.create(resume=resume, scheduled_date=timezone.localdate()),
        interviewer_name='P', token_expires_at=timezone.now() + timedelta(days=3))
    resume.soft_delete()

    assert client.get(reverse('employee_form:entry', kwargs={'token': form.token})).status_code == 404
    assert client.get(reverse('reference_checks:entry', kwargs={'token': check.token})).status_code == 404
    closed = client.get(reverse('interviews:evaluate', kwargs={'token': ev.token}))
    assert closed.status_code == 410
    assert 'No evaluation is needed' in closed.content.decode()


# ── exports ──────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_the_csv_export_neutralises_formulas_and_uses_local_dates(authenticated_client, sample_job):
    resume = Resume.objects.create(job=sample_job, candidate_name='=cmd', email='@x.com', phone='+8801711')
    # 20:30 UTC is 02:30 the next day in Dhaka.
    Resume.objects.filter(pk=resume.pk).update(
        created_at=timezone.now().replace(hour=20, minute=30, second=0, microsecond=0))
    resume.refresh_from_db()

    response = authenticated_client.get(reverse('core:job_export_csv', kwargs={'slug': sample_job.slug}))
    body = b''.join(response.streaming_content).decode()

    assert "'=cmd" in body and "'@x.com" in body and "'+8801711" in body
    assert timezone.localtime(resume.created_at).strftime('%Y-%m-%d') in body


# ── files, API, accounts ─────────────────────────────────────────────────
@pytest.mark.django_db
def test_replacing_the_cv_file_re_screens_the_new_file(authenticated_client, sample_job):
    resume = Resume.objects.create(job=sample_job, candidate_name='Mitu Das', raw_text='OLD CV TEXT',
                                   file_hash='old', screening_status='completed')
    with mock.patch('apps.core.tasks.screen_resume_task.delay') as delay:
        authenticated_client.post(reverse('core:resume_edit', kwargs={'uuid': resume.uuid}), {
            'candidate_name': 'Mitu Das', 'file': _pdf('new.pdf', PDF + b' new')})

    resume.refresh_from_db()
    assert resume.raw_text == '' and resume.file_hash != 'old'
    delay.assert_called_once_with(resume.id)


@pytest.mark.django_db
def test_a_media_directory_url_is_a_404_not_a_crash(authenticated_client):
    assert authenticated_client.get('/media/resumes/').status_code == 404


@pytest.mark.django_db
def test_the_api_applies_the_upload_checks_and_keeps_scores_read_only(authenticated_client, sample_job):
    bad = SimpleUploadedFile('evil.html', b'<script>x</script>', content_type='text/html')
    response = authenticated_client.post('/api/resumes/', {
        'job': sample_job.pk, 'candidate_name': 'Api Person', 'file': bad})
    assert response.status_code == 400

    resume = Resume.objects.create(job=sample_job, candidate_name='Api Person', final_score=40)
    authenticated_client.patch(f'/api/resumes/{resume.pk}/', {'final_score': 99},
                               content_type='application/json')
    resume.refresh_from_db()
    assert resume.final_score == 40


@pytest.mark.django_db
def test_a_superuser_changing_their_own_password_stays_signed_in(client, django_user_model):
    admin = django_user_model.objects.create_superuser('boss', 'b@example.com', 'Old-pass-123!')
    client.login(username='boss', password='Old-pass-123!')

    client.post(reverse('core:user_change_password', kwargs={'pk': admin.pk}),
                {'new_password1': 'N3w-strong-pass!', 'new_password2': 'N3w-strong-pass!'})

    assert client.get(reverse('core:user_list')).status_code == 200


# ── rate limits behind the proxy ─────────────────────────────────────────
@override_settings(CLIENT_IP_HEADER='HTTP_X_REAL_IP')
def test_rate_limits_key_on_the_visitor_behind_the_proxy():
    from config.client_ip import client_ip
    request = RequestFactory().get('/', REMOTE_ADDR='10.0.0.1', HTTP_X_REAL_IP='203.0.113.9')
    assert client_ip(request) == '203.0.113.9'


@override_settings(CLIENT_IP_HEADER='')
def test_without_a_proxy_header_the_connecting_address_is_used():
    from config.client_ip import client_ip
    request = RequestFactory().get('/', REMOTE_ADDR='198.51.100.7', HTTP_X_REAL_IP='1.2.3.4')
    assert client_ip(request) == '198.51.100.7'


@pytest.mark.django_db
def test_the_admin_login_is_throttled(client, django_user_model):
    django_user_model.objects.create_superuser('root', 'r@example.com', 'Right-pass-123!')
    for _ in range(6):
        response = client.post('/admin/login/', {'username': 'root', 'password': 'wrong'})
    assert response.status_code in (403, 429)


# ── email ────────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_plain_text_emails_are_not_html_escaped(sample_job):
    from apps.employee_form.models import EmployeeForm
    from apps.employee_form.services import send_invite
    resume = Resume.objects.create(job=sample_job, candidate_name="Ayesha O'Neil", email='a@example.com')
    form = EmployeeForm.objects.create(resume=resume)
    mail.outbox = []

    send_invite(form, otp='[PLACEHOLDER]')

    assert "O'Neil" in mail.outbox[0].body
    assert '&#x27;' not in mail.outbox[0].body


@pytest.mark.django_db
def test_the_interview_link_to_copy_uses_the_public_address(authenticated_client, sample_job):
    from apps.interviews.models import Interview, InterviewEvaluation
    resume = Resume.objects.create(job=sample_job, candidate_name='Panel Case')
    interview = Interview.objects.create(resume=resume, scheduled_date=timezone.localdate())
    ev = InterviewEvaluation.objects.create(interview=interview, interviewer_name='P',
                                            token_expires_at=timezone.now() + timedelta(days=3))

    with override_settings(SITE_BASE_URL='https://careers.example.com'):
        html = authenticated_client.get(reverse('interviews:detail', kwargs={'pk': interview.pk})).content.decode()

    # escapejs encodes the token's hyphens for the JS string; the host is what matters.
    assert 'https://careers.example.com/evaluate/' in html
    assert 'http://testserver/evaluate/' not in html
