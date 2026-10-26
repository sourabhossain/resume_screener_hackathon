"""
Regression tests for the pipeline / resume rendering bugs fixed during the
UI/UX audit. Each test pins a specific past breakage so it can't silently
return:

  * pending (unscored) candidates must show "—" for rank, not a number
  * scored candidates get sequential rank numbers
  * the polling row fragment must render a real <tr> (so live-polling rows
    don't get blanked / vanish)
  * candidate links use hx-boost="false" and the tbody disinherits the
    body's hx-select so boosted navigation never dumps a full page (stacked
    page) and polling never blanks a row
  * security/correlation middleware emits CSP (with 'unsafe-eval' for Alpine)
    and X-Request-ID
  * base.html disables the HTMX history cache and purges stale snapshots
"""
import pytest
from django.template.loader import render_to_string
from django.urls import reverse

from apps.core.models import Resume


@pytest.fixture
def scored_resume(db, sample_job):
    """A fully-screened candidate with a final score (gets a rank)."""
    return Resume.objects.create(
        job=sample_job,
        candidate_name='Scored Candidate',
        email='scored@example.com',
        screening_status='completed',
        verification_status='completed',
        experience_score=80, education_score=70, skills_score=90,
        certification_score=60, final_score=88, tier='top',
        recommendation='interview',
    )


@pytest.fixture
def pending_resume(db, sample_job):
    """An unscored candidate (screening not done) — must NOT get a rank number."""
    return Resume.objects.create(
        job=sample_job,
        candidate_name='Pending Candidate',
        email='pending@example.com',
        screening_status='failed',       # failed screening, no score
        verification_status='processing',  # still verifying → row polls
        final_score=None,
    )


def _rank_cell(row_html):
    """Return just the first <td> (the Rank cell) from a rendered row."""
    return row_html.split('</td>', 1)[0]


@pytest.mark.django_db
class TestRankDisplay:
    # 'h-7 w-7' is the class unique to the numeric rank badge; its absence means
    # the cell fell through to the "—" dash branch.
    RANK_BADGE = 'h-7 w-7'

    def test_scored_resume_shows_rank_number(self, scored_resume):
        cell = _rank_cell(render_to_string(
            'core/partials/resume_row.html', {'resume': scored_resume, 'rank': 1},
        ))
        assert self.RANK_BADGE in cell      # numeric rank badge rendered
        assert '>1<' in cell                # showing the rank number 1

    def test_pending_resume_shows_dash_not_number(self, pending_resume):
        # final_score is None → rank cell must be a dash even though rank=5 is passed
        cell = _rank_cell(render_to_string(
            'core/partials/resume_row.html', {'resume': pending_resume, 'rank': 5},
        ))
        assert '—' in cell
        assert self.RANK_BADGE not in cell  # NO numeric rank badge

    def test_zero_score_still_ranks(self, sample_job):
        # final_score == 0 is a real score (is not None) → should rank, not dash
        zero = Resume.objects.create(
            job=sample_job, candidate_name='Zero', screening_status='completed',
            final_score=0,
        )
        cell = _rank_cell(render_to_string(
            'core/partials/resume_row.html', {'resume': zero, 'rank': 7},
        ))
        assert self.RANK_BADGE in cell


@pytest.mark.django_db
class TestPipelineOrdering:
    def test_scored_sorts_before_unscored(self, sample_job, scored_resume, pending_resume):
        from apps.core.views import _ordered_active_resumes_queryset
        ordered = list(_ordered_active_resumes_queryset(sample_job.resumes))
        assert ordered[0] == scored_resume
        assert ordered[-1] == pending_resume


@pytest.mark.django_db
class TestPollingRowFragment:
    """The single-row fragment (kept for pages loaded before the table's single
    poll) must keep returning a real <tr> so a row is never blanked."""

    def test_fragment_renders_tr(self, authenticated_client, pending_resume):
        url = reverse('core:resume_row_fragment', args=[pending_resume.uuid])
        resp = authenticated_client.get(url)
        assert resp.status_code == 200
        body = resp.content.decode()
        assert '<tr' in body
        assert pending_resume.candidate_name in body

    def test_fragment_carries_oob_badge_and_stats(self, authenticated_client, pending_resume):
        url = reverse('core:resume_row_fragment', args=[pending_resume.uuid])
        body = authenticated_client.get(url).content.decode()
        assert 'hx-swap-oob' in body  # OOB refresh of pending badge / stat cards

    def test_fragment_keeps_rank_for_scored_row(self, authenticated_client, scored_resume):
        # A completed row polled once must keep its rank badge, not fall back to "—".
        url = reverse('core:resume_row_fragment', args=[scored_resume.uuid])
        cell = _rank_cell(authenticated_client.get(url).content.decode())
        assert 'h-7 w-7' in cell  # numeric rank badge present (not the "—" dash)
        assert '>1<' in cell  # sole scored resume → rank 1


