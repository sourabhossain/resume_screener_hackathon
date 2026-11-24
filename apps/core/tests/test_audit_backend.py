"""Backend regressions found by the November 2026 audit (each failed before its fix)."""
import json
from unittest import mock

import pytest
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone

from apps.core.models import Job, Resume, StatusChange
from apps.employee_form.tests.test_submission import STEP_DATA, _walk, candidate, verified  # noqa: F401


def _move(client, resume, status):
    return client.post(reverse('core:resume_status_update', kwargs={'uuid': resume.uuid}),
                       {'recruiter_status': status, 'context': 'card'}, HTTP_HX_REQUEST='true')


def _toast(response):
    return json.loads(response['HX-Trigger']).get('toast')


@pytest.mark.django_db
def test_r1_deleting_a_user_hard_deletes_their_jobs_and_candidates(user, sample_job):
    r = Resume.objects.create(job=sample_job, candidate_name='Keep Me', email='k@example.com')
    StatusChange.objects.create(resume=r, from_status='new', to_status='shortlisted')
    user.delete()
    print('jobs left', Job.all_objects.filter(pk=sample_job.pk).count(),
          'resumes left', Resume.all_objects.filter(pk=r.pk).count())
    assert Job.all_objects.filter(pk=sample_job.pk).exists(), 'job was hard-deleted with its owner'
    assert Resume.all_objects.filter(pk=r.pk).exists(), 'candidate was hard-deleted with job owner'


@pytest.mark.django_db
def test_r2_back_to_assessment_after_rejection_reports_sent_but_link_is_dead(authenticated_client, sample_job):
    sample_job.assessments = ['pe']
    sample_job.save(update_fields=['assessments'])
    r = Resume.objects.create(job=sample_job, candidate_name='Mahin', email='mahin@example.com',
                              screening_status='completed', verification_status='completed')
    first = _move(authenticated_client, r, 'assessment')
    print('first toast', _toast(first))
    sent_before = len(mail.outbox)
    _move(authenticated_client, r, 'rejected')
    again = _move(authenticated_client, r, 'assessment')
    inv = r.assessment_invitation
    inv.refresh_from_db()
    print('second toast', _toast(again), 'emails added', len(mail.outbox) - sent_before,
          'link expired', inv.is_expired)
    assert not (_toast(again)['level'] == 'success' and inv.is_expired), (
        'recruiter told "Assessment link sent" while no email went and the link is closed')


@pytest.mark.django_db
def test_r3_stale_step_post_reopens_a_submitted_information_form(verified):
    client, form = verified
    _walk(client, form, stop_before='d7_declaration')
    form.refresh_from_db()
    assert not form.is_submitted

    import apps.employee_form.views as views
    real_prefill = views.pending_prefill

    def submit_meanwhile(resume, answers):
        from apps.employee_form.models import EmployeeForm
        EmployeeForm.objects.filter(pk=form.pk).update(
            is_submitted=True, submitted_at=timezone.now(), current_step='d7_declaration')
        return real_prefill(resume, answers)

    with mock.patch.object(views, 'pending_prefill', side_effect=submit_meanwhile):
        resp = client.post(reverse('employee_form:step', kwargs={'token': form.token, 'step_key': 'section_a'}),
                           STEP_DATA['section_a']())
    form.refresh_from_db()
    print('status', resp.status_code, 'is_submitted after stale POST', form.is_submitted,
          'submitted_at', form.submitted_at, 'current_step', form.current_step)
    assert form.is_submitted, 'a step POST loaded before the submit un-submitted the form'


@pytest.mark.django_db
def test_r4_api_create_accepts_resume_for_closed_and_draft_job(authenticated_client, sample_job, monkeypatch):
    from apps.core import tasks
    monkeypatch.setattr(tasks.screen_resume_task, 'delay', lambda rid: None)
    sample_job.status = 'closed'
    sample_job.save(update_fields=['status'])
    resp = authenticated_client.post('/api/resumes/', {'job': sample_job.pk, 'candidate_name': 'Late Applicant',
                                                       'email': 'late@example.com'})
    print('closed job API create ->', resp.status_code)
    assert resp.status_code == 400


