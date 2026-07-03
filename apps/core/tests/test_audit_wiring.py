"""One test per instrumented flow, asserting the expected AuditLog row is written.

Screening runs eagerly in tests (CELERY_TASK_ALWAYS_EAGER), so upload flows patch
screen_resume_task.delay to keep the LLM/network out of the assertion.
"""
import json
from datetime import date, timedelta
from unittest.mock import patch

import pytest
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.core.models import AuditLog, Job, Resume
from apps.core.services.resume_service import ResumeService


def _rows(action, entity_id=None):
    qs = AuditLog.objects.filter(action=action)
    if entity_id is not None:
        qs = qs.filter(entity_id=str(entity_id))
    return qs


@pytest.fixture
def superuser_client(client, django_user_model):
    django_user_model.objects.create_superuser(
        username='root', email='root@example.com', password='rootpass123'
    )
    client.login(username='root', password='rootpass123')
    return client


# --------------------------------------------------------------------------- jobs
@pytest.mark.django_db
class TestJobFlows:
    def test_job_create_logs(self, authenticated_client, user):
        authenticated_client.post(reverse('core:job_create'), {
            'title': 'Data Engineer', 'description': 'Build pipelines', 'status': 'active',
        })
        row = _rows('job.created').get()
        assert row.actor == user
        assert row.entity_type == 'job'

    def test_job_edit_logs(self, authenticated_client, sample_job):
        authenticated_client.post(reverse('core:job_edit', kwargs={'slug': sample_job.slug}), {
            'title': 'Updated Title', 'description': sample_job.description, 'status': 'active',
        })
        assert _rows('job.updated', sample_job.slug).exists()

    def test_job_delete_logs(self, authenticated_client, sample_job):
        authenticated_client.post(reverse('core:job_delete', kwargs={'slug': sample_job.slug}))
        assert _rows('job.deleted', sample_job.slug).exists()

    def test_job_auto_closed_logs_with_no_actor(self, user):
        from apps.core.tasks import close_expired_jobs
        job = Job.objects.create(
            owner=user, title='Expired', description='x', status='active',
            closing_date=date.today() - timedelta(days=1),
        )
        close_expired_jobs()
        row = _rows('job.auto_closed', job.slug).get()
        assert row.actor is None


# ------------------------------------------------------------------------- resumes
@pytest.mark.django_db
class TestResumeFlows:
    def test_upload_single_logs(self, authenticated_client, sample_job):
        with patch('apps.core.tasks.screen_resume_task.delay'):
            authenticated_client.post(
                reverse('core:resume_create', kwargs={'job_slug': sample_job.slug}),
                {'candidate_name': 'Ada Lovelace', 'file': SimpleUploadedFile(
                    'cv.pdf', b'%PDF-1.4 minimal', content_type='application/pdf')},
            )
        assert _rows('resume.uploaded').filter(entity_type='resume').exists()

    def test_public_apply_logs_with_no_actor(self, client, sample_job):
        with patch('apps.core.tasks.screen_resume_task.delay'):
            client.post(reverse('core:careers_apply', kwargs={'slug': sample_job.slug}), {
                'candidate_name': 'Grace Hopper', 'email': 'grace@example.com',
                'phone': '+8801711111111',
                'file': SimpleUploadedFile('cv.pdf', b'%PDF-1.4 minimal',
                                           content_type='application/pdf'),
            })
        row = _rows('resume.uploaded').filter(entity_type='resume').first()
        assert row is not None
        assert row.actor is None

    def test_delete_logs(self, authenticated_client, sample_resume):
        authenticated_client.post(reverse('core:resume_delete', kwargs={'uuid': sample_resume.uuid}))
        assert _rows('resume.deleted', sample_resume.uuid).exists()

    def test_rescreen_single_logs(self, authenticated_client, sample_resume):
        sample_resume.screening_status = 'completed'
        sample_resume.save(update_fields=['screening_status'])
        with patch('apps.core.tasks.screen_resume_task.delay'):
            authenticated_client.post(reverse('core:resume_rescreen', kwargs={'uuid': sample_resume.uuid}))
        assert _rows('resume.rescreen_requested', sample_resume.uuid).exists()

    def test_bulk_rescreen_logs(self, authenticated_client, sample_resume):
        sample_resume.screening_status = 'failed'
        sample_resume.save(update_fields=['screening_status'])
        with patch('apps.core.tasks.screen_resume_task.delay'):
            authenticated_client.post(reverse('core:screening_rescreen_bulk'),
                                      {'scope': 'all'})
        assert _rows('resume.rescreen_requested', sample_resume.uuid).exists()

    def test_recruiter_status_change_logs(self, authenticated_client, sample_resume):
        status = Resume.RECRUITER_STATUS_CHOICES[0][0]
        authenticated_client.post(
            reverse('core:resume_status_update', kwargs={'uuid': sample_resume.uuid}),
            {'recruiter_status': status},
        )
        assert _rows('resume.recruiter_status_changed', sample_resume.uuid).exists()


