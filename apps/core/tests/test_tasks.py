"""
Tests for Celery tasks: screen_resume_task, verify_resume_links_task, batch_screen_resumes.

Covers: success path, timeout (SoftTimeLimitExceeded), resume-not-found,
general-exception retry / permanent-failure, and batch concurrency guard.
"""
import pytest
from unittest.mock import patch
from celery.exceptions import SoftTimeLimitExceeded

from apps.core.models import Resume


@pytest.mark.django_db
class TestScreenResumeTaskSuccess:

    def test_success_returns_result_dict(self, sample_resume):
        from apps.core.tasks import screen_resume_task

        mock_result = {
            'success': True,
            'resume_id': sample_resume.id,
            'candidate_name': 'John Doe',
            'final_score': 85,
            'tier': 'top',
            'recommendation': 'interview',
        }
        with patch('apps.core.services.resume_service.ResumeService.process_resume',
                   return_value=mock_result):
            result = screen_resume_task(sample_resume.id)

        assert result['success'] is True
        assert result['final_score'] == 85

    def test_success_does_not_change_status_directly(self, sample_resume):
        """Status management is delegated to ResumeService.process_resume."""
        from apps.core.tasks import screen_resume_task

        with patch('apps.core.services.resume_service.ResumeService.process_resume',
                   return_value={'success': True}) as mock_process:
            screen_resume_task(sample_resume.id)

        mock_process.assert_called_once_with(sample_resume)

    def test_failure_result_logged_but_returned(self, sample_resume):
        from apps.core.tasks import screen_resume_task

        with patch('apps.core.services.resume_service.ResumeService.process_resume',
                   return_value={'success': False, 'error': 'LLM error'}):
            result = screen_resume_task(sample_resume.id)

        assert result['success'] is False
        assert 'LLM error' in result['error']


@pytest.mark.django_db
class TestScreenResumeTaskNotFound:

    def test_missing_resume_sets_failed_status(self):
        from apps.core.tasks import screen_resume_task

        result = screen_resume_task(99999)
        assert result['error'] == 'Resume not found'

    def test_missing_resume_updates_soft_deleted_rows(self, sample_resume):
        """Even a soft-deleted resume should be marked failed, not left as processing."""
        from apps.core.tasks import screen_resume_task

        sample_resume.soft_delete()
        # all_objects reaches soft-deleted; using an ID that exists only in all_objects
        result = screen_resume_task(sample_resume.id)
        sample_resume.refresh_from_db()
        # The task raises DoesNotExist for soft-deleted (SoftDeleteManager hides it)
        assert result['error'] == 'Resume not found'
        sample_resume_in_db = Resume.all_objects.get(pk=sample_resume.pk)
        assert sample_resume_in_db.screening_status == 'failed'


@pytest.mark.django_db
class TestScreenResumeTaskTimeout:

    def test_timeout_sets_failed_status(self, sample_resume):
        from apps.core.tasks import screen_resume_task

        with patch('apps.core.services.resume_service.ResumeService.process_resume',
                   side_effect=SoftTimeLimitExceeded()):
            result = screen_resume_task(sample_resume.id)

        sample_resume.refresh_from_db()
        assert sample_resume.screening_status == 'failed'
        assert result['error'] == 'timeout'

    def test_timeout_returns_resume_id(self, sample_resume):
        from apps.core.tasks import screen_resume_task

        with patch('apps.core.services.resume_service.ResumeService.process_resume',
                   side_effect=SoftTimeLimitExceeded()):
            result = screen_resume_task(sample_resume.id)

        assert result['resume_id'] == sample_resume.id


