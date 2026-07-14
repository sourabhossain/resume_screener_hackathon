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

from apps.core.models import Job, Resume

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
        screening_status='failed',
        verification_status='processing',
        final_score=None,
    )

def _rank_cell(row_html):
    """Return the Rank cell from a rendered row. A compare-selection checkbox
    cell now precedes it, so the Rank cell is the second <td>."""
    return row_html.split('</td>')[1]

@pytest.mark.django_db
class TestRankDisplay:
    RANK_BADGE = 'h-7 w-7'

    def test_scored_resume_shows_rank_number(self, scored_resume):
        cell = _rank_cell(render_to_string(
            'core/partials/resume_row.html', {'resume': scored_resume, 'rank': 1},
        ))
        assert self.RANK_BADGE in cell
        assert '>1<' in cell

    def test_pending_resume_shows_dash_not_number(self, pending_resume):
        cell = _rank_cell(render_to_string(
            'core/partials/resume_row.html', {'resume': pending_resume, 'rank': 5},
        ))
        assert '—' in cell
        assert self.RANK_BADGE not in cell

    def test_zero_score_still_ranks(self, sample_job):
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
    """The pending/processing row polls itself every 3s; the fragment must keep
    returning a real <tr> so the row is never replaced with empty content."""

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
        assert 'hx-swap-oob' in body

    def test_fragment_keeps_rank_for_scored_row(self, authenticated_client, scored_resume):
        url = reverse('core:resume_row_fragment', args=[scored_resume.uuid])
        cell = _rank_cell(authenticated_client.get(url).content.decode())
        assert 'h-7 w-7' in cell
        assert '>1<' in cell

@pytest.mark.django_db
class TestJobDetailHtmxSafety:
    """Guards against the 'stacked page' and 'vanishing row' regressions."""

    def test_tbody_disinherits_hx_select(self, authenticated_client, sample_job, scored_resume):
        body = authenticated_client.get(
            reverse('core:job_detail', args=[sample_job.slug])
        ).content.decode()
        assert 'id="pipeline-tbody"' in body
        tbody_tag = body.split('id="pipeline-tbody"', 1)[1].split('>', 1)[0]
        assert 'hx-disinherit' in tbody_tag

    def test_candidate_links_opt_out_of_boost(self, authenticated_client, sample_job, scored_resume):
        body = authenticated_client.get(
            reverse('core:job_detail', args=[sample_job.slug])
        ).content.decode()
        assert 'hx-boost="false"' in body

@pytest.mark.django_db
class TestSecurityHeaders:
    def test_csp_allows_unsafe_eval_for_alpine(self, authenticated_client, sample_job):
        resp = authenticated_client.get(reverse('core:job_list'))
        csp = resp.headers.get('Content-Security-Policy', '')
        assert csp, 'CSP header missing'
        assert "'unsafe-eval'" in csp
        assert "'unsafe-inline'" in csp

    def test_request_id_header_present(self, authenticated_client):
        resp = authenticated_client.get(reverse('core:job_list'))
        assert resp.headers.get('X-Request-ID')

@pytest.mark.django_db
class TestBaseTemplateHtmxConfig:
    def test_history_cache_disabled_and_purged(self, client, sample_job):
        body = client.get(reverse('core:careers')).content.decode()
        assert 'historyCacheSize' in body
        assert 'htmx-history-cache' in body
