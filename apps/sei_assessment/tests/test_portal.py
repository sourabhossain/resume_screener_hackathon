"""The candidate portal: consent, anonymous parts, and what each screen shows."""
import json
import re
import uuid

import pytest
from django.core import mail
from django.urls import reverse

from apps.core.models import Resume
from apps.sei_assessment import instruments, services
from apps.sei_assessment.models import AssessmentInvitation, SEIAssessment

SEI, PE = instruments.SEI, instruments.PE
# Item 41 itself says "emotional", so the check is for the names, not words.
NAME_GIVEAWAYS = [
    *(spec.label.lower() for spec in instruments.all_instruments()),
    'emotional intelligence', 'effectiveness',
]


def _giveaways(html):
    found = [name for name in NAME_GIVEAWAYS if name in html.lower()]
    found += re.findall(r'\b(?:SEI|PE)\b', html)
    found += re.findall(r'/(?:sei|pe)/', html)
    return found


def _invite(job, keys, name='Tania Akter'):
    job.assessments = keys
    job.save(update_fields=['assessments'])
    resume = Resume.objects.create(job=job, candidate_name=name,
                                   email=f'{uuid.uuid4().hex[:8]}@example.com',
                                   recruiter_status='shortlisted')
    invitation = services.issue_invite(resume)
    invitation.refresh_from_db()
    invitation.plain_otp = invitation.issue_otp()
    invitation.save()
    return invitation


def _url(name, invitation, **extra):
    return reverse(f'sei_assessment:{name}', kwargs={'token': invitation.token, **extra})


def _enter(client, invitation):
    client.post(_url('verify', invitation), {'code': invitation.plain_otp})
    return client


def _part(invitation, key):
    return SEIAssessment.objects.get(invitation=invitation, instrument=key)


def _begin(client, invitation, key, consent=True):
    data = {'consent': '1'} if consent else {}
    return client.post(_url('begin_part', invitation, part=_part(invitation, key).token),
                       data, follow=True)


def _save(client, invitation, key, payload):
    return client.post(_url('save_part', invitation, part=_part(invitation, key).token),
                       data=json.dumps(payload), content_type='application/json')


def _finish(client, invitation, key):
    _begin(client, invitation, key)
    total = instruments.get(key).total_items
    return _save(client, invitation, key, {
        'answers': {str(i): 1 for i in range(1, total + 1)}, 'finish': True})


@pytest.fixture
def both(sample_job):
    return _invite(sample_job, [SEI, PE])


# ── consent ──────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_no_clock_starts_without_consent(client, both):
    _enter(client, both)

    response = _begin(client, both, PE, consent=False)

    assert not _part(both, PE).has_started
    both.refresh_from_db()
    assert both.consented_at is None
    assert 'Accept the consent statement to continue' in response.content.decode()


@pytest.mark.django_db
def test_consent_is_recorded_once_and_not_asked_again(client, both):
    _enter(client, both)
    _finish(client, both, PE)
    both.refresh_from_db()
    first = both.consented_at

    page = client.get(_url('entry', both)).content.decode()
    _begin(client, both, SEI, consent=False)

    assert first is not None
    assert 'name="consent"' not in page
    assert _part(both, SEI).has_started
    both.refresh_from_db()
    assert both.consented_at == first


@pytest.mark.django_db
def test_a_part_already_running_is_never_blocked_for_consent(client, both):
    _enter(client, both)
    _part(both, PE).start_clock()

    response = client.get(_url('test', both))

    assert response.status_code == 200
    assert _save(client, both, PE, {'answers': {'1': 2}}).json()['status'] == 'saved'


@pytest.mark.django_db
def test_a_candidate_who_finished_part_one_before_consent_existed_is_asked_before_part_two(
        client, both):
    _enter(client, both)
    _finish(client, both, PE)
    AssessmentInvitation.objects.filter(pk=both.pk).update(consented_at=None)

    page = client.get(_url('entry', both)).content.decode()

    assert 'Part 1 complete' in page
    assert 'name="consent"' in page


