"""The timed sitting: who may open it, when the clock starts, and how it ends.

The rule that matters is that the server owns the deadline. The page counts
down and submits itself, but a countdown can be paused in the devtools and a
tab can simply be closed, so nothing here trusts the browser.
"""
import json
from datetime import timedelta

import pytest
from django.core import mail
from django.urls import reverse
from django.utils import timezone

from apps.core.models import Resume
from apps.sei_assessment import scoring, services
from apps.sei_assessment.models import SEIAssessment


@pytest.fixture
def candidate(db, sample_job):
    return Resume.objects.create(
        job=sample_job, candidate_name='Ayesha Rahman',
        email='ayesha@example.com', recruiter_status='new')


@pytest.fixture
def sitting(db, candidate):
    assessment = SEIAssessment.objects.create(resume=candidate)
    otp = assessment.issue_otp()
    assessment.save()
    assessment.plain_otp = otp
    return assessment


def _entry(a):  return reverse('sei_assessment:entry', kwargs={'token': a.token})
def _verify(a): return reverse('sei_assessment:verify', kwargs={'token': a.token})
def _test(a):   return reverse('sei_assessment:test', kwargs={'token': a.token})
def _save(a):   return reverse('sei_assessment:save', kwargs={'token': a.token})


def _open(client, sitting):
    client.post(_verify(sitting), {'code': sitting.plain_otp})
    return client


@pytest.fixture
def hr_client(client, django_user_model):
    """The report is HR-only, so the plain authenticated_client cannot see it."""
    django_user_model.objects.create_user(
        username='sei-hr', password='hrpass123', is_staff=True)
    hr = type(client)(SERVER_NAME='testserver')
    hr.login(username='sei-hr', password='hrpass123')
    return hr


def _post(client, sitting, payload):
    return client.post(_save(sitting), data=json.dumps(payload),
                       content_type='application/json')


# ── getting in ───────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_the_link_alone_does_not_open_the_questions(client, sitting):
    assert 'verify' in client.get(_entry(sitting)).url
    assert 'verify' in client.get(_test(sitting)).url


@pytest.mark.django_db
def test_a_wrong_code_does_not_start_the_clock(client, sitting):
    client.post(_verify(sitting), {'code': '000000'})

    sitting.refresh_from_db()
    assert sitting.started_at is None


@pytest.mark.django_db
def test_the_right_code_opens_the_questions(client, sitting):
    response = client.post(_verify(sitting), {'code': sitting.plain_otp})

    assert response.status_code == 302
    assert client.get(_test(sitting)).status_code == 200


# ── the clock ────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_the_clock_starts_when_the_questions_are_opened_not_when_sent(client, sitting):
    """The invitation may sit unread for a day; that must not cost the
    candidate their fifteen minutes."""
    assert sitting.started_at is None

    _open(client, sitting).get(_test(sitting))

    sitting.refresh_from_db()
    assert sitting.started_at is not None
    expected = sitting.started_at + timedelta(minutes=SEIAssessment.TIME_LIMIT_MINUTES)
    assert abs((sitting.deadline_at - expected).total_seconds()) < 1


@pytest.mark.django_db
def test_reloading_the_page_does_not_restart_the_clock(client, sitting):
    """Otherwise a refresh every fourteen minutes buys unlimited time."""
    _open(client, sitting).get(_test(sitting))
    sitting.refresh_from_db()
    first_deadline = sitting.deadline_at

    client.get(_test(sitting))

    sitting.refresh_from_db()
    assert sitting.deadline_at == first_deadline


@pytest.mark.django_db
def test_two_tabs_opened_together_get_one_clock(client, sitting):
    """start_clock is a conditional UPDATE, so the second caller loses."""
    _open(client, sitting)
    first = SEIAssessment.objects.get(pk=sitting.pk)
    second = SEIAssessment.objects.get(pk=sitting.pk)

    assert first.start_clock() is True
    assert second.start_clock() is False

    sitting.refresh_from_db()
    assert second.deadline_at == sitting.deadline_at


