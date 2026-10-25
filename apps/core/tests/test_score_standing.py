"""The AI Benchmark card: a candidate's percentile among everyone scored for the job."""
import pytest
from django.urls import reverse

from apps.core.models import Resume


def _scored(job, name, score, **extra):
    return Resume.objects.create(job=job, candidate_name=name, final_score=score,
                                 screening_status='completed', **extra)


@pytest.fixture
def pool(sample_job):
    return [_scored(sample_job, f'Candidate {i}', score) for i, score in enumerate((40, 55, 62, 70, 81, 93.5))]


@pytest.mark.django_db
def test_the_percentile_counts_the_other_candidates_scored_lower(pool):
    s = pool[3].score_standing
    assert (s['percentile'], s['suffix'], s['raw'], s['band'], s['others']) == (60, 'th', 70, 'Above', 5)
    assert (s['position'], s['pool'], s['lower']) == (3, 6, 3)
    assert pool[0].score_standing['percentile'] == 1 and pool[0].score_standing['band'] == 'Well below'
    top = pool[-1].score_standing
    assert top['percentile'] == 99 and top['is_top'] and top['top'] == 94


@pytest.mark.django_db
def test_unscored_and_other_jobs_candidates_are_left_out(pool, sample_job, user):
    from apps.core.models import Job
    other = Job.objects.create(title='Other role', description='x', owner=user)
    _scored(other, 'Elsewhere', 99)
    Resume.objects.create(job=sample_job, candidate_name='Pending', screening_status='processing')
    assert pool[-1].score_standing['pool'] == 6
    assert Resume.objects.get(candidate_name='Pending').score_standing is None


@pytest.mark.django_db
def test_a_small_pool_says_when_the_percentile_will_appear(sample_job):
    first = _scored(sample_job, 'Only One', 80)
    assert first.score_standing == {'enough': False, 'pool': 1, 'needed': 5}


@pytest.mark.django_db
def test_the_candidate_page_shows_the_card(authenticated_client, pool):
    html = authenticated_client.get(reverse('core:resume_detail', kwargs={'uuid': pool[3].uuid})).content.decode()
    assert 'AI Benchmark' in html and '60<sup class="text-base">th</sup> percentile' in html
    assert '#3 of 6</strong>' in html and 'scoring higher than 3 of the other 5 candidates (60%)' in html
    assert 'Score Breakdown' not in html


@pytest.mark.django_db
def test_suffixes():
    from apps.core.standing import _suffix
    assert [_suffix(n) for n in (1, 2, 3, 4, 11, 12, 13, 21, 22, 99)] == [
        'st', 'nd', 'rd', 'th', 'th', 'th', 'th', 'st', 'nd', 'th']


@pytest.mark.django_db
def test_equal_scores_share_a_position(pool, sample_job):
    tied = _scored(sample_job, 'Tied', 70)
    assert tied.score_standing['position'] == pool[3].score_standing['position'] == 3


@pytest.mark.django_db
def test_the_table_scores_column_is_unchanged(authenticated_client, pool, sample_job):
    html = authenticated_client.get(reverse('core:job_detail', kwargs={'slug': sample_job.slug}),
                                    {'recruiter_status': 'all'}).content.decode()
    assert '>Experience<' in html and '>Position<' not in html