@pytest.mark.django_db
def test_the_practice_answer_is_not_saved(client, both):
    _enter(client, both)

    client.post(_url('begin_part', both, part=_part(both, PE).token),
                {'consent': '1', 'practice': '3'})

    assert _part(both, PE).answers == {}


# ── the test is never named ──────────────────────────────────────────────
@pytest.mark.django_db
@pytest.mark.parametrize('keys', [[SEI, PE], [SEI], [PE]])
def test_no_candidate_screen_names_the_test(client, sample_job, keys):
    invitation = _invite(sample_job, keys)
    pages = [client.get(_url('verify', invitation)).content.decode()]
    _enter(client, invitation)

    for key in invitation_order(invitation):
        pages.append(client.get(_url('entry', invitation)).content.decode())
        pages.append(_begin(client, invitation, key).content.decode())
        _save(client, invitation, key, {'finish': True, 'answers': {
            str(i): 1 for i in range(1, instruments.get(key).total_items + 1)}})
    pages.append(client.get(_url('entry', invitation)).content.decode())

    for html in pages:
        assert _giveaways(html) == []
    assert 'Assessment submitted' in pages[-1]


def invitation_order(invitation):
    return [s.instrument for s in invitation.ordered_sittings()]


@pytest.mark.django_db
@pytest.mark.parametrize('keys', [[SEI, PE], [SEI], [PE]])
def test_the_email_never_names_the_test(sample_job, keys):
    mail.outbox = []

    _invite(sample_job, keys)

    [sent] = [m for m in mail.outbox if 'assessment' in m.subject.lower()]
    assert _giveaways(sent.subject) == []
    assert _giveaways(sent.body) == []
    assert _giveaways(sent.alternatives[0][0]) == []
    assert 'jobs@sslwireless.com' in sent.body


# ── order and screens ────────────────────────────────────────────────────
@pytest.mark.django_db
def test_part_one_is_the_short_one(both):
    assert invitation_order(both) == [PE, SEI]


@pytest.mark.django_db
def test_one_question_a_screen_then_five_statements_a_screen(client, both):
    _enter(client, both)

    first = _begin(client, both, PE)
    assert len(first.context['pages']) == 15
    assert all(len(page) == 1 for page in first.context['pages'])
    assert first.context['state']['perPage'] == 1

    _save(client, both, PE, {'finish': True, 'answers': {str(i): 2 for i in range(1, 16)}})
    second = _begin(client, both, SEI)
    assert [len(page) for page in second.context['pages']] == [5] * 9 + [3]


@pytest.mark.django_db
def test_the_options_keep_the_instrument_scale_in_order(client, both):
    _enter(client, both)

    scale = _begin(client, both, PE).context['scale']

    assert [s['value'] for s in scale] == [0, 1, 2, 3, 4]
    assert scale[0]['full'] == 'Not at all characteristic'
    assert scale[-1]['full'] == 'Most characteristic'
    assert [s['letter'] for s in scale] == list('ABCDE')


@pytest.mark.django_db
def test_a_resumed_part_comes_back_with_its_answers(client, both):
    _enter(client, both)
    _begin(client, both, PE)
    _save(client, both, PE, {'answers': {'1': 4, '2': 0}})

    state = client.get(_url('test', both)).context['state']

    assert state['answers'] == {'1': 4, '2': 0}
    assert state['saveUrl'] == _url('save_part', both, part=_part(both, PE).token)


@pytest.mark.django_db
def test_a_part_key_from_another_invitation_is_refused(client, sample_job, both):
    other = _invite(sample_job, [SEI, PE], name='Someone Else')
    _enter(client, both)
    _begin(client, both, PE)

    response = client.post(
        _url('save_part', both, part=_part(other, PE).token),
        data=json.dumps({'answers': {'1': 2}}), content_type='application/json')

    assert response.status_code == 404
    assert _part(other, PE).answers == {}
    assert _part(both, PE).answers == {}


@pytest.mark.django_db
def test_beginning_a_later_part_by_its_key_is_refused(client, both):
    _enter(client, both)

    _begin(client, both, SEI)

    assert not _part(both, SEI).has_started
    assert not _part(both, PE).has_started