# ── answering ────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_answers_save_as_they_are_picked(client, sitting):
    _open(client, sitting).get(_test(sitting))

    response = _post(client, sitting, {'answers': {'1': 3, '2': 1}})

    assert response.json()['status'] == 'saved'
    sitting.refresh_from_db()
    assert sitting.answers == {'1': 3, '2': 1}


@pytest.mark.django_db
def test_a_later_save_merges_rather_than_replaces(client, sitting):
    """Each save carries only what changed since the last one."""
    _open(client, sitting).get(_test(sitting))
    _post(client, sitting, {'answers': {'1': 3}})

    _post(client, sitting, {'answers': {'2': 2}})

    sitting.refresh_from_db()
    assert sitting.answers == {'1': 3, '2': 2}


@pytest.mark.django_db
@pytest.mark.parametrize('payload', [
    {'answers': {'1': 9}}, {'answers': {'1': -1}}, {'answers': {'99': 2}},
    {'answers': {'x': 2}}, {'answers': {'1': 'three'}},
])
def test_unusable_answers_are_dropped_not_stored(client, sitting, payload):
    _open(client, sitting).get(_test(sitting))

    _post(client, sitting, payload)

    sitting.refresh_from_db()
    assert sitting.answers == {}


@pytest.mark.django_db
def test_someone_without_the_code_cannot_answer(client, sitting):
    """The save endpoint is the one that writes; a link alone must not reach it."""
    response = _post(client, sitting, {'answers': {'1': 3}})

    assert response.status_code == 403
    sitting.refresh_from_db()
    assert sitting.answers == {}


# ── how it ends ──────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_submitting_closes_the_sitting(client, sitting):
    _open(client, sitting).get(_test(sitting))

    response = _post(client, sitting, {'answers': {'1': 3}, 'finish': True})

    assert response.json()['status'] == 'submitted'
    sitting.refresh_from_db()
    assert sitting.is_submitted is True
    assert sitting.auto_submitted is False


@pytest.mark.django_db
def test_answers_are_refused_once_the_clock_runs_out(client, sitting):
    """The browser is not the authority. Even with the countdown disabled, a
    late answer must not be accepted."""
    _open(client, sitting).get(_test(sitting))
    _post(client, sitting, {'answers': {'1': 3}})
    SEIAssessment.objects.filter(pk=sitting.pk).update(
        deadline_at=timezone.now() - timedelta(seconds=1))

    response = _post(client, sitting, {'answers': {'2': 3}})

    assert response.json()['status'] == 'closed'
    sitting.refresh_from_db()
    assert sitting.answers == {'1': 3}, 'a late answer was accepted'
    assert sitting.is_submitted is True
    assert sitting.auto_submitted is True


@pytest.mark.django_db
def test_an_abandoned_sitting_is_closed_by_the_sweep(client, sitting):
    """A candidate who closes the tab at minute three leaves an open paper.
    Without the sweep, HR would see "In progress" for someone long gone."""
    from apps.sei_assessment.tasks import close_expired_sittings

    _open(client, sitting).get(_test(sitting))
    _post(client, sitting, {'answers': {'1': 3, '2': 2}})
    SEIAssessment.objects.filter(pk=sitting.pk).update(
        deadline_at=timezone.now() - timedelta(minutes=1))

    assert close_expired_sittings() == 1

    sitting.refresh_from_db()
    assert sitting.is_submitted is True
    assert sitting.auto_submitted is True
    assert sitting.answers == {'1': 3, '2': 2}, 'the sweep lost the answers'


@pytest.mark.django_db
def test_the_sweep_leaves_a_running_sitting_alone(client, sitting):
    from apps.sei_assessment.tasks import close_expired_sittings

    _open(client, sitting).get(_test(sitting))

    assert close_expired_sittings() == 0
    sitting.refresh_from_db()
    assert sitting.is_submitted is False


