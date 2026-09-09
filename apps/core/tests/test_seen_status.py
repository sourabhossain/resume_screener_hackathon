"""The Seen / Not Seen status HR sets on a CV.

Set by hand, like recruiter status. Deliberately not driven by opening the
page: clicking through a list of two hundred applicants is not reading them,
and a queue that marked itself would tell HR nothing about what is left.
"""
import pytest
from django.urls import reverse

from apps.core.models import Resume


def _seen_url(resume):
    return reverse('core:resume_seen_update', kwargs={'uuid': resume.uuid})


def _pipeline(job, **params):
    url = reverse('core:job_detail', kwargs={'slug': job.slug})
    query = '&'.join(f'{k}={v}' for k, v in {'recruiter_status': 'all', **params}.items())
    return f'{url}?{query}'


HTMX = {'HTTP_HX_REQUEST': 'true'}


# ── Setting it ───────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_a_new_cv_starts_not_seen(sample_resume):
    assert sample_resume.seen_status == 'unseen'
    assert sample_resume.is_seen is False


@pytest.mark.django_db
def test_hr_marks_a_cv_seen(authenticated_client, sample_resume):
    authenticated_client.post(_seen_url(sample_resume), {'seen_status': 'seen'}, **HTMX)

    sample_resume.refresh_from_db()
    assert sample_resume.is_seen is True


@pytest.mark.django_db
def test_hr_can_put_it_back(authenticated_client, sample_resume):
    """Marked by mistake has to be undoable, or the column becomes a trap."""
    authenticated_client.post(_seen_url(sample_resume), {'seen_status': 'seen'}, **HTMX)
    authenticated_client.post(_seen_url(sample_resume), {'seen_status': 'unseen'}, **HTMX)

    sample_resume.refresh_from_db()
    assert sample_resume.is_seen is False


@pytest.mark.django_db
def test_merely_opening_the_cv_changes_nothing(authenticated_client, sample_resume):
    """The whole point of a manual status: reading the page is not reviewing."""
    authenticated_client.get(
        reverse('core:resume_detail', kwargs={'uuid': sample_resume.uuid}))

    sample_resume.refresh_from_db()
    assert sample_resume.seen_status == 'unseen'


@pytest.mark.django_db
def test_setting_seen_writes_only_its_own_column(authenticated_client, sample_resume):
    """Both statuses sit on one row and are changed from the same table.

    Asserted on the SQL rather than on an outcome, because the damage a full
    row write does only appears when a colleague happens to be editing the same
    candidate at that moment -- rare, invisible, and impossible to reproduce
    from a bug report.
    """
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    with CaptureQueriesContext(connection) as queries:
        authenticated_client.post(
            _seen_url(sample_resume), {'seen_status': 'seen'}, **HTMX)

    updates = [q['sql'] for q in queries.captured_queries
               if q['sql'].lstrip().upper().startswith('UPDATE')
               and 'resumes' in q['sql']]
    assert len(updates) == 1, f'expected one UPDATE, got {len(updates)}'
    sql = updates[0]
    assert 'seen_status' in sql
    for untouched in ('recruiter_status', 'final_score', 'raw_text', 'tier'):
        assert untouched not in sql, f'the write also touched {untouched}'


@pytest.mark.django_db
def test_a_tampered_value_is_refused_and_nothing_is_saved(authenticated_client,
                                                          sample_resume):
    response = authenticated_client.post(
        _seen_url(sample_resume), {'seen_status': 'definitely_seen'}, **HTMX)

    assert response.status_code == 400
    sample_resume.refresh_from_db()
    assert sample_resume.seen_status == 'unseen'


@pytest.mark.django_db
def test_anonymous_cannot_change_it(client, sample_resume):
    response = client.post(_seen_url(sample_resume), {'seen_status': 'seen'})

    assert response.status_code == 302
    assert '/login/' in response.url
    sample_resume.refresh_from_db()
    assert sample_resume.seen_status == 'unseen'


@pytest.mark.django_db
def test_it_cannot_be_changed_by_a_get(authenticated_client, sample_resume):
    response = authenticated_client.get(_seen_url(sample_resume),
                                        {'seen_status': 'seen'})

    assert response.status_code == 405
    sample_resume.refresh_from_db()
    assert sample_resume.seen_status == 'unseen'


@pytest.mark.django_db
def test_the_response_is_the_refreshed_cell(authenticated_client, sample_resume):
    """htmx swaps this straight back into the table, so it must come back
    showing the new value -- not the old one."""
    response = authenticated_client.post(
        _seen_url(sample_resume), {'seen_status': 'seen'}, **HTMX)
    body = response.content.decode()

    assert response.status_code == 200
    assert body.strip().startswith('<td')
    # Both options live in the dropdown, so check the button's own label --
    # the bit HR actually reads in the table.
    import re
    label = re.search(r'<span class="whitespace-nowrap">([^<]+)</span>', body)
    assert label, 'the cell renders no current value'
    assert label.group(1).strip() == 'Seen', label.group(1)
    # And the newly-current option is the one ticked.
    ticked = re.findall(r'status-picker__option--active[^>]*>.*?option-label">([^<]+)<',
                        body, re.S)
    assert ticked == ['Seen'], ticked


# ── Filtering ────────────────────────────────────────────────────────────
@pytest.fixture
def mixed_pipeline(db, sample_job):
    seen = Resume.objects.create(
        job=sample_job, candidate_name='Already Reviewed',
        email='seen@example.com', final_score=70, seen_status='seen')
    unseen = Resume.objects.create(
        job=sample_job, candidate_name='Still To Review',
        email='unseen@example.com', final_score=60, seen_status='unseen')
    return sample_job, seen, unseen