@pytest.mark.django_db
def test_a_retake_of_part_one_after_part_two_is_a_fresh_welcome(client, both):
    _enter(client, both)
    _begin(client, both, PE)
    _save(client, both, PE, {'finish': True, 'answers': {'1': 1}})
    _finish(client, both, SEI)
    services.issue_invite(both.resume, resend=True)
    both.refresh_from_db()
    otp = both.issue_otp()
    both.save()
    client.post(_url('verify', both), {'code': otp})

    response = client.get(_url('entry', both))

    assert response.context['mode'] == 'welcome'
    assert 'Completed' in response.content.decode()


# ── the end ──────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_the_last_screen_quotes_a_reference_not_the_token(client, both):
    _enter(client, both)
    _finish(client, both, PE)
    _finish(client, both, SEI)

    html = client.get(_url('entry', both)).content.decode()

    assert both.reference_id == f'SSLW-ASM-{both.pk:06d}'
    assert both.reference_id in html
    assert 'Thank you, Tania' in html
    assert 'working days' not in html
    assert 'jobs@sslwireless.com' in html


@pytest.mark.django_db
def test_hr_sees_the_reference_and_when_consent_was_given(client, django_user_model, both):
    _enter(client, both)
    _begin(client, both, PE)
    django_user_model.objects.create_user(username='portal-hr', password='p', is_staff=True)
    hr = type(client)()
    hr.login(username='portal-hr', password='p')

    html = hr.get(reverse('core:resume_detail', kwargs={'uuid': both.resume.uuid})).content.decode()

    assert both.reference_id in html
    assert 'consent given' in html


@pytest.mark.django_db
def test_a_part_finished_under_the_old_order_is_counted_as_done(client, both):
    from django.utils import timezone
    SEIAssessment.objects.filter(invitation=both, instrument=SEI).update(
        answers={str(i): 1 for i in range(1, 49)}, started_at=timezone.now(),
        deadline_at=timezone.now(), is_submitted=True, submitted_at=timezone.now())
    _enter(client, both)

    response = client.get(_url('entry', both))
    html = ' '.join(response.content.decode().split())

    assert response.context['mode'] == 'welcome'
    assert 'You have one part left to complete.' in html
    assert 'Complete the remaining part by' in html
    assert [s['state'] for s in response.context['steps']] == ['active', '', 'done', '']


# ── found in the pre-live review ─────────────────────────────────────────
def _move_deadline(invitation, key, seconds):
    from datetime import timedelta
    from django.utils import timezone
    SEIAssessment.objects.filter(invitation=invitation, instrument=key).update(
        deadline_at=timezone.now() + timedelta(seconds=seconds))


@pytest.mark.django_db
def test_the_final_save_sent_at_zero_is_kept(client, both):
    _enter(client, both)
    _begin(client, both, PE)
    _save(client, both, PE, {'answers': {str(i): 2 for i in range(1, 15)}})
    _move_deadline(both, PE, -1)

    reply = _save(client, both, PE, {'answers': {'15': 4}, 'finish': True}).json()

    part = _part(both, PE)
    assert reply['status'] == 'submitted'
    assert part.answers['15'] == 4 and part.is_valid_result
    assert part.auto_submitted


@pytest.mark.django_db
def test_nothing_is_written_once_the_grace_is_over(client, both):
    _enter(client, both)
    _begin(client, both, PE)
    _move_deadline(both, PE, -(SEIAssessment.SAVE_GRACE_SECONDS + 1))

    reply = _save(client, both, PE, {'answers': {'1': 4}}).json()

    part = _part(both, PE)
    assert reply['status'] == 'closed'
    assert part.is_submitted and part.auto_submitted and part.answers == {}


@pytest.mark.django_db
def test_the_sweep_leaves_a_part_alone_during_the_grace(client, both):
    from apps.sei_assessment.tasks import close_expired_sittings
    _enter(client, both)
    _begin(client, both, PE)
    _move_deadline(both, PE, -1)

    assert close_expired_sittings() == 0
    _move_deadline(both, PE, -(SEIAssessment.SAVE_GRACE_SECONDS + 1))
    assert close_expired_sittings() == 1