@pytest.mark.django_db
def test_the_sweep_ignores_a_sitting_never_opened(sitting):
    """Nobody started it, so there is no clock to have run out."""
    from apps.sei_assessment.tasks import close_expired_sittings

    assert close_expired_sittings() == 0
    sitting.refresh_from_db()
    assert sitting.is_submitted is False


@pytest.mark.django_db
def test_a_finished_sitting_cannot_be_answered_again(client, sitting):
    _open(client, sitting).get(_test(sitting))
    _post(client, sitting, {'answers': {'1': 3}, 'finish': True})

    _post(client, sitting, {'answers': {'2': 3}})

    sitting.refresh_from_db()
    assert sitting.answers == {'1': 3}


@pytest.mark.django_db
def test_reopening_a_finished_sitting_shows_the_thank_you(client, sitting):
    _open(client, sitting).get(_test(sitting))
    _post(client, sitting, {'answers': {'1': 3}, 'finish': True})

    body = client.get(_entry(sitting)).content.decode()

    assert 'Thank you' in body


# ── the candidate never sees a score ─────────────────────────────────────
@pytest.mark.django_db
def test_no_page_the_candidate_can_reach_shows_a_result(client, sitting):
    _open(client, sitting).get(_test(sitting))
    _post(client, sitting, {'answers': {str(i): 3 for i in range(1, 49)},
                            'finish': True})
    sitting.refresh_from_db()
    total = str(sitting.result()['total_percent'])

    for url in (_entry(sitting), reverse('sei_assessment:done',
                                         kwargs={'token': sitting.token})):
        body = client.get(url).content.decode()
        assert total not in body
        for label in ('Self-awareness', 'Empathy', 'Social skills'):
            assert label not in body


# ── invitation ───────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_shortlisting_sends_the_assessment(authenticated_client, candidate):
    authenticated_client.post(
        reverse('core:resume_status_update', kwargs={'uuid': candidate.uuid}),
        {'recruiter_status': 'shortlisted'})

    assessment = SEIAssessment.objects.get(resume=candidate)
    assert assessment.invite_count == 1
    sent = [m for m in mail.outbox if 'Assessment for your application' in m.subject]
    assert len(sent) == 1
    assert str(assessment.token) in sent[0].body


@pytest.mark.django_db
def test_the_invitation_says_the_clock_has_not_started(authenticated_client, candidate):
    """A candidate who opens the email on a phone at a bus stop must be able to
    tell that reading it costs them nothing."""
    authenticated_client.post(
        reverse('core:resume_status_update', kwargs={'uuid': candidate.uuid}),
        {'recruiter_status': 'shortlisted'})

    body = [m for m in mail.outbox
            if 'Assessment for your application' in m.subject][0].body

    assert 'timer starts when you open the questions' in body
    assert str(SEIAssessment.TIME_LIMIT_MINUTES) in body


@pytest.mark.django_db
def test_a_candidate_without_an_email_is_reported_not_crashed(sample_job):
    resume = Resume.objects.create(job=sample_job, candidate_name='No Email')

    with pytest.raises(services.InviteError, match='no email address'):
        services.issue_invite(resume)


@pytest.mark.django_db
def test_a_completed_assessment_is_not_re_sent(candidate, sitting):
    SEIAssessment.objects.filter(pk=sitting.pk).update(
        is_submitted=True, answers={str(i): 2 for i in range(1, 49)})
    # Re-read: the fixture's resume still holds the sitting as it was, while a
    # request would load it fresh.
    fresh = Resume.objects.get(pk=candidate.pk)

    with pytest.raises(services.InviteError, match='already completed'):
        services.issue_invite(fresh, resend=True)


@pytest.mark.django_db
def test_a_sitting_already_under_way_is_not_restarted_by_accident(candidate, sitting):
    """Resending issues a new link and a new clock, so it must take the
    recruiter's explicit Resend rather than happening on a stray status change."""
    sitting.start_clock()
    fresh = Resume.objects.get(pk=candidate.pk)

    with pytest.raises(services.InviteError, match='already started'):
        services.issue_invite(fresh)


