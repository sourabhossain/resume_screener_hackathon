"""Tests for the candidate comparison feature: pure helpers, the view's
validation + query behavior, and rendered-HTML markers."""
from types import SimpleNamespace
from uuid import uuid4

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.core.models import Job, Resume
from apps.core.services.comparison import best_value_flags, build_skills_matrix


# --------------------------------------------------------------- helper units
class TestBestValueFlags:
    def test_marks_single_highest(self):
        assert best_value_flags([70, 85, 60]) == [False, True, False]

    def test_marks_all_ties(self):
        assert best_value_flags([90, 90, 60]) == [True, True, False]

    def test_excludes_nulls_and_never_marks_them(self):
        assert best_value_flags([None, 50, None]) == [False, True, False]

    def test_all_null_marks_none(self):
        assert best_value_flags([None, None]) == [False, False]

    def test_empty(self):
        assert best_value_flags([]) == []

    def test_zero_can_win_only_among_present(self):
        # 0 is a real value; with a None present, 0 is still the max of present.
        assert best_value_flags([0, None]) == [True, False]


def _cand(skills):
    return SimpleNamespace(matched_skills=skills)


class TestSkillsMatrix:
    def test_union_and_presence_case_insensitive(self):
        a = _cand(['Python', 'Django'])
        b = _cand(['python', 'React'])
        m = build_skills_matrix([a, b])
        assert m['total'] == 3
        # Ranked by coverage desc: Python (2) first.
        assert m['rows'][0]['skill'] == 'Python'
        assert m['rows'][0]['present'] == [True, True]
        dj = next(r for r in m['rows'] if r['skill'] == 'Django')
        assert dj['present'] == [True, False]

    def test_cap_and_overflow(self):
        a = _cand([f'skill{i:02d}' for i in range(20)])
        b = _cand([])
        m = build_skills_matrix([a, b], cap=15)
        assert len(m['rows']) == 15
        assert m['overflow'] == 5
        assert m['total'] == 20

    def test_no_skills(self):
        m = build_skills_matrix([_cand([]), _cand(None)])
        assert m['rows'] == [] and m['overflow'] == 0 and m['total'] == 0


# ------------------------------------------------------------------ view tests
@pytest.fixture
def compare_resumes(db, sample_job):
    """Four screened candidates on the same job (scores 90/80/70/60)."""
    out = []
    for i, score in enumerate([90, 80, 70, 60]):
        out.append(Resume.objects.create(
            job=sample_job, candidate_name=f'Cand {i}',
            final_score=score, experience_score=score, education_score=score,
            skills_score=score, certification_score=score, achievement_score=score,
            experience_years=float(i), matched_skills=['Python', 'SQL'],
            certifications=['AWS Cert'] if i == 0 else [],
        ))
    return out


def _url(job):
    return reverse('core:job_compare', kwargs={'slug': job.slug})