@pytest.mark.django_db
def test_a_running_part_outlives_the_link_expiring(client, both):
    from datetime import timedelta
    from django.utils import timezone
    _enter(client, both)
    _begin(client, both, PE)
    AssessmentInvitation.objects.filter(pk=both.pk).update(
        token_expires_at=timezone.now() - timedelta(minutes=1))

    assert client.get(_url('test', both)).status_code == 200
    reply = _save(client, both, PE, {'answers': {str(i): 1 for i in range(1, 16)},
                                     'finish': True}).json()
    assert reply['status'] == 'submitted'
    assert 'This link has expired' in client.get(_url('entry', both)).content.decode()
    assert not _part(both, SEI).has_started


@pytest.mark.django_db
def test_without_the_code_the_closed_pages_do_not_name_the_candidate(client, both):
    _enter(client, both)
    _finish(client, both, PE)
    _finish(client, both, SEI)

    stranger = type(client)()
    html = stranger.get(_url('done', both)).content.decode()

    assert 'Assessment submitted' in html
    assert 'Tania' not in html
    assert both.reference_id not in html


@pytest.mark.django_db
def test_the_second_part_running_first_is_not_called_the_last(client, both):
    from django.utils import timezone
    _enter(client, both)
    _part(both, SEI).start_clock()

    response = client.get(_url('test', both))

    assert response.context['part_number'] == 2
    assert response.context['is_last_part'] is False
    assert 'Submit Part 2' in response.content.decode()
    assert [s['state'] for s in response.context['steps']] == ['done', '', 'active', '']


@pytest.mark.django_db
def test_an_old_part_token_shares_the_invitation_code_allowance(rf, both):
    from django.urls import resolve
    from apps.sei_assessment.views import _rate_key
    legacy = reverse('sei_assessment:verify', kwargs={'token': _part(both, SEI).token})
    request = rf.post(legacy)
    request.resolver_match = resolve(legacy)

    assert _rate_key(None, request) == str(both.token)


@pytest.mark.django_db
def test_hr_numbers_the_parts_as_the_candidate_sees_them(client, django_user_model, sample_job, both):
    _enter(client, both)
    _finish(client, both, PE)
    sample_job.assessments = [SEI]
    sample_job.save(update_fields=['assessments'])
    django_user_model.objects.create_user(username='portal-hr2', password='p', is_staff=True)
    hr = type(client)()
    hr.login(username='portal-hr2', password='p')

    response = hr.get(reverse('core:resume_detail', kwargs={'uuid': both.resume.uuid}))

    rows = response.context['job_assessments']
    assert [(r['spec'].key, r['part']) for r in rows] == [(PE, 1), (SEI, 2)]


@pytest.mark.django_db
def test_a_submit_the_timer_sent_is_recorded_as_time_expired(client, both):
    _enter(client, both)
    _begin(client, both, PE)

    _save(client, both, PE, {'answers': {'1': 1}, 'finish': True, 'timed_out': True})

    assert _part(both, PE).auto_submitted


@pytest.mark.django_db
def test_the_hr_report_explains_the_category_as_the_recruiter_guide_does(client, django_user_model, both):
    _enter(client, both)
    _begin(client, both, PE)
    # Totals 11 / 12 / 15 read Low / High / High.
    answers = {'1': 2, '4': 2, '7': 3, '10': 2, '13': 2,
               '2': 2, '5': 2, '8': 2, '11': 2, '14': 4,
               '3': 1, '6': 1, '9': 3, '12': 1, '15': 1}
    _save(client, both, PE, {'answers': answers, 'finish': True})
    django_user_model.objects.create_user(username='portal-hr3', password='p', is_staff=True)
    hr = type(client)()
    hr.login(username='portal-hr3', password='p')

    response = hr.get(reverse('sei_assessment:report', kwargs={'uuid': both.resume.uuid, 'instrument': PE}))
    html = ' '.join(response.content.decode().split())

    result = response.context['result']
    assert result['category'] == 'Secretive' and result['pattern'] == 'Low / High / High'
    assert 'shares very little about themselves. Colleagues may find them hard to know.' in html
    assert 'Interpersonal Effectiveness Profile' in html
    assert 'Note for recruiters' in html
    assert 'Share these labels with recruiters only, not with candidates.' in html
    assert html.count('This candidate') == 1
    for name in ('Effective', 'Insensitive', 'Egocentric', 'Dogmatic', 'Task-Obsessed', 'Lonely-Empathic', 'Ineffective'):
        assert name in html