@pytest.mark.django_db
@pytest.mark.parametrize('value,expected_key', [('unseen', 2), ('seen', 1)])
def test_the_filter_narrows_to_that_status(authenticated_client, mixed_pipeline,
                                           value, expected_key):
    job, seen, unseen = mixed_pipeline
    wanted = unseen if value == 'unseen' else seen
    other = seen if value == 'unseen' else unseen

    rows = authenticated_client.get(_pipeline(job, seen=value)).context['resumes']

    assert wanted in rows
    assert other not in rows


@pytest.mark.django_db
def test_no_filter_shows_everyone(authenticated_client, mixed_pipeline):
    job, seen, unseen = mixed_pipeline

    rows = authenticated_client.get(_pipeline(job)).context['resumes']

    assert seen in rows and unseen in rows


@pytest.mark.django_db
def test_a_junk_filter_value_falls_back_to_everyone(authenticated_client,
                                                    mixed_pipeline):
    job, seen, unseen = mixed_pipeline

    response = authenticated_client.get(_pipeline(job, seen='../etc/passwd'))

    assert response.status_code == 200
    assert response.context['seen_filter'] == 'all'
    assert seen in response.context['resumes']


@pytest.mark.django_db
def test_the_counts_describe_the_whole_pipeline_not_the_filtered_rows(
        authenticated_client, mixed_pipeline):
    """The chips say how much work is left. Recomputing them after the filter
    would make "Not seen 1" become "Not seen 0" the moment you clicked it."""
    job, seen, unseen = mixed_pipeline

    context = authenticated_client.get(_pipeline(job, seen='seen')).context

    assert context['unseen_count'] == 1
    assert context['seen_count'] == 1


@pytest.mark.django_db
def test_the_filter_combines_with_search_rather_than_replacing_it(
        authenticated_client, mixed_pipeline):
    job, seen, unseen = mixed_pipeline
    url = reverse('core:pipeline_search', kwargs={'job_slug': job.slug})

    # Both match the search term, so only the seen filter can separate them --
    # otherwise this passes with the filter removed entirely.
    Resume.objects.filter(pk__in=[seen.pk, unseen.pk]).update(
        candidate_name='Shared Searchname')

    both = authenticated_client.get(
        url, {'q': 'Shared', 'recruiter_status': 'all', 'seen': 'all'})
    assert len(both.context['resumes']) == 2, 'the search term must match both'

    narrowed = authenticated_client.get(
        url, {'q': 'Shared', 'recruiter_status': 'all', 'seen': 'unseen'})

    assert list(narrowed.context['resumes']) == [unseen]


# ── What the table shows ─────────────────────────────────────────────────
@pytest.mark.django_db
def test_the_table_offers_the_control_on_every_row(authenticated_client,
                                                   mixed_pipeline):
    job, seen, unseen = mixed_pipeline

    body = authenticated_client.get(_pipeline(job)).content.decode()

    assert body.count(f'/resumes/{seen.uuid}/seen-update/') >= 1
    assert body.count(f'/resumes/{unseen.uuid}/seen-update/') >= 1
    assert 'Reviewed' in body, 'the column header is missing'


@pytest.mark.django_db
def test_every_status_has_a_tone_the_stylesheet_knows(sample_resume):
    """The badge colour comes from a status-picker--<tone> class in the
    prebuilt stylesheet. A tone with no class renders an invisible dot."""
    from pathlib import Path

    css = Path('static/css/app.css').read_text()
    for value, _ in Resume.SEEN_STATUS_CHOICES:
        tone = Resume.SEEN_STATUS_TONES[value]
        assert f'status-picker__dot--{tone}' in css, f'{value} -> {tone} has no dot class'
        assert f'status-picker__option--{tone}' in css


# ── The pipeline's own counts ────────────────────────────────────────────
@pytest.mark.django_db
def test_a_search_that_matches_nobody_still_knows_the_job_has_applicants(
        authenticated_client, mixed_pipeline):
    """The template hides the whole table behind pipeline_stats.total.

    Counting after the search filter made that zero for a term nobody matched,
    so a job with applicants announced "No applicants yet" and the
    "No candidates match X" message the template already carries could never
    be reached.
    """
    job, seen, unseen = mixed_pipeline
    url = reverse('core:job_detail', kwargs={'slug': job.slug})

    response = authenticated_client.get(
        url, {'recruiter_status': 'all', 'q': 'zzznobodymatcheszzz'})
    body = response.content.decode()

    assert response.context['pipeline_stats']['total'] == 2, (
        'the snapshot must describe the whole pipeline, not the search'
    )
    assert 'No applicants yet' not in body
    assert 'No candidates match' in body


@pytest.mark.django_db
def test_the_seen_chips_ignore_the_search_too(authenticated_client, mixed_pipeline):
    job, seen, unseen = mixed_pipeline
    url = reverse('core:job_detail', kwargs={'slug': job.slug})

    context = authenticated_client.get(
        url, {'recruiter_status': 'all', 'q': 'Already'}).context

    assert context['unseen_count'] == 1
    assert context['seen_count'] == 1


@pytest.mark.django_db
def test_the_empty_row_spans_every_column(authenticated_client, mixed_pipeline):
    """Adding the Reviewed column widened the table; a stale colspan leaves the
    empty-state message boxed into part of the row."""
    import re

    job, seen, unseen = mixed_pipeline
    body = authenticated_client.get(
        reverse('core:job_detail', kwargs={'slug': job.slug}),
        {'recruiter_status': 'all', 'q': 'zzznobodymatcheszzz'}).content.decode()

    headers = len(re.findall(r'<th ', body))
    spans = {int(n) for n in re.findall(r'colspan="(\d+)"', body)}

    assert headers > 0
    assert spans == {headers}, f'colspan {spans} against {headers} columns'