@pytest.mark.django_db
class TestScreenResumeTaskRetry:

    def test_general_exception_sets_pending_status_before_retry(self, sample_resume):
        """On first failure (retries_left > 0), status is set to 'pending' before the retry
        so the UI shows the task as queued rather than failed while it retries.
        In CELERY_TASK_ALWAYS_EAGER mode, self.retry() re-raises immediately without looping."""
        from apps.core.tasks import screen_resume_task

        with patch('apps.core.services.resume_service.ResumeService.process_resume',
                   side_effect=RuntimeError("network error")):
            with pytest.raises(RuntimeError):
                screen_resume_task(sample_resume.id)

        sample_resume.refresh_from_db()
        # retries_left = max_retries(3) - request.retries(0) = 3 > 0 → pending
        assert sample_resume.screening_status == 'pending'

    def test_max_retries_sets_failed_status(self, sample_resume):
        """When retries_left == 0 (max_retries=0), status is set to 'failed'.
        Simulated by patching max_retries to 0 so the first failure exhausts the limit."""
        from apps.core.tasks import screen_resume_task
        from unittest.mock import patch as _patch

        with _patch.object(screen_resume_task, 'max_retries', 0):
            with patch('apps.core.services.resume_service.ResumeService.process_resume',
                       side_effect=RuntimeError("persistent failure")):
                with pytest.raises(RuntimeError):
                    screen_resume_task(sample_resume.id)

        sample_resume.refresh_from_db()
        # retries_left = 0 - 0 = 0 → 'failed'
        assert sample_resume.screening_status == 'failed'


@pytest.mark.django_db
class TestBatchScreenResumes:

    def test_queues_all_pending_resumes(self, sample_job):
        """All 'pending' resumes for a job are dispatched."""
        from apps.core.tasks import batch_screen_resumes

        r1 = Resume.objects.create(job=sample_job, candidate_name='A', screening_status='pending')
        r2 = Resume.objects.create(job=sample_job, candidate_name='B', screening_status='pending')
        # completed resume should not be re-queued
        Resume.objects.create(job=sample_job, candidate_name='C', screening_status='completed')

        with patch('apps.core.tasks.screen_resume_task.delay') as mock_delay:
            result = batch_screen_resumes(sample_job.id)

        assert result['queued'] == 2
        dispatched_ids = {c.args[0] for c in mock_delay.call_args_list}
        assert r1.id in dispatched_ids
        assert r2.id in dispatched_ids

    def test_marks_pending_as_processing_before_dispatch(self, sample_job):
        from apps.core.tasks import batch_screen_resumes

        resume = Resume.objects.create(job=sample_job, candidate_name='A', screening_status='pending')

        with patch('apps.core.tasks.screen_resume_task.delay'):
            batch_screen_resumes(sample_job.id)

        resume.refresh_from_db()
        assert resume.screening_status == 'processing'

    def test_no_pending_resumes_returns_zero(self, sample_job):
        from apps.core.tasks import batch_screen_resumes

        Resume.objects.create(job=sample_job, candidate_name='A', screening_status='completed')

        with patch('apps.core.tasks.screen_resume_task.delay') as mock_delay:
            result = batch_screen_resumes(sample_job.id)

        assert result['queued'] == 0
        mock_delay.assert_not_called()

    def test_skips_soft_deleted_resumes(self, sample_job):
        from apps.core.tasks import batch_screen_resumes

        r = Resume.objects.create(job=sample_job, candidate_name='A', screening_status='pending')
        r.soft_delete()

        with patch('apps.core.tasks.screen_resume_task.delay') as mock_delay:
            result = batch_screen_resumes(sample_job.id)

        assert result['queued'] == 0
        mock_delay.assert_not_called()

    def test_caps_at_500_per_batch(self, sample_job):
        """Batch is capped at 500 to avoid oversized transactions."""
        from apps.core.tasks import batch_screen_resumes

        resumes = [
            Resume(job=sample_job, candidate_name=f'C{i}', screening_status='pending')
            for i in range(510)
        ]
        Resume.objects.bulk_create(resumes)

        with patch('apps.core.tasks.screen_resume_task.delay'):
            result = batch_screen_resumes(sample_job.id)

        assert result['queued'] == 500