# ── found in the full-system review ──────────────────────────────────────
@pytest.mark.django_db
def test_asking_for_a_retake_gives_the_full_link_window_again(client, both):
    from datetime import timedelta
    from django.utils import timezone
    _enter(client, both)
    _begin(client, both, PE)
    _save(client, both, PE, {'answers': {'1': 1}, 'finish': True})
    AssessmentInvitation.objects.filter(pk=both.pk).update(
        token_expires_at=timezone.now() + timedelta(minutes=30))

    services.issue_invite(both.resume, resend=True)

    both.refresh_from_db()
    assert both.token_expires_at > timezone.now() + timedelta(days=6)
    assert not _part(both, PE).is_submitted


@pytest.mark.django_db
def test_a_retired_instrument_does_not_crash_the_resend(both):
    SEIAssessment.objects.filter(invitation=both, instrument=SEI).update(
        instrument='retired', is_submitted=True)

    services.issue_invite(both.resume, resend=True)


@pytest.mark.django_db
def test_a_part_running_past_the_link_reads_in_progress(client, both):
    from datetime import timedelta
    from django.utils import timezone
    _enter(client, both)
    _begin(client, both, PE)
    AssessmentInvitation.objects.filter(pk=both.pk).update(
        token_expires_at=timezone.now() - timedelta(minutes=1))

    assert _part(both, PE).status_label == 'In progress'


@pytest.mark.django_db
def test_a_new_code_during_the_grace_keeps_the_final_save(client, both):
    _enter(client, both)
    _begin(client, both, PE)
    _move_deadline(both, PE, -2)

    services.resend_code(AssessmentInvitation.objects.get(pk=both.pk))
    reply = _save(client, both, PE, {'answers': {'1': 3}, 'finish': True}).json()

    assert reply['status'] == 'submitted'


@pytest.mark.django_db
def test_hr_never_reads_in_progress_after_the_clock_and_grace(client, django_user_model, both):
    _enter(client, both)
    _begin(client, both, PE)
    _move_deadline(both, PE, -(SEIAssessment.SAVE_GRACE_SECONDS + 1))
    django_user_model.objects.create_user(username='portal-hr4', password='p', is_staff=True)
    hr = type(client)()
    hr.login(username='portal-hr4', password='p')

    hr.get(reverse('core:resume_detail', kwargs={'uuid': both.resume.uuid}))

    assert _part(both, PE).is_submitted


@pytest.mark.django_db
def test_a_dropped_invalid_paper_does_not_offer_a_retake(client, django_user_model, sample_job, both):
    _enter(client, both)
    _begin(client, both, PE)
    _save(client, both, PE, {'answers': {'1': 1}, 'finish': True})
    sample_job.assessments = [SEI]
    sample_job.save(update_fields=['assessments'])
    django_user_model.objects.create_user(username='portal-hr5', password='p', is_staff=True)
    hr = type(client)()
    hr.login(username='portal-hr5', password='p')

    response = hr.get(reverse('core:resume_detail', kwargs={'uuid': both.resume.uuid}))

    assert response.context['sei_needs_retake'] is False


@pytest.mark.django_db
def test_going_back_to_the_code_page_mid_part_returns_to_the_questions(client, both):
    _enter(client, both)
    _begin(client, both, PE)

    back = client.get(_url('verify', both))
    assert back.status_code == 302
    assert back.url == _url('entry', both)
    assert client.get(back.url).url == _url('test', both)


@pytest.mark.django_db
def test_a_visitor_without_the_code_still_gets_the_code_page(client, both):
    _enter(client, both)
    stranger = type(client)()

    page = stranger.get(_url('verify', both))

    assert page.status_code == 200
    assert 'name="code"' in page.content.decode()
