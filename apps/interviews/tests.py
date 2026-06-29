"""Tests for the interviews app: models, recruiter views, and the public
token-based evaluation flow."""
from datetime import date, timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.interviews.forms import InterviewerAddForm
from apps.interviews.models import (
    Interview,
    InterviewEvaluation,
    CRITERIA_KEYS,
    MAX_SCORE,
)

@pytest.fixture
def interview(db, sample_resume):
    return Interview.objects.create(
        resume=sample_resume, phase='1', scheduled_date=date.today()
    )

@pytest.fixture
def evaluation(db, interview):
    return interview.evaluations.create(interviewer_name='Bob Reviewer')

def _full_scores(value=4):
    """A complete, valid evaluation POST payload (all criteria scored)."""
    return {f'score_{k}': str(value) for k in CRITERIA_KEYS}

@pytest.mark.django_db
class TestInterviewModels:
    def test_evaluation_gets_token_and_expiry_on_create(self, evaluation):
        assert evaluation.token is not None
        assert evaluation.token_expires_at is not None
        assert evaluation.token_expires_at > timezone.now()

    def test_total_score_and_percentage(self, evaluation):
        evaluation.scores = {k: 4 for k in CRITERIA_KEYS}
        assert evaluation.total_score == len(CRITERIA_KEYS) * 4
        assert evaluation.percentage == round((evaluation.total_score / MAX_SCORE) * 100)

    def test_total_score_ignores_out_of_range_values(self, evaluation):
        evaluation.scores = {'educational_background': 9, 'enthusiasm': 3}
        assert evaluation.total_score == 3

    def test_impression_label_bands(self, evaluation):
        evaluation.scores = {k: 5 for k in CRITERIA_KEYS}
        assert evaluation.impression_label == 'Good'
        evaluation.scores = {k: 3 for k in CRITERIA_KEYS}
        assert evaluation.impression_label == 'Satisfactory'
        evaluation.scores = {k: 1 for k in CRITERIA_KEYS}
        assert evaluation.impression_label == 'Unsatisfactory'

    def test_is_expired_logic(self, interview):
        ev = interview.evaluations.create(interviewer_name='X')
        assert ev.is_expired is False
        ev.token_expires_at = timezone.now() - timedelta(days=1)
        ev.save(update_fields=['token_expires_at'])
        assert ev.is_expired is True
        ev.is_submitted = True
        assert ev.is_expired is False

    def test_interview_avg_and_counts(self, interview):
        assert interview.avg_score() is None
        e1 = interview.evaluations.create(interviewer_name='A', scores={k: 4 for k in CRITERIA_KEYS}, is_submitted=True)
        interview.evaluations.create(interviewer_name='B')
        assert interview.submitted_count == 1
        assert interview.pending_count == 1
        assert interview.avg_score() == e1.total_score

@pytest.mark.django_db
class TestInterviewerAddForm:
    def test_accepts_bengali_and_english_names(self):
        form = InterviewerAddForm({
            'interviewer_name': 'আসাদ হোসেন',
            'interviewer_position': 'Sr. Manager',
            'interviewer_department': 'Human Resources',
        })
        assert form.is_valid(), form.errors

    def test_accepts_hyphen_apostrophe_and_period(self):
        form = InterviewerAddForm({
            'interviewer_name': "Dr. O'Brien-Smith",
            'interviewer_position': '',
            'interviewer_department': '',
        })
        assert form.is_valid(), form.errors

    def test_rejects_special_characters(self):
        form = InterviewerAddForm({
            'interviewer_name': "ঘজক্ল;'",
            'interviewer_position': 'bad@title',
            'interviewer_department': '',
        })
        assert not form.is_valid()
        assert 'interviewer_name' in form.errors
        assert 'interviewer_position' in form.errors

    def test_rejects_name_without_letters(self):
        form = InterviewerAddForm({
            'interviewer_name': '12345',
            'interviewer_position': '',
            'interviewer_department': '',
        })
        assert not form.is_valid()
        assert 'interviewer_name' in form.errors

    def test_trims_whitespace(self):
        form = InterviewerAddForm({
            'interviewer_name': '  Carol  ',
            'interviewer_position': '  Lead  ',
            'interviewer_department': '',
        })
        assert form.is_valid(), form.errors
        assert form.cleaned_data['interviewer_name'] == 'Carol'
        assert form.cleaned_data['interviewer_position'] == 'Lead'