@pytest.mark.django_db
class TestTablePoll:
    """One request refreshes every row still in screening or verification."""

    @pytest.fixture
    def processing(self, sample_job):
        return Resume.objects.create(job=sample_job, candidate_name='Being Screened', screening_status='processing')

    def _poll(self, client, job, ids):
        return client.get(reverse('core:pipeline_poll', args=[job.slug]), {'ids': ids}).content.decode()

    def test_pending_rows_are_marked_and_the_page_polls_once(self, authenticated_client, sample_job, processing, scored_resume):
        body = authenticated_client.get(reverse('core:job_detail', args=[sample_job.slug]),
                                        {'recruiter_status': 'all'}).content.decode()
        row = body.split(f'id="resume-row-{processing.pk}"', 1)[1].split('>', 1)[0]
        done = body.split(f'id="resume-row-{scored_resume.pk}"', 1)[1].split('>', 1)[0]
        assert 'data-pending' in row and 'data-pending' not in done
        assert 'every 3s' not in body and body.count('id="pipeline-poller"') == 1
        assert 'hx-trigger="every 8s"' in body

    def test_the_poll_returns_the_rows_out_of_band_with_their_rank(self, authenticated_client, sample_job, processing, scored_resume):
        import re
        body = self._poll(authenticated_client, sample_job, f'{scored_resume.pk}:1,{processing.pk}:2')
        assert len(re.findall(r'<template>\s*<tr id="resume-row-', body)) == 2 and body.count('hx-swap-oob="true"') >= 4
        assert '>1<' in _rank_cell(body.split(f'resume-row-{scored_resume.pk}', 1)[1])
        assert 'id="pipeline-stat-cards" hx-swap-oob="true"' in body

    def test_the_poll_ignores_other_jobs_and_junk(self, authenticated_client, sample_job, pending_resume, user):
        from apps.core.models import Job, Resume
        other = Job.objects.create(title='Other', description='x', owner=user)
        stranger = Resume.objects.create(job=other, candidate_name='Stranger', screening_status='processing')
        body = self._poll(authenticated_client, sample_job, f'{stranger.pk}:1,abc,:5,{pending_resume.pk}:x')
        assert 'Stranger' not in body and f'resume-row-{pending_resume.pk}' in body


@pytest.mark.django_db
class TestJobDetailHtmxSafety:
    """Guards against the 'stacked page' and 'vanishing row' regressions."""

    def test_tbody_disinherits_hx_select(self, authenticated_client, sample_job, scored_resume):
        body = authenticated_client.get(
            reverse('core:job_detail', args=[sample_job.slug])
        ).content.decode()
        # the tbody must disinherit so polling rows don't inherit body's
        # hx-select="#main-content" (which would blank them)
        assert 'id="pipeline-tbody"' in body
        tbody_tag = body.split('id="pipeline-tbody"', 1)[1].split('>', 1)[0]
        assert 'hx-disinherit' in tbody_tag

    def test_candidate_links_opt_out_of_boost(self, authenticated_client, sample_job, scored_resume):
        body = authenticated_client.get(
            reverse('core:job_detail', args=[sample_job.slug])
        ).content.decode()
        # candidate detail links must not be boosted (boosted + disinherit =
        # whole resume_detail document dumped into <body>)
        assert 'hx-boost="false"' in body


@pytest.mark.django_db
class TestSecurityHeaders:
    def test_csp_allows_unsafe_eval_for_alpine(self, authenticated_client, sample_job):
        resp = authenticated_client.get(reverse('core:job_list'))
        csp = resp.headers.get('Content-Security-Policy', '')
        assert csp, 'CSP header missing'
        assert "'unsafe-eval'" in csp   # AlpineJS needs Function() eval
        assert "'unsafe-inline'" in csp

    def test_request_id_header_present(self, authenticated_client):
        resp = authenticated_client.get(reverse('core:job_list'))
        assert resp.headers.get('X-Request-ID')


@pytest.mark.django_db
class TestBaseTemplateHtmxConfig:
    def test_history_cache_disabled_and_purged(self, client, sample_job):
        # use a public page so no auth redirect strips the <head>
        body = client.get(reverse('core:careers')).content.decode()
        assert 'historyCacheSize' in body         # cache disabled via meta config
        assert 'htmx-history-cache' in body        # stale snapshot purge script
