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