# ---------------------------------------------------------------- score override
@pytest.mark.django_db
class TestScoreOverride:
    def _post(self, client, resume, extra):
        # Mirror the instance's current values so only `extra` counts as changed.
        data = {
            'candidate_name': resume.candidate_name,
            'experience_score': resume.experience_score,
            'education_score': resume.education_score,
            'skills_score': resume.skills_score,
            'certification_score': resume.certification_score or '',
            'achievement_score': resume.achievement_score or '',
            'final_score': resume.final_score,
        }
        data.update(extra)
        return client.post(reverse('core:resume_edit', kwargs={'uuid': resume.uuid}), data)

    def test_score_change_without_reason_rejected(self, authenticated_client, sample_resume):
        resp = self._post(authenticated_client, sample_resume, {'final_score': 42})
        assert resp.status_code == 200  # re-render, not redirect
        sample_resume.refresh_from_db()
        assert sample_resume.final_score == 85
        assert not _rows('resume.score_overridden').exists()

    def test_score_change_with_reason_accepted_and_logged(self, authenticated_client, sample_resume):
        resp = self._post(authenticated_client, sample_resume,
                          {'final_score': 42, 'reason': 'panel adjusted after debrief'})
        assert resp.status_code == 302
        sample_resume.refresh_from_db()
        assert sample_resume.final_score == 42
        row = _rows('resume.score_overridden', sample_resume.uuid).get()
        assert 'old=85' in row.details and 'new=42' in row.details
        assert 'panel adjusted' in row.details

    def test_no_score_change_needs_no_reason(self, authenticated_client, sample_resume):
        resp = self._post(authenticated_client, sample_resume, {'candidate_name': 'Renamed Person'})
        assert resp.status_code == 302
        assert not _rows('resume.score_overridden').exists()


# ------------------------------------------------------ screening terminal states
@pytest.mark.django_db
class TestScreeningTransitions:
    def test_completed_logs_no_actor(self, sample_resume, monkeypatch):
        monkeypatch.setattr(ResumeService, 'extract_text', staticmethod(lambda resume: 'cv text'))
        monkeypatch.setattr(ResumeService, 'run_screening',
                            staticmethod(lambda resume: {'final_score': 80}))
        ResumeService.process_resume(sample_resume)
        row = _rows('resume.screening_completed', sample_resume.uuid).get()
        assert row.actor is None

    def test_needs_review_logs(self, sample_resume, monkeypatch):
        monkeypatch.setattr(ResumeService, 'extract_text', staticmethod(lambda resume: 'cv text'))
        monkeypatch.setattr(ResumeService, 'run_screening',
                            staticmethod(lambda resume: {'needs_review': True, 'reasoning': 'uncertain'}))
        ResumeService.process_resume(sample_resume)
        assert _rows('resume.screening_needs_review', sample_resume.uuid).exists()

    def test_failed_logs(self, sample_resume):
        ResumeService._mark_failed(sample_resume, 'boom')
        assert _rows('resume.screening_failed', sample_resume.uuid).exists()


# ------------------------------------------------------------------------- users
@pytest.mark.django_db
class TestUserFlows:
    def test_user_create_logs(self, superuser_client):
        superuser_client.post(reverse('core:user_create'), {
            'username': 'newbie', 'password1': 'Sup3rSecret!x', 'password2': 'Sup3rSecret!x',
        })
        assert _rows('user.created').exists()

    def test_user_deactivate_then_activate_logs(self, superuser_client, user):
        superuser_client.post(reverse('core:user_toggle_active', kwargs={'pk': user.pk}))
        assert _rows('user.deactivated', user.pk).exists()
        superuser_client.post(reverse('core:user_toggle_active', kwargs={'pk': user.pk}))
        assert _rows('user.activated', user.pk).exists()