@pytest.mark.django_db
def test_the_code_is_never_stored_in_plaintext(sitting):
    assert sitting.otp_hash
    assert sitting.plain_otp not in sitting.otp_hash
    assert sitting.check_otp(sitting.plain_otp) is True


# ── an unscoreable paper ─────────────────────────────────────────────────
@pytest.mark.django_db
def test_too_few_answers_yields_no_score_and_asks_for_a_retake(
        hr_client, client, candidate, sitting):
    """Twenty of forty-eight is not a low score, it is no score."""
    _open(client, sitting).get(_test(sitting))
    _post(client, sitting, {'answers': {str(i): 2 for i in range(1, 21)},
                            'finish': True})

    sitting.refresh_from_db()
    assert sitting.is_submitted is True
    assert sitting.needs_retaking is True
    assert sitting.status_label == scoring.INVALID_LABEL
    assert sitting.result()['total_percent'] is None

    body = hr_client.get(
        reverse('sei_assessment:report', kwargs={'uuid': candidate.uuid})
    ).content.decode()
    assert 'Insufficient Responses' in body
    assert 'take it again' in body


@pytest.mark.django_db
def test_an_unscoreable_paper_can_be_re_issued(candidate, sitting):
    """Refusing to resend would leave the candidate with no way to finish."""
    sitting.answers = {str(i): 2 for i in range(1, 21)}
    sitting.is_submitted = True
    sitting.started_at = timezone.now() - timedelta(minutes=30)
    sitting.save()
    fresh = Resume.objects.get(pk=candidate.pk)

    services.issue_invite(fresh, resend=True)

    sitting.refresh_from_db()
    assert sitting.is_submitted is False
    assert sitting.answers == {}, 'the old partial answers must not linger'
    assert sitting.started_at is None, 'the clock has to start again'


@pytest.mark.django_db
def test_re_issuing_an_unscoreable_paper_takes_an_explicit_resend(candidate, sitting):
    """A stray status change must not silently wipe what was answered."""
    sitting.answers = {str(i): 2 for i in range(1, 21)}
    sitting.is_submitted = True
    sitting.save()
    fresh = Resume.objects.get(pk=candidate.pk)

    with pytest.raises(services.InviteError, match='did not answer enough'):
        services.issue_invite(fresh)

    sitting.refresh_from_db()
    assert sitting.answers != {}


@pytest.mark.django_db
def test_a_scoreable_paper_is_still_protected_from_resending(candidate, sitting):
    sitting.answers = {str(i): 2 for i in range(1, 49)}
    sitting.is_submitted = True
    sitting.save()
    fresh = Resume.objects.get(pk=candidate.pk)

    with pytest.raises(services.InviteError, match='already completed'):
        services.issue_invite(fresh, resend=True)


@pytest.mark.django_db
def test_the_sitting_is_fifteen_minutes(client, sitting):
    """Pinned as a literal, not read off the setting: the point is to catch the
    clock changing length, which a derived assertion would happily allow."""
    assert SEIAssessment.TIME_LIMIT_MINUTES == 15

    _open(client, sitting).get(_test(sitting))

    sitting.refresh_from_db()
    span = (sitting.deadline_at - sitting.started_at).total_seconds()
    assert abs(span - 15 * 60) < 1


@pytest.mark.django_db
def test_the_page_carries_the_instruction_wording(client, sitting):
    raw = _open(client, sitting).get(_test(sitting)).content.decode()
    body = ' '.join(raw.split())   # the copy wraps across lines in the template

    assert 'first and most natural reaction' in body
    assert 'Do not overthink the statements' in body
    assert 'recommended completion time 15 minutes' in body.lower()


