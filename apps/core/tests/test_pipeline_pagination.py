"""A job's pipeline table comes in pages, and pages and pages of HTML are gzipped."""
import gzip
import re

import pytest
from django.urls import reverse

from apps.core.models import Resume


def _row_ids(html):
    return [int(pk) for pk in re.findall(r'<tr id="resume-row-(\d+)"', html)]


@pytest.fixture
def crowded_job(sample_job):
    # Equal scores and one created_at for everyone: only the pk can keep the
    # order stable from one page to the next.
    Resume.objects.bulk_create([
        Resume(job=sample_job, candidate_name=f'Candidate {i}', final_score=70, screening_status='completed',
               recommendation='talent_pool', recruiter_status='shortlisted' if i % 4 == 0 else 'new')
        for i in range(120)])
    return sample_job


def _first_page(client, job, **params):
    return client.get(reverse('core:job_detail', kwargs={'slug': job.slug}), params).content.decode()


def _more(client, job, offset, **params):
    url = reverse('core:pipeline_search', kwargs={'job_slug': job.slug})
    return client.get(url, {'offset': offset, **params}).content.decode()


@pytest.mark.django_db
def test_the_table_comes_fifty_at_a_time_without_gaps_or_repeats(authenticated_client, crowded_job):
    first = _first_page(authenticated_client, crowded_job, recruiter_status='all')
    assert len(_row_ids(first)) == 50 and '120 in queue' in first
    assert 'Show 50 more' in first and '70 left' in first

    second = _more(authenticated_client, crowded_job, 50, recruiter_status='all')
    third = _more(authenticated_client, crowded_job, 100, recruiter_status='all')
    assert len(_row_ids(second)) == 50 and 'Show 20 more' in second
    assert len(_row_ids(third)) == 20 and 'Show ' not in third

    seen = _row_ids(first) + _row_ids(second) + _row_ids(third)
    assert len(seen) == len(set(seen)) == 120
    assert set(seen) == set(Resume.objects.values_list('pk', flat=True))


@pytest.mark.django_db
def test_rank_numbers_continue_on_the_next_page(authenticated_client, crowded_job):
    second = _more(authenticated_client, crowded_job, 50, recruiter_status='all')
    ranks = [int(n) for n in re.findall(r'tabular-nums">(\d+)</span>', second)]
    assert ranks[:3] == [51, 52, 53] and ranks[-1] == 100


@pytest.mark.django_db
def test_the_next_page_keeps_the_filters(authenticated_client, crowded_job):
    first = _first_page(authenticated_client, crowded_job, recruiter_status='new')
    assert '90 in queue' in first and '40 left' in first
    assert 'hx-include="#pipeline-search-input, #pipeline-status-filter, #pipeline-seen-filter"' in first
    rest = _more(authenticated_client, crowded_job, 50, recruiter_status='new')
    statuses = set(Resume.objects.filter(pk__in=_row_ids(rest)).values_list('recruiter_status', flat=True))
    assert len(_row_ids(rest)) == 40 and statuses == {'new'}


@pytest.mark.django_db
def test_a_page_past_the_end_is_empty_without_the_no_match_message(authenticated_client, crowded_job):
    past = _more(authenticated_client, crowded_job, 500, recruiter_status='all')
    assert _row_ids(past) == [] and 'No candidates' not in past
    none = _more(authenticated_client, crowded_job, 0, q='nobody-has-this-name', recruiter_status='all')
    assert 'No candidates match' in none
    assert _row_ids(_more(authenticated_client, crowded_job, 'junk', recruiter_status='all'))