# ------------------------------------------------------------ PII-absence guard
@pytest.mark.django_db
class TestAuditPIIAbsence:
    """Audit details must never leak candidate PII. Run every instrumented flow
    that touches a candidate with distinctive email/phone/raw_text markers, then
    assert none of the markers appear in any AuditLog.details."""

    EMAIL = 'pii.marker.zzz@secret-domain.invalid'
    PHONE = '+8801700000042'
    RAW = 'RAWTEXTPIIMARKER_XYZ'
    _PDF = b'%PDF-1.4 minimal'

    def test_no_candidate_pii_in_any_audit_details(self, authenticated_client, client, sample_job):
        # A resume with distinctive PII for the override + status-change flows.
        resume = Resume.objects.create(
            job=sample_job, candidate_name='Pii Person',
            email=self.EMAIL, phone=self.PHONE, raw_text=self.RAW,
            experience_score=85, education_score=75, skills_score=90, final_score=85,
        )

        with patch('apps.core.tasks.screen_resume_task.delay'):
            # 1) Recruiter upload.
            authenticated_client.post(
                reverse('core:resume_create', kwargs={'job_slug': sample_job.slug}),
                {'candidate_name': 'Uploaded Pii',
                 'file': SimpleUploadedFile('cv.pdf', self._PDF, content_type='application/pdf')},
            )
            # 2) Public careers apply (email/phone entered by the applicant).
            client.post(reverse('core:careers_apply', kwargs={'slug': sample_job.slug}), {
                'candidate_name': 'Applicant Pii', 'email': self.EMAIL, 'phone': self.PHONE,
                'file': SimpleUploadedFile('cv.pdf', self._PDF, content_type='application/pdf'),
            })

        # 3) Score override (mandatory reason).
        authenticated_client.post(reverse('core:resume_edit', kwargs={'uuid': resume.uuid}), {
            'candidate_name': resume.candidate_name,
            'experience_score': resume.experience_score,
            'education_score': resume.education_score,
            'skills_score': resume.skills_score,
            'certification_score': '',
            'achievement_score': '',
            'final_score': 42,
            'reason': 'panel adjusted after debrief',
        })
        # 4) Recruiter status change.
        authenticated_client.post(
            reverse('core:resume_status_update', kwargs={'uuid': resume.uuid}),
            {'recruiter_status': Resume.RECRUITER_STATUS_CHOICES[0][0]},
        )

        # Guard the guard: the flows actually produced the audit rows we care about.
        assert _rows('resume.uploaded').filter(entity_type='resume').exists()
        assert _rows('resume.score_overridden', resume.uuid).exists()
        assert _rows('resume.recruiter_status_changed', resume.uuid).exists()

        # No marker may appear in ANY audit row's details.
        blob = '\n'.join(AuditLog.objects.values_list('details', flat=True))
        assert self.EMAIL not in blob
        assert self.PHONE not in blob
        assert self.RAW not in blob


# -------------------------------------------------------------------- interviews
@pytest.mark.django_db
class TestInterviewFlows:
    def _interview(self, sample_resume):
        from apps.interviews.models import Interview
        return Interview.objects.create(resume=sample_resume, phase='1', scheduled_date=date.today())

    def test_interview_create_logs(self, authenticated_client, sample_resume):
        authenticated_client.post(
            reverse('interviews:create', kwargs={'resume_uuid': sample_resume.uuid}),
            {'phase': '1', 'scheduled_date': date.today().isoformat()},
        )
        assert _rows('interview.created').exists()

    def test_interview_delete_logs(self, authenticated_client, sample_resume):
        interview = self._interview(sample_resume)
        authenticated_client.post(reverse('interviews:delete', kwargs={'pk': interview.pk}))
        assert _rows('interview.deleted', interview.pk).exists()

    def test_eval_link_renew_logs(self, authenticated_client, sample_resume):
        interview = self._interview(sample_resume)
        ev = interview.evaluations.create(interviewer_name='Bob')
        authenticated_client.post(reverse('interviews:evaluation_renew', kwargs={'token': ev.token}))
        assert _rows('interview.eval_link_renewed', ev.pk).exists()

    def test_eval_link_delete_logs_before_hard_delete(self, authenticated_client, sample_resume):
        interview = self._interview(sample_resume)
        ev = interview.evaluations.create(interviewer_name='Bob')
        pk = ev.pk
        authenticated_client.post(reverse('interviews:evaluation_delete', kwargs={'token': ev.token}))
        assert _rows('interview.eval_link_deleted', pk).exists()

    def test_evaluation_submitted_logs_no_actor(self, client, sample_resume):
        from apps.interviews.models import CRITERIA_KEYS
        interview = self._interview(sample_resume)
        ev = interview.evaluations.create(interviewer_name='Bob')
        data = {f'score_{k}': '4' for k in CRITERIA_KEYS}
        client.post(reverse('interviews:evaluate', kwargs={'token': ev.token}), data)
        row = _rows('interview.evaluation_submitted', ev.pk).get()
        assert row.actor is None


# -------------------------------------------------------------------------- api
@pytest.mark.django_db
class TestApiFlows:
    def test_api_job_create_logs(self, authenticated_client):
        authenticated_client.post('/api/jobs/', json.dumps({
            'title': 'API Job', 'description': 'via api', 'status': 'active',
        }), content_type='application/json')
        assert _rows('job.created').exists()

    def test_api_job_delete_logs(self, authenticated_client, sample_job):
        authenticated_client.delete(f'/api/jobs/{sample_job.pk}/')
        assert _rows('job.deleted', sample_job.slug).exists()

    def test_api_job_restore_logs(self, authenticated_client, sample_job):
        sample_job.soft_delete()
        authenticated_client.post(f'/api/jobs/{sample_job.pk}/restore/')
        assert _rows('job.restored', sample_job.slug).exists()
