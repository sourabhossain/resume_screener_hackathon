"""Integrity: what the page saw while a part was running, kept and shown to HR."""
import json
import re

import pytest
from django.urls import reverse

from apps.sei_assessment import integrity
from apps.sei_assessment.models import SEIAssessment
from apps.sei_assessment.tests.test_flow import (  # noqa: F401
    _begin, _open, _post, _test, candidate, hr_client, sitting)


def _client_id(response):
    state = json.loads(re.search(r'<script id="ap-state" type="application/json">(.+?)</script>',
                                 response.content.decode(), re.S).group(1))
    return state['client']


@pytest.fixture
def running(client, sitting):
    _open(client, sitting)
    page = _begin(client, sitting)
    return client, sitting, _client_id(page)


def test_unknown_or_malformed_events_are_dropped_and_the_rest_counted(sitting):
    integrity.record(sitting, [
        {'type': 'tab_hidden', 'at': 1}, {'type': 'tab_hidden'}, {'type': 'window_blur', 'seconds': 12.6},
        {'type': 'not_a_thing'}, 'junk', {'type': 'shortcut', 'detail': 'Ctrl+C' * 20},
    ])
    data = sitting.integrity
    assert data['counts'] == {'tab_hidden': 2, 'window_blur': 1, 'shortcut': 1}
    assert data['events'][2]['seconds'] == 13 and len(data['events'][3]['detail']) == 40


def test_a_flood_of_events_is_capped(sitting):
    for _ in range(20):
        integrity.record(sitting, [{'type': 'copy'}] * 100)
    assert sitting.integrity['counts']['copy'] == 20 * integrity.MAX_PER_REQUEST
    assert len(sitting.integrity['events']) == integrity.MAX_EVENTS


@pytest.mark.django_db
def test_the_question_page_gives_each_window_an_id_and_the_watermark(running):
    client, sitting, cid = running
    page = client.get(_test(sitting)).content.decode()
    assert cid and _client_id(client.get(_test(sitting))) != cid
    assert sitting.invitation.reference_id in page and 'class="ap-mark"' in page
    assert 'class="ap-gate"' in page


@pytest.mark.django_db
def test_events_arrive_with_the_autosave(running):
    client, sitting, cid = running
    r = _post(client, sitting, {'answers': {'1': 2}, 'client': cid,
                                'events': [{'type': 'tab_hidden', 'at': 1}, {'type': 'copy'}]})
    assert r.json()['status'] == 'saved'
    sitting.refresh_from_db()
    assert sitting.answers == {'1': 2}
    assert sitting.integrity['counts'] == {'tab_hidden': 1, 'copy': 1}


@pytest.mark.django_db
def test_a_window_replaced_by_a_newer_one_cannot_write_answers(running):
    client, sitting, old = running
    new = _client_id(client.get(_test(sitting)))
    stale = _post(client, sitting, {'answers': {'1': 3}, 'client': old, 'events': [{'type': 'second_tab'}]})
    assert stale.status_code == 409 and stale.json()['status'] == 'superseded'
    fresh = _post(client, sitting, {'answers': {'2': 1}, 'client': new})
    assert fresh.json()['status'] == 'saved'
    sitting.refresh_from_db()
    assert sitting.answers == {'2': 1}
    assert sitting.integrity['counts'] == {'reopened': 1, 'second_tab': 1}


@pytest.mark.django_db
def test_a_page_from_before_this_change_still_saves(running):
    client, sitting, _ = running
    assert _post(client, sitting, {'answers': {'1': 1}}).json()['status'] == 'saved'


@pytest.mark.django_db
def test_hr_sees_the_flags_on_the_report(running, hr_client):
    client, sitting, cid = running
    answers = {str(no): 1 for no in sitting.spec.items}
    _post(client, sitting, {'answers': answers, 'client': cid, 'finish': True,
                            'events': [{'type': 'tab_hidden'}, {'type': 'fullscreen_exit'}, {'type': 'shortcut', 'detail': 'Ctrl+C'}]})
    url = reverse('sei_assessment:report', kwargs={'uuid': sitting.resume.uuid, 'instrument': sitting.instrument})
    html = hr_client.get(url).content.decode()
    assert '3 flags recorded' in html and 'Switched tab or minimised the browser' in html and 'Ctrl+C' in html
    section = hr_client.get(reverse('core:resume_detail', kwargs={'uuid': sitting.resume.uuid})).content.decode()
    assert '3 integrity flags' in section


@pytest.mark.django_db
def test_a_reload_is_on_the_timeline_but_not_a_flag(running):
    client, sitting, _ = running
    client.get(_test(sitting))
    sitting.refresh_from_db()
    flags, rows, timeline = integrity.summary(sitting)
    assert flags == 0 and rows and timeline[0]['label'].startswith('Opened the part again')


def test_a_retake_starts_with_a_clean_record(sitting):
    integrity.record(sitting, [{'type': 'copy'}])
    sitting.reset()
    assert sitting.integrity == {} and 'integrity' in SEIAssessment.RESET_FIELDS


@pytest.mark.django_db
def test_candidates_are_told_before_they_start(client, sitting):
    _open(client, sitting)
    lobby = client.get(reverse('sei_assessment:entry', kwargs={'token': sitting.invitation.token})).content.decode()
    assert 'recorded and shown to the recruiter' in lobby


@pytest.mark.django_db
def test_the_flags_show_even_on_a_paper_too_short_to_score(running, hr_client):
    client, sitting, cid = running
    _post(client, sitting, {'answers': {'1': 1}, 'client': cid, 'finish': True, 'events': [{'type': 'tab_hidden'}]})
    url = reverse('sei_assessment:report', kwargs={'uuid': sitting.resume.uuid, 'instrument': sitting.instrument})
    html = hr_client.get(url).content.decode()
    assert '1 flag recorded' in html and 'Switched tab or minimised the browser' in html
