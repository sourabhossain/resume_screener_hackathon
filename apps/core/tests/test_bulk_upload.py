"""
Tests for resume_bulk_create view.

Covers:
- Inactive job blocks upload
- Empty file list rejected
- More than 20 files rejected
- Files exceeding 5 MB limit skipped with warning
- Wrong extension skipped
- Magic-byte mismatch (DOCX header on a .pdf) skipped
- Duplicate file hash skipped
- Valid batch creates resumes and queues screening
"""
import io
import pytest
from unittest.mock import patch
from django.urls import reverse

from apps.core.models import Job, Resume


# ── helpers ───────────────────────────────────────────────────────────────────

DOCX_MAGIC = b'PK\x03\x04'  # ZIP-based magic for DOCX
PDF_MAGIC = b'%PDF'


def _fake_file(name, content=None, size=None):
    if content is None:
        ext = name.rsplit('.', 1)[-1].lower()
        content = PDF_MAGIC + b'-1.4 test' if ext == 'pdf' else DOCX_MAGIC + b'\x00' * 20
    buf = io.BytesIO(content)
    buf.name = name
    if size is not None:
        # Pad to desired size so len(file.read()) == size
        buf = io.BytesIO(content + b'\x00' * (size - len(content)))
        buf.name = name
    return buf


def _bulk_post(client, job, files):
    url = reverse('core:resume_bulk_create', kwargs={'job_slug': job.slug})
    with patch('apps.core.tasks.screen_resume_task.delay'):
        return client.post(url, {'files': files})


# ── access & job-status guard ─────────────────────────────────────────────────

@pytest.mark.django_db
class TestBulkUploadAccess:

    def test_unauthenticated_redirects(self, client, sample_job):
        resp = client.post(
            reverse('core:resume_bulk_create', kwargs={'job_slug': sample_job.slug}),
            {'files': [_fake_file('cv.pdf')]},
        )
        assert resp.status_code == 302
        assert 'login' in resp['Location']

    def test_draft_job_blocks_upload(self, authenticated_client, sample_job):
        sample_job.status = 'draft'
        sample_job.save()
        resp = _bulk_post(authenticated_client, sample_job, [_fake_file('cv.pdf')])
        assert resp.status_code == 302
        assert Resume.objects.filter(job=sample_job).count() == 0

    def test_closed_job_blocks_upload(self, authenticated_client, sample_job):
        sample_job.status = 'closed'
        sample_job.save()
        resp = _bulk_post(authenticated_client, sample_job, [_fake_file('cv.pdf')])
        assert resp.status_code == 302
        assert Resume.objects.filter(job=sample_job).count() == 0

    def test_get_renders_form(self, authenticated_client, sample_job):
        resp = authenticated_client.get(
            reverse('core:resume_bulk_create', kwargs={'job_slug': sample_job.slug})
        )
        assert resp.status_code == 200


# ── empty / over-limit guards ─────────────────────────────────────────────────

@pytest.mark.django_db
class TestBulkUploadLimits:

    def test_empty_file_list_rejected(self, authenticated_client, sample_job):
        url = reverse('core:resume_bulk_create', kwargs={'job_slug': sample_job.slug})
        resp = authenticated_client.post(url, {})
        assert resp.status_code == 200  # re-renders form with error

    def test_more_than_20_files_rejected(self, authenticated_client, sample_job):
        files = [_fake_file(f'cv{i}.pdf') for i in range(21)]
        url = reverse('core:resume_bulk_create', kwargs={'job_slug': sample_job.slug})
        with patch('apps.core.tasks.screen_resume_task.delay'):
            resp = authenticated_client.post(url, {'files': files})
        assert resp.status_code == 200  # re-renders with error
        assert Resume.objects.filter(job=sample_job).count() == 0


# ── per-file validation ───────────────────────────────────────────────────────

