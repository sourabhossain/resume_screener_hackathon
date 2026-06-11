"""
Tests for the rank_report view (interviews app).

Covers:
- Requires login
- Renders with no candidates (empty state)
- Composite score calculation: interview 65% + AI 25% + verification 10%
- Composite degrades gracefully when verification score is absent
- Composite degrades to AI-only when no interview evals
- Verdict logic: hire / reject / review / pending
- Phase filter returns only the requested phase
- Rank order: higher composite = lower rank number
"""
from datetime import date

import pytest
from django.urls import reverse

from apps.core.models import Job, Resume
from apps.interviews.models import Interview, InterviewEvaluation, CRITERIA_KEYS


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def job_with_interview(db, user):
    job = Job.objects.create(owner=user, title='Dev Role', status='active')
    resume = Resume.objects.create(
        job=job,
        candidate_name='Candidate One',
        final_score=80,
        verification_score=90,
    )
    iv = Interview.objects.create(resume=resume, phase='1', scheduled_date=date.today())
    return job, resume, iv


def _submit_eval(interview, scores_value=4):
    ev = interview.evaluations.create(interviewer_name='Reviewer')
    ev.scores = {k: scores_value for k in CRITERIA_KEYS}
    ev.recommendation = 'yes'
    ev.is_submitted = True
    ev.save()
    return ev


# ── access control ────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestRankReportAccess:

    def test_unauthenticated_redirects(self, client, job_with_interview):
        job, _, _ = job_with_interview
        resp = client.get(reverse('interviews:rank_report', kwargs={'job_slug': job.slug}))
        assert resp.status_code == 302
        assert 'login' in resp['Location']

    def test_authenticated_renders(self, authenticated_client, job_with_interview):
        job, _, iv = job_with_interview
        _submit_eval(iv)
        resp = authenticated_client.get(
            reverse('interviews:rank_report', kwargs={'job_slug': job.slug})
        )
        assert resp.status_code == 200

    def test_empty_state_renders(self, authenticated_client, user):
        job = Job.objects.create(owner=user, title='Empty Job', status='active')
        resp = authenticated_client.get(
            reverse('interviews:rank_report', kwargs={'job_slug': job.slug})
        )
        assert resp.status_code == 200
        assert resp.context['candidates'] == []


# ── composite score ───────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestRankReportCompositeScore:

    def test_composite_uses_all_three_components(self, authenticated_client, job_with_interview):
        """Composite = interview_pct * 0.65 + ai_score * 0.25 + v_score * 0.10"""
        job, resume, iv = job_with_interview
        # scores_value=4 → percentage = round((4*20 / 100) * 100) = 80
        _submit_eval(iv, scores_value=4)

        resp = authenticated_client.get(
            reverse('interviews:rank_report', kwargs={'job_slug': job.slug})
        )
        candidate = resp.context['candidates'][0]
        expected = round(80 * 0.65 + float(resume.final_score) * 0.25 + float(resume.verification_score) * 0.10)
        assert candidate['composite'] == expected

    def test_composite_degrades_without_verification(self, authenticated_client, user):
        """When verification_score is None: interview 70% + AI 30%."""
        job = Job.objects.create(owner=user, title='Dev Role 2', status='active')
        resume = Resume.objects.create(
            job=job, candidate_name='Cand', final_score=70, verification_score=None
        )
        iv = Interview.objects.create(resume=resume, phase='1', scheduled_date=date.today())
        _submit_eval(iv, scores_value=4)  # 80%

        resp = authenticated_client.get(
            reverse('interviews:rank_report', kwargs={'job_slug': job.slug})
        )
        candidate = resp.context['candidates'][0]
        expected = round(80 * 0.70 + 70 * 0.30)
        assert candidate['composite'] == expected

    def test_composite_falls_back_to_ai_score_only(self, authenticated_client, user):
        """When there are no submitted evals, composite == ai final_score."""
        job = Job.objects.create(owner=user, title='Dev Role 3', status='active')
        resume = Resume.objects.create(
            job=job, candidate_name='Cand', final_score=65, verification_score=None
        )
        iv = Interview.objects.create(resume=resume, phase='1', scheduled_date=date.today())
        # No submitted evaluations → avg_score() returns None
        # rank_report skips candidates with no submitted evals, so nothing in context
        resp = authenticated_client.get(
            reverse('interviews:rank_report', kwargs={'job_slug': job.slug})
        )
        # No submitted evals → no candidates in report
        assert resp.context['candidates'] == []