@pytest.mark.django_db
def test_r5_api_patch_file_keeps_old_text_hash_and_scores(authenticated_client, sample_job, monkeypatch):
    from apps.core import tasks
    queued = []
    monkeypatch.setattr(tasks.screen_resume_task, 'delay', lambda rid: queued.append(rid))
    r = Resume.objects.create(job=sample_job, candidate_name='Old CV', email='o@example.com',
                              raw_text='OLD CV TEXT', file_hash='a' * 64, final_score=88,
                              screening_status='completed')
    new = SimpleUploadedFile('new.pdf', b'%PDF-1.4 a completely different cv', content_type='application/pdf')
    resp = authenticated_client.patch(f'/api/resumes/{r.pk}/', {'file': new}, format='multipart')
    if resp.status_code == 415 or resp.status_code == 400:
        from django.test.client import encode_multipart, BOUNDARY, MULTIPART_CONTENT
        new.seek(0)
        resp = authenticated_client.patch(f'/api/resumes/{r.pk}/', encode_multipart(BOUNDARY, {'file': new}),
                                          content_type=MULTIPART_CONTENT)
    r.refresh_from_db()
    print('patch', resp.status_code, 'file', r.file.name, 'raw_text', r.raw_text[:12], 'hash', r.file_hash[:4],
          'score', r.final_score, 'queued', queued)
    assert resp.status_code == 200
    assert r.raw_text != 'OLD CV TEXT' or queued, 'new file attached but old text/score kept and no re-screen'


@pytest.mark.django_db
def test_r6_rescreen_claims_a_row_that_is_pending_a_celery_retry(authenticated_client, sample_job, monkeypatch):
    from apps.core import tasks
    queued = []
    monkeypatch.setattr(tasks.screen_resume_task, 'delay', lambda rid: queued.append(rid))
    r = Resume.objects.create(job=sample_job, candidate_name='Retrying', email='r@example.com',
                              screening_status='pending')
    authenticated_client.post(reverse('core:resume_rescreen', kwargs={'uuid': r.uuid}), HTTP_HX_REQUEST='true')
    print('queued while a retry is already scheduled:', queued)
    assert queued == []


@pytest.mark.django_db
def test_r7_superscript_digits_crash_poll_and_api(authenticated_client, sample_job):
    r = Resume.objects.create(job=sample_job, candidate_name='Poll', email='p@example.com')
    codes = {}
    for url in (reverse('core:pipeline_poll', kwargs={'job_slug': sample_job.slug}) + f'?ids={r.pk}:%C2%B2',
                reverse('core:resume_row_fragment', kwargs={'uuid': r.uuid}) + '?rank=%C2%B2',
                '/api/resumes/?job=%C2%B2'):
        try:
            codes[url] = authenticated_client.get(url).status_code
        except Exception as exc:
            codes[url] = type(exc).__name__
    print(codes)
    assert all(c in (200, 400, 404) for c in codes.values())


@pytest.mark.django_db
def test_r8_bangla_digit_otp_is_rejected_and_costs_an_attempt(client, sample_job):
    from apps.sei_assessment.models import AssessmentInvitation
    r = Resume.objects.create(job=sample_job, candidate_name='Otp', email='o@example.com')
    inv = AssessmentInvitation.objects.create(resume=r)
    otp = inv.issue_otp()
    inv.save()
    bangla = otp.translate(str.maketrans('0123456789', '০১২৩৪৫৬৭৮৯'))
    ok = inv.check_otp(bangla)
    inv.refresh_from_db()
    print('otp', otp, 'typed', bangla, 'accepted', ok, 'attempts', inv.otp_attempts)
    assert ok