@pytest.mark.django_db
class TestBulkUploadFileValidation:

    def test_oversized_file_skipped(self, authenticated_client, sample_job):
        big_file = _fake_file('big.pdf', size=6 * 1024 * 1024)
        _bulk_post(authenticated_client, sample_job, [big_file])
        assert Resume.objects.filter(job=sample_job).count() == 0

    def test_wrong_extension_skipped(self, authenticated_client, sample_job):
        bad_file = _fake_file('cv.txt', content=b'plain text')
        _bulk_post(authenticated_client, sample_job, [bad_file])
        assert Resume.objects.filter(job=sample_job).count() == 0

    def test_magic_byte_mismatch_pdf_skipped(self, authenticated_client, sample_job):
        """File named .pdf but with DOCX magic bytes → rejected."""
        fake = _fake_file('cv.pdf', content=DOCX_MAGIC + b'\x00' * 20)
        _bulk_post(authenticated_client, sample_job, [fake])
        assert Resume.objects.filter(job=sample_job).count() == 0

    def test_magic_byte_mismatch_docx_skipped(self, authenticated_client, sample_job):
        """File named .docx but with PDF magic bytes → rejected."""
        fake = _fake_file('cv.docx', content=PDF_MAGIC + b'-1.4 test')
        _bulk_post(authenticated_client, sample_job, [fake])
        assert Resume.objects.filter(job=sample_job).count() == 0

    def test_duplicate_hash_skipped(self, authenticated_client, sample_job):
        from apps.core.utils import compute_file_hash
        content = PDF_MAGIC + b'-1.4 exact same content'
        file_hash = compute_file_hash(io.BytesIO(content))
        Resume.objects.create(
            job=sample_job,
            candidate_name='Already Uploaded',
            file_hash=file_hash,
        )
        dup_file = _fake_file('dup.pdf', content=content)
        _bulk_post(authenticated_client, sample_job, [dup_file])
        # Still only one resume
        assert Resume.objects.filter(job=sample_job).count() == 1

    def test_valid_pdf_queued(self, authenticated_client, sample_job):
        with patch('apps.core.tasks.screen_resume_task.delay') as mock_delay:
            url = reverse('core:resume_bulk_create', kwargs={'job_slug': sample_job.slug})
            authenticated_client.post(url, {'files': [_fake_file('John_Doe.pdf')]})

        assert Resume.objects.filter(job=sample_job).count() == 1
        mock_delay.assert_called_once()

    def test_valid_docx_queued(self, authenticated_client, sample_job):
        with patch('apps.core.tasks.screen_resume_task.delay') as mock_delay:
            url = reverse('core:resume_bulk_create', kwargs={'job_slug': sample_job.slug})
            authenticated_client.post(url, {'files': [_fake_file('Jane_Smith.docx')]})

        assert Resume.objects.filter(job=sample_job).count() == 1
        mock_delay.assert_called_once()

    def test_mixed_batch_valid_and_invalid(self, authenticated_client, sample_job):
        """Valid files are created; invalid ones produce warnings but don't abort."""
        files = [
            _fake_file('valid.pdf', content=PDF_MAGIC + b'-1.4 content-A'),   # valid
            _fake_file('bad.txt', content=b'plain text'),                      # wrong ext
            _fake_file('Jane_Smith.pdf', content=PDF_MAGIC + b'-1.4 content-B'),  # valid, different hash
        ]
        with patch('apps.core.tasks.screen_resume_task.delay'):
            url = reverse('core:resume_bulk_create', kwargs={'job_slug': sample_job.slug})
            resp = authenticated_client.post(url, {'files': files})

        # Redirected after upload
        assert resp.status_code == 302
        assert Resume.objects.filter(job=sample_job).count() == 2

    def test_candidate_name_derived_from_filename(self, authenticated_client, sample_job):
        with patch('apps.core.tasks.screen_resume_task.delay'):
            url = reverse('core:resume_bulk_create', kwargs={'job_slug': sample_job.slug})
            authenticated_client.post(url, {'files': [_fake_file('Alice_Wonderland.pdf')]})

        resume = Resume.objects.get(job=sample_job)
        assert 'Alice' in resume.candidate_name
