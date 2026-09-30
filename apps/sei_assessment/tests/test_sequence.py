"""One invitation for every assessment, taken one after another."""
import json
from datetime import timedelta

import pytest
from django.core import mail
from django.urls import reverse
from django.utils import timezone

from apps.core.models import Resume
from apps.sei_assessment import instruments, services
from apps.sei_assessment.models import AssessmentInvitation, SEIAssessment

SEI, PE = instruments.SEI, instruments.PE
SEI_LABEL = instruments.get(SEI).label
PE_LABEL = instruments.get(PE).label
# The order a candidate takes them: the short one first.
FIRST, SECOND = PE, SEI
FIRST_ITEMS = instruments.get(FIRST).total_items
SECOND_ITEMS = instruments.get(SECOND).total_items


def _assessment_mail():
    return [m for m in mail.outbox if 'assessment' in m.subject.lower()]


@pytest.fixture
def job(sample_job):
    sample_job.assessments = [SEI, PE]
    sample_job.save(update_fields=['assessments'])
    return sample_job


@pytest.fixture
def candidate(db, job):
    return Resume.objects.create(
        job=job, candidate_name='Farhan Kabir',
        email='farhan@example.com', recruiter_status='assessment')


@pytest.fixture
def invited(candidate):
    invitation = services.issue_invite(candidate)
    invitation.refresh_from_db()
    otp = invitation.issue_otp()
    invitation.save()
    invitation.plain_otp = otp
    mail.outbox = []
    return invitation


def _sitting(invitation, key):
    return SEIAssessment.objects.get(invitation=invitation, instrument=key)


def _url(name, invitation, **extra):
    return reverse(f'sei_assessment:{name}', kwargs={'token': invitation.token, **extra})


def _verify(client, invitation):
    return client.post(_url('verify', invitation), {'code': invitation.plain_otp})


def _save(client, invitation, key, payload):
    return client.post(_url('save', invitation, instrument=key),
                       data=json.dumps(payload), content_type='application/json')


def _begin(client, invitation, key):
    return client.post(_url('begin', invitation, instrument=key), {'consent': '1'}, follow=True)


def _finish(client, invitation, key, count):
    _begin(client, invitation, key)
    return _save(client, invitation, key, {
        'answers': {str(i): 1 for i in range(1, count + 1)}, 'finish': True})


def _flat(response):
    return ' '.join(response.content.decode().split())


@pytest.fixture
def hr_client(client, django_user_model):
    django_user_model.objects.create_user(
        username='seq-hr', password='hrpass123', is_staff=True)
    hr = type(client)(SERVER_NAME='testserver')
    hr.login(username='seq-hr', password='hrpass123')
    return hr


# ── the invitation ───────────────────────────────────────────────────────
@pytest.mark.django_db
def test_one_email_one_link_one_code_for_both(candidate):
    mail.outbox = []

    invitation = services.issue_invite(candidate)

    sent = _assessment_mail()
    assert len(sent) == 1
    assert sent[0].subject.startswith('Your assessments')
    body = ' '.join(sent[0].body.split())
    assert str(invitation.token) in body
    assert body.index(f'Part 1 — {FIRST_ITEMS} questions') < body.index(f'Part 2 — {SECOND_ITEMS} statements')
    assert 'one at a time' in body
    assert sent[0].alternatives, 'the HTML part is missing'
    assert AssessmentInvitation.objects.filter(resume=candidate).count() == 1
    assert candidate.sittings.count() == 2


@pytest.mark.django_db
def test_a_single_assessment_keeps_its_own_subject(job, candidate):
    job.assessments = [PE]
    job.save(update_fields=['assessments'])
    mail.outbox = []

    services.issue_invite(candidate)

    [sent] = _assessment_mail()
    assert sent.subject.startswith('Your assessment for')
    assert 'one at a time' not in sent.body


@pytest.mark.django_db
def test_moving_to_assessment_twice_does_not_send_twice(authenticated_client, job):
    resume = Resume.objects.create(
        job=job, candidate_name='Rafi', email='rafi@example.com',
        recruiter_status='new')
    url = reverse('core:resume_status_update', kwargs={'uuid': resume.uuid})
    mail.outbox = []

    authenticated_client.post(url, {'recruiter_status': 'assessment'})
    authenticated_client.post(url, {'recruiter_status': 'phone_screen'})
    authenticated_client.post(url, {'recruiter_status': 'assessment'})

    assert len(_assessment_mail()) == 1


