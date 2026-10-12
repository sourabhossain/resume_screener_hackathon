"""CVs that arrive as pictures: read by OCR, and caught on the public form."""
import io
from unittest.mock import patch

import pymupdf
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.core.models import Resume
from apps.core.services.document_extractor import DocumentExtractor

CV_LINES = ['Jane Candidate', 'Senior Python Developer', 'jane.candidate@example.com',
            'Experience: Django, Celery, MySQL, Redis', 'Education: BSc in Computer Science']


def _text_pdf():
    doc = pymupdf.open()
    page = doc.new_page()
    for i, line in enumerate(CV_LINES):
        page.insert_text((72, 100 + 30 * i), line, fontsize=16)
    return doc.tobytes()


def _image_only_pdf():
    """The same page, flattened to a picture: what a scan or a Canva export gives."""
    source = pymupdf.open(stream=_text_pdf(), filetype='pdf')
    picture = source[0].get_pixmap(dpi=200).tobytes('png')
    doc = pymupdf.open()
    page = doc.new_page(width=source[0].rect.width, height=source[0].rect.height)
    page.insert_image(page.rect, stream=picture)
    return doc.tobytes(deflate=True)


def _upload(data, name='cv.pdf'):
    return SimpleUploadedFile(name, data, content_type='application/pdf')


def _write(tmp_path, data):
    path = tmp_path / 'cv.pdf'
    path.write_bytes(data)
    return str(path)


# ── OCR ──────────────────────────────────────────────────────────────────
def test_a_cv_saved_as_a_picture_is_read_by_ocr(tmp_path):
    path = _write(tmp_path, _image_only_pdf())
    assert DocumentExtractor._extract_pdf_pymupdf(path).strip() == ''

    text = DocumentExtractor.extract(path)

    assert 'Python Developer' in text and 'Django' in text


def test_a_normal_pdf_is_not_sent_through_ocr(tmp_path):
    path = _write(tmp_path, _text_pdf())
    with patch.object(DocumentExtractor, '_extract_pdf_ocr') as ocr:
        text = DocumentExtractor.extract(path)
    assert 'Jane Candidate' in text
    ocr.assert_not_called()


def test_without_tesseract_the_file_is_reported_unreadable_not_crashed(tmp_path):
    path = _write(tmp_path, _image_only_pdf())
    with patch('pymupdf.Page.get_textpage_ocr', side_effect=RuntimeError('No tessdata specified')):
        assert DocumentExtractor.extract(path).strip() == ''


# ── the public application form ──────────────────────────────────────────
def test_the_text_check_tells_pictures_from_text():
    assert DocumentExtractor.has_text_layer(_upload(_text_pdf()), 'pdf') is True
    assert DocumentExtractor.has_text_layer(_upload(_image_only_pdf()), 'pdf') is False
    assert DocumentExtractor.has_text_layer(_upload(b'%PDF-1.4 broken'), 'pdf') is True


def _apply(client, job, data):
    with patch('apps.core.tasks.screen_resume_task.delay'):
        return client.post(reverse('core:careers_apply', kwargs={'slug': job.slug}), {
            'candidate_name': 'Jane Candidate', 'email': 'jane@example.com', 'phone': '+8801711000000',
            'file': _upload(data)})


@pytest.mark.django_db
def test_a_candidate_who_uploads_a_picture_is_asked_for_a_text_pdf(client, sample_job):
    response = _apply(client, sample_job, _image_only_pdf())

    assert response.status_code == 200
    assert 'could not read any text in this file' in response.content.decode()
    assert not Resume.objects.filter(email='jane@example.com').exists()


@pytest.mark.django_db
def test_a_candidate_with_a_text_pdf_applies_as_before(client, sample_job):
    response = _apply(client, sample_job, _text_pdf())

    assert response.status_code == 302
    assert Resume.objects.filter(email='jane@example.com').exists()


@pytest.mark.django_db
def test_hr_can_still_upload_a_scanned_cv_for_ocr(authenticated_client, sample_job):
    with patch('apps.core.tasks.screen_resume_task.delay'):
        response = authenticated_client.post(
            reverse('core:resume_create', kwargs={'job_slug': sample_job.slug}),
            {'candidate_name': 'Scanned Candidate', 'file': _upload(_image_only_pdf())})

    assert response.status_code == 302
    assert Resume.objects.filter(candidate_name='Scanned Candidate').exists()