@pytest.mark.django_db
class TestCompareView:
    def test_requires_login(self, client, compare_resumes):
        a, b = compare_resumes[0], compare_resumes[1]
        resp = client.get(_url(a.job), {'candidates': f'{a.uuid},{b.uuid}'})
        assert resp.status_code == 302
        assert 'login' in resp.url

    def test_two_valid_render_both_columns(self, authenticated_client, compare_resumes):
        a, b = compare_resumes[0], compare_resumes[1]
        resp = authenticated_client.get(_url(a.job), {'candidates': f'{a.uuid},{b.uuid}'})
        assert resp.status_code == 200
        assert len(resp.context['candidates']) == 2
        body = resp.content.decode()
        assert a.candidate_name.title() in body
        assert b.candidate_name.title() in body

    def test_four_valid_render(self, authenticated_client, compare_resumes):
        ids = ','.join(str(r.uuid) for r in compare_resumes)
        resp = authenticated_client.get(_url(compare_resumes[0].job), {'candidates': ids})
        assert resp.status_code == 200
        assert len(resp.context['candidates']) == 4

    def test_one_candidate_rejected(self, authenticated_client, compare_resumes):
        a = compare_resumes[0]
        resp = authenticated_client.get(_url(a.job), {'candidates': str(a.uuid)})
        assert resp.status_code == 302
        assert resp.url == reverse('core:job_detail', kwargs={'slug': a.job.slug})

    def test_five_candidates_rejected(self, authenticated_client, compare_resumes):
        ids = ','.join([str(r.uuid) for r in compare_resumes] + [str(uuid4())])
        resp = authenticated_client.get(_url(compare_resumes[0].job), {'candidates': ids})
        assert resp.status_code == 302

    def test_cross_job_uuid_rejected(self, authenticated_client, compare_resumes, user):
        other_job = Job.objects.create(owner=user, title='Other', description='x', status='active')
        other = Resume.objects.create(job=other_job, candidate_name='Outsider', final_score=99)
        a = compare_resumes[0]
        resp = authenticated_client.get(_url(a.job), {'candidates': f'{a.uuid},{other.uuid}'})
        assert resp.status_code == 302
        assert resp.url == reverse('core:job_detail', kwargs={'slug': a.job.slug})

    def test_soft_deleted_resume_rejected(self, authenticated_client, compare_resumes):
        a, b = compare_resumes[0], compare_resumes[1]
        b.soft_delete()
        resp = authenticated_client.get(_url(a.job), {'candidates': f'{a.uuid},{b.uuid}'})
        assert resp.status_code == 302

    def test_unknown_uuid_rejected_gracefully(self, authenticated_client, compare_resumes):
        a = compare_resumes[0]
        resp = authenticated_client.get(_url(a.job), {'candidates': f'{a.uuid},{uuid4()}'})
        assert resp.status_code == 302
        assert resp.url == reverse('core:job_detail', kwargs={'slug': a.job.slug})

    def test_malformed_uuid_rejected(self, authenticated_client, compare_resumes):
        a = compare_resumes[0]
        resp = authenticated_client.get(_url(a.job), {'candidates': f'{a.uuid},not-a-uuid'})
        assert resp.status_code == 302

    def test_query_count_constant_2_vs_4(self, authenticated_client, compare_resumes):
        a, b, c, d = compare_resumes
        url = _url(a.job)
        with CaptureQueriesContext(connection) as q2:
            authenticated_client.get(url, {'candidates': f'{a.uuid},{b.uuid}'})
        with CaptureQueriesContext(connection) as q4:
            authenticated_client.get(url, {'candidates': f'{a.uuid},{b.uuid},{c.uuid},{d.uuid}'})
        assert len(q2) == len(q4), f'{len(q2)} vs {len(q4)}'


@pytest.mark.django_db
class TestCompareRenderedHTML:
    def test_tier_badge_and_best_value_and_emdash(self, authenticated_client, sample_job):
        top = Resume.objects.create(job=sample_job, candidate_name='Screened',
                                    final_score=90, skills_score=88)
        blank = Resume.objects.create(job=sample_job, candidate_name='Fresh')  # not screened
        resp = authenticated_client.get(_url(sample_job), {'candidates': f'{top.uuid},{blank.uuid}'})
        body = resp.content.decode()
        assert resp.status_code == 200
        # Tier badge for the screened candidate (final_score 90 -> 'Top').
        assert top.get_tier_display() in body
        # Best-value highlight class present on at least one numeric cell.
        assert 'bg-emerald-50/70' in body
        # Not-screened candidate renders em-dash + note, never a 0.
        assert 'Not screened yet' in body
        assert '—' in body

    def test_list_page_shows_checkbox_and_disabled_compare(self, authenticated_client, sample_resume):
        resp = authenticated_client.get(
            reverse('core:job_detail', kwargs={'slug': sample_resume.job.slug})
        )
        body = resp.content.decode()
        assert 'type="checkbox"' in body
        assert 'toggle(' in body                          # per-row selection binding
        # Compare button is disabled unless 2-4 are selected (literal Alpine expr).
        assert 'selected.length < 2 || selected.length > 4' in body
        assert 'go()' in body                             # compare button click handler