# ── getting in ───────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_the_code_leads_to_the_overview_not_straight_into_a_clock(client, invited):
    response = _verify(client, invited)

    assert response.url == _url('entry', invited)
    page = _flat(client.get(response.url))
    assert 'Start Part 1' in page
    assert 'Opens after Part 1' in page
    assert not SEIAssessment.objects.filter(
        invitation=invited, started_at__isnull=False).exists()


# ── the order ────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_the_first_part_opens_first_and_only_it_starts(client, invited):
    _verify(client, invited)

    page = _flat(_begin(client, invited, FIRST))

    assert 'Part 1 of 2' in page
    assert 'Submit Part 1' in page
    assert _sitting(invited, FIRST).has_started
    assert not _sitting(invited, SECOND).has_started


@pytest.mark.django_db
def test_a_locked_part_cannot_be_written_to(client, invited):
    _verify(client, invited)
    _begin(client, invited, FIRST)

    response = _save(client, invited, SECOND, {'answers': {'1': 2}})

    assert response.status_code == 409
    assert _sitting(invited, SECOND).answers == {}


@pytest.mark.django_db
def test_submitting_the_first_opens_the_second_without_starting_its_clock(
        client, invited):
    _verify(client, invited)
    _finish(client, invited, FIRST, FIRST_ITEMS)

    page = _flat(client.get(_url('entry', invited)))

    assert 'Part 1 complete' in page
    assert 'Start Part 2' in page
    assert not _sitting(invited, SECOND).has_started

    page = _flat(_begin(client, invited, SECOND))
    assert 'Part 2 of 2' in page
    assert 'Submit assessment' in page
    assert 'Submit Part 2' not in page
    assert _sitting(invited, SECOND).has_started


@pytest.mark.django_db
def test_a_stale_tab_on_a_closed_part_cannot_write_into_the_next(client, invited):
    _verify(client, invited)
    _finish(client, invited, FIRST, FIRST_ITEMS)
    _begin(client, invited, SECOND)

    response = _save(client, invited, FIRST, {'answers': {'3': 2}})

    assert response.json()['status'] == 'closed'
    assert _sitting(invited, SECOND).answers == {}


@pytest.mark.django_db
def test_a_part_whose_time_ran_out_unlocks_the_next_without_the_sweep(
        client, invited):
    _verify(client, invited)
    _begin(client, invited, FIRST)
    _save(client, invited, FIRST, {'answers': {'1': 2}})
    SEIAssessment.objects.filter(invitation=invited, instrument=FIRST).update(
        deadline_at=timezone.now() - timedelta(seconds=SEIAssessment.SAVE_GRACE_SECONDS + 1))

    page = _flat(client.get(_url('entry', invited)))

    first = _sitting(invited, FIRST)
    assert first.is_submitted and first.auto_submitted
    assert 'Your time ran out' in page
    assert 'Start Part 2' in page


@pytest.mark.django_db
def test_returning_mid_part_goes_straight_back_to_the_questions(client, invited):
    _verify(client, invited)
    _begin(client, invited, FIRST)

    response = client.get(_url('entry', invited))

    assert response.status_code == 302
    assert response.url == _url('test', invited)


@pytest.mark.django_db
def test_both_done_thanks_them_once_for_everything(client, invited):
    _verify(client, invited)
    _finish(client, invited, FIRST, FIRST_ITEMS)
    _finish(client, invited, SECOND, SECOND_ITEMS)

    for name in ('entry', 'done', 'test'):
        page = _flat(client.get(_url(name, invited)))
        assert 'Both parts are recorded' in page, name
        assert invited.reference_id in page, name


@pytest.mark.django_db
def test_done_before_the_end_sends_them_back_to_the_next_part(client, invited):
    _verify(client, invited)
    _finish(client, invited, FIRST, FIRST_ITEMS)

    response = client.get(_url('done', invited))

    assert response.url == _url('entry', invited)


