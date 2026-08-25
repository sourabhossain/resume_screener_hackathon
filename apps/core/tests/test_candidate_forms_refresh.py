"""The candidate page's form cards must follow a recruiter-status change.

Shortlisting sends the information form and Interviewing opens the two HR
instruments, so the cards go stale the moment the status control is swapped on
its own -- which is what made recruiters reload the page to see the buttons.
"""
import json

import pytest
from django.urls import reverse

from apps.core.models import Resume


@pytest.fixture
def candidate(db, sample_job):
    return Resume.objects.create(
        job=sample_job, candidate_name='Ayesha Rahman',
        email='ayesha@example.com', recruiter_status='shortlisted',
    )


@pytest.fixture
def hr_client(client, db, django_user_model):
    django_user_model.objects.create_user(
        username='hradmin', password='hrpass123', is_staff=True)
    client.login(username='hradmin', password='hrpass123')
    return client


def _forms_url(candidate):
    return reverse('core:resume_forms', kwargs={'uuid': candidate.uuid})


def _status_url(candidate):
    return reverse('core:resume_status_update', kwargs={'uuid': candidate.uuid})


def test_the_status_change_announces_itself(hr_client, candidate):
    """Without the trigger nothing tells the cards to re-render."""
    response = hr_client.post(
        _status_url(candidate),
        {'recruiter_status': 'interviewing', 'context': 'card'},
        HTTP_HX_REQUEST='true',
    )

    assert response.status_code == 200
    triggers = json.loads(response['HX-Trigger'])
    assert triggers['recruiter-status-changed'] == {'status': 'interviewing'}


def test_the_invite_toast_still_rides_along(hr_client, candidate):
    """Both triggers share one header; adding one must not drop the other."""
    candidate.recruiter_status = 'new'
    candidate.save()

    response = hr_client.post(
        _status_url(candidate),
        {'recruiter_status': 'shortlisted', 'context': 'card'},
        HTTP_HX_REQUEST='true',
    )

    triggers = json.loads(response['HX-Trigger'])
    assert 'recruiter-status-changed' in triggers
    assert triggers['toast']['level'] == 'success'


def test_the_cards_open_at_interviewing(hr_client, candidate):
    before = hr_client.get(_forms_url(candidate)).content.decode()
    assert 'Start verification' not in before
    assert 'Start mapping' not in before

    candidate.recruiter_status = 'interviewing'
    candidate.save()

    after = hr_client.get(_forms_url(candidate)).content.decode()
    assert 'Start verification' in after
    assert 'Start mapping' in after


def test_the_block_rewires_itself_after_a_swap(hr_client, candidate):
    """It replaces its own outerHTML, so the response must carry the wiring."""
    body = hr_client.get(_forms_url(candidate)).content.decode()

    assert 'id="candidate-forms"' in body
    assert 'hx-trigger="recruiter-status-changed from:body"' in body
    # <body> is hx-boosted with hx-target/hx-select="#main-content"; inheriting
    # those swapped this fragment over the whole page.
    assert 'hx-target="this"' in body
    assert 'hx-select="unset"' in body


def test_a_recruiter_gets_the_block_without_the_hr_cards(authenticated_client,
                                                         candidate):
    candidate.recruiter_status = 'interviewing'
    candidate.save()

    body = authenticated_client.get(_forms_url(candidate)).content.decode()

    assert 'Employee Information Form' in body
    assert 'HR Background Verification' not in body
    assert 'Candidate Mapping' not in body


def test_the_block_needs_a_login(client, candidate):
    response = client.get(_forms_url(candidate))
    assert response.status_code == 302
    assert '/login/' in response.url


def test_the_page_and_the_fragment_agree(hr_client, candidate):
    """Both build their context the same way, so they cannot drift."""
    candidate.recruiter_status = 'interviewing'
    candidate.save()

    page = hr_client.get(
        reverse('core:resume_detail', kwargs={'uuid': candidate.uuid})
    ).content.decode()
    fragment = hr_client.get(_forms_url(candidate)).content.decode()

    for marker in ('Employee Information Form', 'HR Background Verification',
                   'Candidate Mapping', 'Start verification', 'Start mapping'):
        assert (marker in page) == (marker in fragment), marker


def test_the_block_does_not_hand_its_wiring_to_the_links_inside(hr_client, candidate):
    """htmx attributes are inherited by descendants.

    Without hx-disinherit the boosted links in these cards ("View responses",
    "View record", "Continue") pick up the block's own hx-target="this" /
    hx-select="unset" and paste a whole page -- nav, footer and all -- inside the
    card instead of navigating to it.
    """
    body = hr_client.get(_forms_url(candidate)).content.decode()

    assert 'hx-disinherit=' in body
    disinherited = body.split('hx-disinherit="')[1].split('"')[0].split()
    for attr in ('hx-target', 'hx-select', 'hx-swap', 'hx-trigger'):
        assert attr in disinherited, attr


def test_the_cards_do_contain_boosted_links(hr_client, candidate):
    """Guards the test above: it only means something while the links exist."""
    candidate.recruiter_status = 'interviewing'
    candidate.save()

    body = hr_client.get(_forms_url(candidate)).content.decode()

    assert 'information-form/' in body
    assert 'hr-verification/' in body
    assert 'candidate-mapping/' in body