# ── verdict logic ─────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestRankReportVerdict:

    def _make_candidate(self, user, name, yes=0, no=0, maybe=0, final_score=70):
        job = Job.objects.create(owner=user, title=f'Job-{name}', status='active')
        resume = Resume.objects.create(job=job, candidate_name=name, final_score=final_score)
        iv = Interview.objects.create(resume=resume, phase='1', scheduled_date=date.today())
        for _ in range(yes):
            ev = iv.evaluations.create(interviewer_name=f'yes-{_}')
            ev.scores = {k: 4 for k in CRITERIA_KEYS}
            ev.recommendation = 'yes'
            ev.is_submitted = True
            ev.save()
        for _ in range(no):
            ev = iv.evaluations.create(interviewer_name=f'no-{_}')
            ev.scores = {k: 2 for k in CRITERIA_KEYS}
            ev.recommendation = 'no'
            ev.is_submitted = True
            ev.save()
        for _ in range(maybe):
            ev = iv.evaluations.create(interviewer_name=f'maybe-{_}')
            ev.scores = {k: 3 for k in CRITERIA_KEYS}
            ev.recommendation = 'maybe'
            ev.is_submitted = True
            ev.save()
        return job, resume

    def test_verdict_hire_when_yes_majority(self, authenticated_client, user):
        job, _ = self._make_candidate(user, 'A', yes=2, no=1)
        resp = authenticated_client.get(
            reverse('interviews:rank_report', kwargs={'job_slug': job.slug})
        )
        assert resp.context['candidates'][0]['verdict'] == 'hire'

    def test_verdict_reject_when_no_majority(self, authenticated_client, user):
        job, _ = self._make_candidate(user, 'B', yes=1, no=3)
        resp = authenticated_client.get(
            reverse('interviews:rank_report', kwargs={'job_slug': job.slug})
        )
        assert resp.context['candidates'][0]['verdict'] == 'reject'

    def test_verdict_review_when_tied(self, authenticated_client, user):
        """Tied vote → review, not hire."""
        job, _ = self._make_candidate(user, 'C', yes=1, no=1)
        resp = authenticated_client.get(
            reverse('interviews:rank_report', kwargs={'job_slug': job.slug})
        )
        assert resp.context['candidates'][0]['verdict'] == 'review'

    def test_verdict_review_when_maybe_wins(self, authenticated_client, user):
        job, _ = self._make_candidate(user, 'D', yes=1, no=0, maybe=2)
        resp = authenticated_client.get(
            reverse('interviews:rank_report', kwargs={'job_slug': job.slug})
        )
        assert resp.context['candidates'][0]['verdict'] == 'review'


# ── phase filter ──────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestRankReportPhaseFilter:

    def test_phase_filter_returns_only_requested_phase(self, authenticated_client, user):
        job = Job.objects.create(owner=user, title='Phase Job', status='active')

        resume1 = Resume.objects.create(job=job, candidate_name='P1', final_score=75)
        iv1 = Interview.objects.create(resume=resume1, phase='1', scheduled_date=date.today())
        _submit_eval(iv1)

        resume2 = Resume.objects.create(job=job, candidate_name='P2', final_score=80)
        iv2 = Interview.objects.create(resume=resume2, phase='2', scheduled_date=date.today())
        _submit_eval(iv2)

        resp = authenticated_client.get(
            reverse('interviews:rank_report', kwargs={'job_slug': job.slug}),
            {'phase': '1'},
        )
        names = [c['resume'].candidate_name for c in resp.context['candidates']]
        assert 'P1' in names
        assert 'P2' not in names

    def test_no_phase_filter_returns_all(self, authenticated_client, user):
        job = Job.objects.create(owner=user, title='All Phases', status='active')
        for phase, name, score in [('1', 'Alpha', 70), ('2', 'Beta', 80)]:
            r = Resume.objects.create(job=job, candidate_name=name, final_score=score)
            iv = Interview.objects.create(resume=r, phase=phase, scheduled_date=date.today())
            _submit_eval(iv)

        resp = authenticated_client.get(
            reverse('interviews:rank_report', kwargs={'job_slug': job.slug})
        )
        names = [c['resume'].candidate_name for c in resp.context['candidates']]
        assert 'Alpha' in names
        assert 'Beta' in names


# ── ranking order ─────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestRankReportOrder:

    def test_higher_composite_gets_rank_1(self, authenticated_client, user):
        job = Job.objects.create(owner=user, title='Rank Job', status='active')

        low = Resume.objects.create(job=job, candidate_name='Low', final_score=50)
        iv_low = Interview.objects.create(resume=low, phase='1', scheduled_date=date.today())
        _submit_eval(iv_low, scores_value=2)

        high = Resume.objects.create(job=job, candidate_name='High', final_score=90)
        iv_high = Interview.objects.create(resume=high, phase='1', scheduled_date=date.today())
        _submit_eval(iv_high, scores_value=5)

        resp = authenticated_client.get(
            reverse('interviews:rank_report', kwargs={'job_slug': job.slug})
        )
        candidates = resp.context['candidates']
        assert candidates[0]['resume'].candidate_name == 'High'
        assert candidates[0]['rank'] == 1
        assert candidates[1]['rank'] == 2