# ── gaps found in review ─────────────────────────────────────────────────
@pytest.mark.django_db
def test_two_tabs_answering_at_once_do_not_lose_answers(client, sitting):
    """Both tabs merge onto the copy they loaded, so without a lock the later
    write drops the earlier answers -- and in a timed sitting there is no
    chance to enter them again."""
    _open(client, sitting).get(_test(sitting))

    _post(client, sitting, {'answers': {'1': 3}})
    _post(client, sitting, {'answers': {'2': 2}})

    sitting.refresh_from_db()
    assert sitting.answers == {'1': 3, '2': 2}


@pytest.mark.django_db
def test_a_save_merges_onto_whatever_is_in_the_database_not_what_was_loaded(
        client, sitting, monkeypatch):
    """The exact interleave, forced.

    Two sequential requests prove nothing here: the second fetches the row
    after the first has written, so it sees the answer either way. The race is
    another tab writing *between* this request loading the row and saving it,
    which is why the view re-reads under a lock instead of trusting the copy it
    fetched.
    """
    from apps.sei_assessment import services as sei_services

    _open(client, sitting).get(_test(sitting))
    fired = []
    real_finalise = sei_services.finalise_if_time_is_up

    def other_tab_writes_first(assessment):
        # Runs after the view has loaded the row and before it saves.
        if not fired:
            fired.append(True)
            SEIAssessment.objects.filter(pk=assessment.pk).update(answers={'5': 1})
        return real_finalise(assessment)

    monkeypatch.setattr(
        'apps.sei_assessment.views.services.finalise_if_time_is_up',
        other_tab_writes_first)

    _post(client, sitting, {'answers': {'6': 2}})

    assert fired, 'the interleave never ran'
    sitting.refresh_from_db()
    assert sitting.answers == {'5': 1, '6': 2}, 'the other tab answer was dropped'


@pytest.mark.django_db
def test_answering_steadily_for_the_whole_sitting_is_not_rate_limited(client, sitting):
    """The page flushes every five seconds, so a full fifteen minutes is about
    180 calls. A limit at that boundary would start refusing saves in the last
    minutes of the test."""
    _open(client, sitting).get(_test(sitting))

    codes = [_post(client, sitting, {'answers': {'1': 3}}).status_code
             for _ in range(260)]

    assert all(c == 200 for c in codes), f'blocked after {codes.index(429) if 429 in codes else "?"} saves'


@pytest.mark.django_db
def test_the_model_counts_answers_the_same_way_the_scorer_does(sitting):
    """is_valid_result gates whether HR sees a score at all, so a looser count
    here would report a paper the scorer refuses to score."""
    sitting.answers = {str(i): 2 for i in range(1, 45)}
    sitting.answers['45'] = 99          # out of range
    sitting.answers['46'] = 'x'         # not a number
    sitting.save(update_fields=['answers'])

    assert sitting.answered_count == 44
    assert sitting.answered_count == scoring.answered_items(sitting.answers)


@pytest.mark.django_db
def test_junk_in_the_stored_answers_cannot_fake_a_valid_paper(sitting):
    sitting.answers = {str(i): 2 for i in range(1, 44)}   # 43 real
    sitting.answers['44'] = 'x'                            # junk, not a 44th
    sitting.is_submitted = True
    sitting.save()

    assert sitting.answered_count == 43
    assert sitting.is_valid_result is False
    assert sitting.needs_retaking is True


@pytest.mark.django_db
def test_the_invitation_tells_the_candidate_what_makes_a_paper_count(
        authenticated_client, candidate):
    """Whether their answers are scored at all turns on finishing enough of
    it, so that cannot be a rule they only discover afterwards."""
    authenticated_client.post(
        reverse('core:resume_status_update', kwargs={'uuid': candidate.uuid}),
        {'recruiter_status': 'shortlisted'})

    raw = [m for m in mail.outbox
           if 'Assessment for your application' in m.subject][0].body
    body = ' '.join(raw.split())   # the template wraps across lines

    assert 'first and most natural reaction' in body
    assert 'Do not overthink the statements' in body
    assert f'fewer than {scoring.MINIMUM_VALID_ANSWERS} of 48' in body
    assert f'{SEIAssessment.TIME_LIMIT_MINUTES} minutes' in body