# ── links sent before parts were grouped ─────────────────────────────────
@pytest.mark.django_db
def test_an_old_per_part_link_lands_on_the_one_invitation(client, invited):
    second = _sitting(invited, SECOND)

    response = client.get(reverse('sei_assessment:entry', kwargs={'token': second.token}))

    assert response.url == _url('entry', invited)


@pytest.mark.django_db
def test_an_old_page_still_saves_to_its_own_part(client, invited):
    _verify(client, invited)
    _begin(client, invited, FIRST)
    first = _sitting(invited, FIRST)

    client.post(reverse('sei_assessment:save_legacy', kwargs={'token': first.token}),
                data=json.dumps({'answers': {'2': 3}}),
                content_type='application/json')

    assert _sitting(invited, FIRST).answers == {'2': 3}


@pytest.mark.django_db
def test_an_unknown_token_is_still_a_dead_link(client):
    import uuid
    response = client.get(reverse('sei_assessment:entry', kwargs={'token': uuid.uuid4()}))
    assert response.status_code == 404


# ── resending ────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_resending_after_part_one_asks_only_for_what_is_left(client, invited):
    _verify(client, invited)
    _finish(client, invited, FIRST, FIRST_ITEMS)

    services.issue_invite(invited.resume, resend=True)

    [sent] = _assessment_mail()
    assert sent.subject.startswith('Your assessments')
    body = ' '.join(sent.body.split())
    assert 'already completed Part 1' in body
    assert f'the remaining part of your assessment: {SECOND_ITEMS} statements' in body
    assert SEI_LABEL not in body and PE_LABEL not in body
    assert _sitting(invited, FIRST).is_submitted


@pytest.mark.django_db
def test_a_retake_clears_only_the_unscoreable_part(client, invited):
    _verify(client, invited)
    _finish(client, invited, FIRST, 10)
    _finish(client, invited, SECOND, SECOND_ITEMS)
    assert _sitting(invited, FIRST).needs_retaking

    services.issue_invite(invited.resume, resend=True)

    first, second = _sitting(invited, FIRST), _sitting(invited, SECOND)
    assert not first.is_submitted and first.answers == {}
    assert second.is_submitted and second.is_valid_result


@pytest.mark.django_db
def test_an_assessment_added_to_the_job_later_joins_the_same_invitation(
        job, candidate):
    job.assessments = [FIRST]
    job.save(update_fields=['assessments'])
    invitation = services.issue_invite(candidate)
    job.assessments = [FIRST, SECOND]
    job.save(update_fields=['assessments'])

    again = services.issue_invite(candidate, resend=True)

    assert again.pk == invitation.pk
    assert {s.instrument for s in again.sittings.all()} == {FIRST, SECOND}


@pytest.mark.django_db
def test_a_dropped_part_never_opened_is_not_put_in_front_of_them(job, invited):
    job.assessments = [FIRST]
    job.save(update_fields=['assessments'])

    services.issue_invite(invited.resume, resend=True)

    assert [s.instrument for s in invited.ordered_sittings()] == [FIRST]


@pytest.mark.django_db
def test_everything_done_refuses_a_resend(client, invited):
    _verify(client, invited)
    _finish(client, invited, FIRST, FIRST_ITEMS)
    _finish(client, invited, SECOND, SECOND_ITEMS)

    with pytest.raises(services.InviteError, match='already completed'):
        services.issue_invite(invited.resume, resend=True)


@pytest.mark.django_db
def test_a_new_code_does_not_throw_out_a_candidate_mid_part(client, invited):
    _verify(client, invited)
    _begin(client, invited, FIRST)

    services.issue_invite(invited.resume, resend=True)

    response = _save(client, invited, FIRST, {'answers': {'1': 2}})
    assert response.json()['status'] == 'saved'


@pytest.mark.django_db
def test_a_new_code_does_revoke_a_session_with_nothing_running(client, invited):
    _verify(client, invited)

    services.issue_invite(invited.resume, resend=True)

    assert 'verify' in client.get(_url('entry', invited)).url


# ── HR ───────────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_hr_sends_both_with_one_click(hr_client, candidate):
    mail.outbox = []

    response = hr_client.post(
        reverse('sei_assessment:send', kwargs={'uuid': candidate.uuid}))

    assert response.status_code == 302
    assert len(_assessment_mail()) == 1
    assert candidate.sittings.count() == 2


