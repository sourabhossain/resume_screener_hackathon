"""Link verification waits for shortlisting instead of running for every CV."""
from unittest.mock import patch

import pytest
from django.test import override_settings
from django.urls import reverse

from apps.core.models import Resume
from apps.core.services.resume_service import ResumeService
from apps.core.status import change_status

RESULT = {'skills': ['Python'], 'final_score': 70, 'skill_score': 70, 'experience_score': 70, 'education_score': 70,
          'certification_score': 0, 'reasoning': 'ok'}


@pytest.fixture
def queued(monkeypatch):
    # Run on-commit work at once, as the real request would after its commit.
    monkeypatch.setattr('django.db.transaction.on_commit', lambda fn, *a, **k: fn())
    with patch('apps.core.tasks.verify_resume_links_task.delay') as delay:
        yield delay


def _screen(resume):
    ResumeService.apply_screening_result(resume, RESULT)
    resume.refresh_from_db()
    return resume


@pytest.mark.django_db
def test_a_new_cv_waits_for_shortlisting(sample_resume, queued):
    resume = _screen(sample_resume)
    assert resume.screening_status == 'completed'
    assert resume.verification_status == 'skipped' and resume.verification_results == {'deferred': True}
    queued.assert_not_called()


@pytest.mark.django_db
def test_shortlisting_starts_the_check(sample_resume, queued):
    resume = _screen(sample_resume)
    change_status(resume, 'shortlisted')
    resume.refresh_from_db()
    assert resume.verification_status == 'pending' and resume.verification_results == {}
    queued.assert_called_once_with(resume.pk)

    change_status(resume, 'phone_screen')
    assert queued.call_count == 1


@pytest.mark.django_db
def test_rejecting_never_starts_it(sample_resume, queued):
    resume = _screen(sample_resume)
    change_status(resume, 'rejected')
    resume.refresh_from_db()
    assert resume.verification_status == 'skipped'
    queued.assert_not_called()


@pytest.mark.django_db
def test_rescreening_a_shortlisted_candidate_checks_at_once(sample_resume, queued):
    Resume.objects.filter(pk=sample_resume.pk).update(recruiter_status='shortlisted')
    sample_resume.refresh_from_db()
    resume = _screen(sample_resume)
    assert resume.verification_status == 'pending'
    queued.assert_called_once_with(resume.pk)


@pytest.mark.django_db
@override_settings(VERIFY_LINKS_AFTER_SHORTLIST=False)
def test_the_setting_restores_checking_every_cv(sample_resume, queued):
    resume = _screen(sample_resume)
    assert resume.verification_status == 'pending'
    queued.assert_called_once_with(resume.pk)


@pytest.mark.django_db
def test_the_candidate_page_says_why_there_is_no_check(authenticated_client, sample_resume, queued):
    _screen(sample_resume)
    html = authenticated_client.get(reverse('core:resume_detail', kwargs={'uuid': sample_resume.uuid})).content.decode()
    assert 'Links are checked once the candidate is shortlisted' in html