@pytest.mark.django_db
def test_pages_are_gzipped_but_downloads_are_not(authenticated_client, crowded_job):
    page = authenticated_client.get(reverse('core:job_detail', kwargs={'slug': crowded_job.slug}),
                                    HTTP_ACCEPT_ENCODING='gzip')
    assert page['Content-Encoding'] == 'gzip' and 'Accept-Encoding' in page['Vary']
    assert len(page.content) * 5 < len(gzip.decompress(page.content))

    sheet = authenticated_client.get(reverse('core:job_ranking_xlsx', kwargs={'slug': crowded_job.slug}),
                                     HTTP_ACCEPT_ENCODING='gzip')
    assert sheet.status_code == 200 and not sheet.has_header('Content-Encoding')

    plain = authenticated_client.get(reverse('core:job_detail', kwargs={'slug': crowded_job.slug}))
    assert not plain.has_header('Content-Encoding')


@pytest.fixture
def three(sample_job):
    from datetime import timedelta
    from django.utils import timezone
    rows = [('Zara Ahmed', 90, 3), ('Abir Khan', 60, 1), ('Mitu Das', 75, 2)]
    made = {}
    for name, score, days_ago in rows:
        r = Resume.objects.create(job=sample_job, candidate_name=name, final_score=score, screening_status='completed',
                                  recommendation='interview')
        Resume.objects.filter(pk=r.pk).update(created_at=timezone.now() - timedelta(days=days_ago))
        made[name] = r.pk
    return made


def _names(html):
    pks = _row_ids(html)
    names = dict(Resume.objects.filter(pk__in=pks).values_list('pk', 'candidate_name'))
    return [names[pk] for pk in pks]


@pytest.mark.django_db
@pytest.mark.parametrize('sort,expected', [
    (None, ['Zara Ahmed', 'Mitu Das', 'Abir Khan']),
    ('best', ['Zara Ahmed', 'Mitu Das', 'Abir Khan']),
    ('newest', ['Abir Khan', 'Mitu Das', 'Zara Ahmed']),
    ('oldest', ['Zara Ahmed', 'Mitu Das', 'Abir Khan']),
    ('name', ['Abir Khan', 'Mitu Das', 'Zara Ahmed']),
    ('junk', ['Zara Ahmed', 'Mitu Das', 'Abir Khan']),
])
def test_the_table_can_be_sorted(authenticated_client, three, sample_job, sort, expected):
    params = {'recruiter_status': 'all', **({'sort': sort} if sort else {})}
    assert _names(_first_page(authenticated_client, sample_job, **params)) == expected
    assert _names(_more(authenticated_client, sample_job, 0, **params)) == expected


@pytest.mark.django_db
def test_final_score_is_the_default_and_the_picker_offers_the_rest(authenticated_client, three, sample_job):
    html = _first_page(authenticated_client, sample_job, recruiter_status='all')
    assert 'id="pipeline-sort"' in html and 'value="best"' in html
    for label in ('Final score', 'Latest CV', 'Oldest CV', 'Name (A–Z)'):
        assert label in html
    assert '3 in queue · sorted by decision, then score' in html


@pytest.mark.django_db
def test_a_new_sort_refreshes_the_note_above_the_table(authenticated_client, three, sample_job):
    fresh = _more(authenticated_client, sample_job, 0, recruiter_status='all', sort='newest')
    assert '<template><p id="pipeline-queue-summary" hx-swap-oob="true"' in fresh and '3 in queue · newest first' in fresh


@pytest.mark.django_db
def test_medals_only_mark_the_score_order(authenticated_client, three, sample_job):
    best = _first_page(authenticated_client, sample_job, recruiter_status='all')
    newest = _first_page(authenticated_client, sample_job, recruiter_status='all', sort='newest')
    assert 'bg-amber-100 text-amber-700' in best and 'bg-amber-100 text-amber-700' not in newest


@pytest.mark.django_db
def test_the_next_page_keeps_the_sort(authenticated_client, crowded_job):
    first = _first_page(authenticated_client, crowded_job, recruiter_status='all', sort='newest')
    assert '#pipeline-sort"' in first
    rest = _more(authenticated_client, crowded_job, 50, recruiter_status='all', sort='newest')
    rest += _more(authenticated_client, crowded_job, 100, recruiter_status='all', sort='newest')
    ids = _row_ids(first) + _row_ids(rest)
    assert ids == sorted(Resume.objects.values_list('pk', flat=True), reverse=True)