@pytest.mark.django_db
def test_the_candidate_page_offers_one_send_button_not_one_per_part(
        hr_client, invited):
    page = hr_client.get(
        reverse('core:resume_detail', kwargs={'uuid': invited.resume.uuid})
    ).content.decode()

    send_url = reverse('sei_assessment:send', kwargs={'uuid': invited.resume.uuid})
    assert page.count(send_url) == 1
    assert 'Waiting' in page


# ── found in review ──────────────────────────────────────────────────────
@pytest.mark.django_db
def test_opening_the_questions_page_never_starts_a_clock(client, invited):
    _verify(client, invited)

    response = client.get(_url('test', invited))

    assert response.url == _url('entry', invited)
    assert not SEIAssessment.objects.filter(
        invitation=invited, started_at__isnull=False).exists()


@pytest.mark.django_db
def test_reloading_after_part_one_times_out_does_not_start_part_two(client, invited):
    _verify(client, invited)
    _begin(client, invited, FIRST)
    SEIAssessment.objects.filter(invitation=invited, instrument=FIRST).update(
        deadline_at=timezone.now() - timedelta(seconds=SEIAssessment.SAVE_GRACE_SECONDS + 1))

    response = client.get(_url('test', invited))

    assert response.url == _url('entry', invited)
    assert not _sitting(invited, SECOND).has_started


@pytest.mark.django_db
def test_beginning_a_part_that_is_not_open_is_refused(client, invited):
    _verify(client, invited)

    client.post(_url('begin', invited, instrument=SECOND))

    assert not _sitting(invited, SECOND).has_started
    assert not _sitting(invited, FIRST).has_started


@pytest.mark.django_db
def test_a_running_part_stays_current_even_after_an_earlier_one_reopens(invited):
    SEIAssessment.objects.filter(invitation=invited, instrument=FIRST).update(
        is_submitted=True, answers={'1': 1})
    _sitting(invited, SECOND).start_clock()
    SEIAssessment.objects.filter(invitation=invited, instrument=FIRST).update(
        is_submitted=False, answers={})

    assert invited.current_sitting().instrument == SECOND


@pytest.mark.django_db
def test_a_retake_is_refused_while_another_part_is_running(client, invited):
    _verify(client, invited)
    _finish(client, invited, FIRST, 10)
    _begin(client, invited, SECOND)

    with pytest.raises(services.InviteError, match='right now'):
        services.issue_invite(invited.resume, resend=True)

    first = _sitting(invited, FIRST)
    assert first.is_submitted and first.answers, 'the paper was reset under a running clock'


@pytest.mark.django_db
def test_an_unscoreable_paper_the_job_no_longer_asks_for_is_kept(
        client, job, invited):
    _verify(client, invited)
    _finish(client, invited, FIRST, 10)
    job.assessments = [SECOND]
    job.save(update_fields=['assessments'])

    services.issue_invite(invited.resume, resend=True)

    first = _sitting(invited, FIRST)
    assert first.is_submitted and first.answers


@pytest.mark.django_db
def test_a_page_open_at_deploy_on_the_shared_token_still_saves(client, invited):
    _verify(client, invited)
    _begin(client, invited, FIRST)

    response = client.post(
        reverse('sei_assessment:save_legacy', kwargs={'token': invited.token}),
        data=json.dumps({'answers': {'4': 1}}), content_type='application/json')

    assert response.json()['status'] == 'saved'
    assert _sitting(invited, FIRST).answers == {'4': 1}


@pytest.mark.django_db
def test_a_session_verified_on_an_old_part_link_stays_verified(client, invited):
    AssessmentInvitation.objects.filter(pk=invited.pk).update(
        otp_verified_at=timezone.now())
    second = _sitting(invited, SECOND)
    session = client.session
    session[f'sei_verified:{second.token}'] = True
    session.save()

    response = client.get(_url('entry', invited))

    assert response.status_code == 200
    assert 'Start Part 1' in _flat(response)


@pytest.mark.django_db
def test_the_old_task_does_not_resend_an_invitation_just_sent(candidate):
    from apps.sei_assessment.tasks import send_sei_invite
    invitation = services.issue_invite(candidate)
    mail.outbox = []

    for sitting in invitation.sittings.all():
        send_sei_invite(sitting.pk)

    assert _assessment_mail() == []