@pytest.mark.django_db
class TestRecruiterViews:
    def test_create_requires_login(self, client, sample_resume):
        url = reverse('interviews:create', kwargs={'resume_uuid': sample_resume.uuid})
        resp = client.get(url)
        assert resp.status_code == 302
        assert 'login' in resp.url

    def test_create_get_and_post(self, authenticated_client, sample_resume):
        url = reverse('interviews:create', kwargs={'resume_uuid': sample_resume.uuid})
        assert authenticated_client.get(url).status_code == 200
        resp = authenticated_client.post(url, {'phase': '1', 'scheduled_date': '2026-07-01', 'notes': 'x'})
        assert resp.status_code == 302
        assert Interview.objects.filter(resume=sample_resume).exists()

    def test_detail_renders(self, authenticated_client, interview):
        resp = authenticated_client.get(reverse('interviews:detail', kwargs={'pk': interview.pk}))
        assert resp.status_code == 200

    def test_detail_add_interviewer(self, authenticated_client, interview):
        url = reverse('interviews:detail', kwargs={'pk': interview.pk})
        resp = authenticated_client.post(url, {'interviewer_name': 'Carol', 'interviewer_position': 'Lead'})
        assert resp.status_code == 302
        assert interview.evaluations.filter(interviewer_name='Carol').exists()

    def test_detail_rejects_invalid_interviewer_input(self, authenticated_client, interview):
        url = reverse('interviews:detail', kwargs={'pk': interview.pk})
        before = interview.evaluations.count()
        resp = authenticated_client.post(url, {
            'interviewer_name': 'bad@name',
            'interviewer_position': 'Lead',
            'interviewer_department': '',
        })
        assert resp.status_code == 200
        assert interview.evaluations.count() == before
        assert b'dj-messages' in resp.content
        assert b'invalid characters' in resp.content.lower()
        assert b'ring-red-400/50' not in resp.content

    def test_delete_soft_deletes(self, authenticated_client, interview):
        url = reverse('interviews:delete', kwargs={'pk': interview.pk})
        resp = authenticated_client.post(url)
        assert resp.status_code == 302
        interview.refresh_from_db()
        assert interview.is_deleted is True

    def test_evaluation_renew_changes_token(self, authenticated_client, evaluation):
        old = evaluation.token
        url = reverse('interviews:evaluation_renew', kwargs={'token': evaluation.token})
        authenticated_client.post(url)
        evaluation.refresh_from_db()
        assert evaluation.token != old

    def test_evaluation_delete(self, authenticated_client, evaluation):
        url = reverse('interviews:evaluation_delete', kwargs={'token': evaluation.token})
        authenticated_client.post(url)
        assert not InterviewEvaluation.objects.filter(pk=evaluation.pk).exists()

    def test_any_authenticated_recruiter_can_access_others_interview(
        self, client, django_user_model, interview
    ):
        """Single-company: a non-owner, non-staff recruiter still has access
        (consistent with unscoped jobs/resumes in core)."""
        interview.resume.job.owner = django_user_model.objects.create_user(
            username='owner2', password='x'
        )
        interview.resume.job.save()
        other = django_user_model.objects.create_user(username='recruiter2', password='x')
        client.force_login(other)
        resp = client.get(reverse('interviews:detail', kwargs={'pk': interview.pk}))
        assert resp.status_code == 200

@pytest.mark.django_db
class TestPublicEvaluate:
    def test_evaluate_get_valid(self, client, evaluation):
        resp = client.get(reverse('interviews:evaluate', kwargs={'token': evaluation.token}))
        assert resp.status_code == 200

    def test_evaluate_bogus_token_404(self, client):
        import uuid
        resp = client.get(reverse('interviews:evaluate', kwargs={'token': uuid.uuid4()}))
        assert resp.status_code == 404

    def test_submit_auto_recommendation_yes(self, client, evaluation):
        url = reverse('interviews:evaluate', kwargs={'token': evaluation.token})
        resp = client.post(url, _full_scores(4))
        assert resp.status_code == 302
        evaluation.refresh_from_db()
        assert evaluation.is_submitted is True
        assert evaluation.recommendation == 'yes'
        assert len(evaluation.scores) == len(CRITERIA_KEYS)

    def test_submit_auto_recommendation_maybe_and_no(self, client, interview):
        e_maybe = interview.evaluations.create(interviewer_name='M')
        client.post(reverse('interviews:evaluate', kwargs={'token': e_maybe.token}), _full_scores(3))
        e_maybe.refresh_from_db()
        assert e_maybe.recommendation == 'maybe'

        e_no = interview.evaluations.create(interviewer_name='N')
        client.post(reverse('interviews:evaluate', kwargs={'token': e_no.token}), _full_scores(1))
        e_no.refresh_from_db()
        assert e_no.recommendation == 'no'

    def test_manual_recommendation_overrides_score(self, client, evaluation):
        url = reverse('interviews:evaluate', kwargs={'token': evaluation.token})
        data = _full_scores(1)
        data['recommendation'] = 'yes'
        client.post(url, data)
        evaluation.refresh_from_db()
        assert evaluation.recommendation == 'yes'

    def test_resubmit_blocked(self, client, evaluation):
        url = reverse('interviews:evaluate', kwargs={'token': evaluation.token})
        client.post(url, _full_scores(4))
        resp = client.get(url)
        assert resp.status_code == 200
        assert b'score-radio' not in resp.content

    def test_expired_token_shows_expired_page(self, client, evaluation):
        evaluation.token_expires_at = timezone.now() - timedelta(days=1)
        evaluation.save(update_fields=['token_expires_at'])
        resp = client.get(reverse('interviews:evaluate', kwargs={'token': evaluation.token}))
        assert resp.status_code == 200
        assert b'score-radio' not in resp.content

    def test_evaluate_done_renders(self, client, evaluation):
        resp = client.get(reverse('interviews:evaluate_done', kwargs={'token': evaluation.token}))
        assert resp.status_code == 200