@pytest.mark.django_db
def test_r9_resume_edit_full_save_undoes_concurrent_auto_advance(authenticated_client, sample_job):
    from apps.core import forms as core_forms
    r = Resume.objects.create(job=sample_job, candidate_name='Edit Me', email='e@example.com',
                              recruiter_status='selected', screening_status='completed', final_score=70)
    real = core_forms.ResumeEditForm.is_valid

    def concurrent(self):
        Resume.objects.filter(pk=r.pk).update(recruiter_status='info_received')
        StatusChange.objects.create(resume=r, from_status='selected', to_status='info_received', source='auto')
        return real(self)

    with mock.patch.object(core_forms.ResumeEditForm, 'is_valid', concurrent):
        authenticated_client.post(reverse('core:resume_edit', kwargs={'uuid': r.uuid}), {
            'candidate_name': 'Edit Me', 'email': 'e@example.com', 'phone': '',
            'final_score': '70', 'scores_seen': core_forms.ResumeEditForm.score_signature(r)})
    r.refresh_from_db()
    print('status after edit', r.recruiter_status, 'last history', r.status_changes.first())
    assert r.recruiter_status == 'info_received'


@pytest.mark.django_db
def test_r10_interview_double_submit_books_phase_twice(authenticated_client, sample_job, django_user_model, monkeypatch):
    monkeypatch.setattr('django.db.transaction.on_commit', lambda fn, *a, **k: fn())
    from datetime import timedelta
    from apps.interviews import forms as iv_forms
    from apps.interviews.models import Interview
    panel = django_user_model.objects.create_user('p1', email='p1@sslwireless.com', password='x')
    r = Resume.objects.create(job=sample_job, candidate_name='nadia', email='nadia@example.com',
                              recruiter_status='assessment')
    day = (timezone.localdate() + timedelta(days=3))
    real = iv_forms.InterviewCreateForm.is_valid

    def other_click_commits_first(self):
        Interview.objects.create(resume=r, phase='1', scheduled_date=day, location='Room 3')
        return real(self)

    with mock.patch.object(iv_forms.InterviewCreateForm, 'is_valid', other_click_commits_first):
        authenticated_client.post(reverse('interviews:create', kwargs={'resume_uuid': r.uuid}), {
            'phase': '1', 'scheduled_date': day.isoformat(), 'scheduled_time': '10:00', 'duration_minutes': '60',
            'mode': 'in_person', 'location': 'Room 3', 'notify_candidate': 'on', 'evaluators': [panel.pk]})
    n = Interview.objects.filter(resume=r, phase='1').count()
    print('phase-1 interviews', n, 'emails', len(mail.outbox))
    assert n == 1


@pytest.mark.django_db
def test_r11_sweep_fails_a_resume_that_is_being_screened_after_a_queue_wait(sample_job):
    from datetime import timedelta
    from apps.core.services.resume_service import ResumeService
    from apps.core.tasks import release_stale_screenings
    r = Resume.objects.create(job=sample_job, candidate_name='Queued', email='q@example.com',
                              raw_text='Python developer with Django experience ' * 5, screening_status='processing')
    Resume.objects.filter(pk=r.pk).update(updated_at=timezone.now() - timedelta(minutes=29, seconds=50))
    seen = {}

    def slow_llm(resume):
        Resume.objects.filter(pk=r.pk).update(updated_at=timezone.now() - timedelta(minutes=31)) if False else None
        seen['released'] = release_stale_screenings.run()
        seen['status_mid_run'] = Resume.objects.get(pk=r.pk).screening_status
        raise RuntimeError('stop here')

    r = Resume.objects.get(pk=r.pk)
    with mock.patch.object(ResumeService, 'run_screening', side_effect=slow_llm), \
         mock.patch('apps.core.services.screening_queue.timezone.now',
                    return_value=timezone.now() + timedelta(seconds=30)):
        ResumeService.process_resume(r)
    print(seen)
    assert seen['status_mid_run'] == 'processing', 'row being screened right now was marked failed as "lost"'


@pytest.mark.django_db
def test_ai_contact_details_are_checked_before_they_are_stored(sample_job):
    from apps.core.services.resume_service import ResumeService
    r = Resume.objects.create(job=sample_job, candidate_name='Contact Case', screening_status='processing')
    result = {'candidate_email': 'not an email', 'candidate_phone': '+8801711000000 / +8801811000000',
              'final_score': 70, 'tier': 'mid', 'recommendation': 'talent_pool'}
    ResumeService.apply_screening_result(r, result)
    r.refresh_from_db()
    assert r.email == '' and len(r.phone) <= 20 and r.phone.startswith('+8801711000000')


@pytest.mark.django_db
def test_back_to_assessment_while_the_link_is_open_says_so_and_sends_nothing(authenticated_client, sample_job):
    sample_job.assessments = ['pe']
    sample_job.save(update_fields=['assessments'])
    r = Resume.objects.create(job=sample_job, candidate_name='Open Link', email='open@example.com',
                              screening_status='completed', verification_status='completed')
    _move(authenticated_client, r, 'assessment')
    from apps.sei_assessment.models import AssessmentInvitation
    AssessmentInvitation.objects.filter(resume=r).update(invited_at=timezone.now())
    _move(authenticated_client, r, 'interviewing')
    sent_before = len(mail.outbox)
    again = _move(authenticated_client, r, 'assessment')
    toast = _toast(again)
    assert toast['level'] == 'info' and 'already sent' in str(toast), toast
    assert len(mail.outbox) == sent_before


@pytest.mark.django_db
def test_deleting_a_candidate_cancels_their_interviews_and_closes_links(authenticated_client, sample_job):
    import datetime

    from apps.employee_form.models import EmployeeForm
    from apps.interviews.models import Interview
    r = Resume.objects.create(job=sample_job, candidate_name='Leaving', email='leaving@example.com')
    iv = Interview.objects.create(resume=r, scheduled_date=datetime.date.today() + datetime.timedelta(days=2),
                                  scheduled_time=datetime.time(10, 0))
    form = EmployeeForm.objects.create(resume=r)
    authenticated_client.post(reverse('core:resume_delete', kwargs={'uuid': r.uuid}))
    iv.refresh_from_db()
    form.refresh_from_db()
    assert iv.status == Interview.CANCELLED and form.is_expired


@pytest.mark.django_db
def test_a_rejected_candidate_is_not_emailed_an_interview_invite(sample_job):
    import datetime

    from apps.interviews.models import Interview
    from apps.interviews.tasks import send_candidate_invite
    r = Resume.objects.create(job=sample_job, candidate_name='Out', email='out@example.com', recruiter_status='rejected')
    iv = Interview.objects.create(resume=r, scheduled_date=datetime.date.today() + datetime.timedelta(days=2),
                                  scheduled_time=datetime.time(10, 0))
    sent_before = len(mail.outbox)
    assert send_candidate_invite(iv.pk) == 'closed' and len(mail.outbox) == sent_before


@pytest.mark.django_db
def test_a_failed_reminder_is_tried_again_by_the_next_run(sample_job, django_user_model):
    import datetime

    from apps.interviews import notifications, tasks
    from apps.interviews.models import Interview, InterviewEvaluation
    staff = django_user_model.objects.create_user('panel', email='panel@example.com', is_staff=True)
    r = Resume.objects.create(job=sample_job, candidate_name='Tomorrow', email='t@example.com')
    iv = Interview.objects.create(resume=r, scheduled_date=timezone.localdate() + datetime.timedelta(days=1),
                                  scheduled_time=datetime.time(10, 0))
    ev = InterviewEvaluation.objects.create(interview=iv, evaluator=staff, interviewer_name='Panel',
                                            interviewer_email='panel@example.com', invited_at=timezone.now())
    with mock.patch.object(notifications, 'send_evaluator_email', side_effect=OSError('smtp down')):
        tasks.send_interview_reminders()
    ev.refresh_from_db()
    assert ev.reminded_at is None and 'smtp down' in ev.invite_error
    tasks.send_interview_reminders()
    ev.refresh_from_db()
    assert ev.reminded_at is not None
