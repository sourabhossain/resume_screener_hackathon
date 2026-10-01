"""Scheduling in one step: time and place, a staff panel, emails, calendar files, reminders."""
from datetime import timedelta
from unittest import mock

import pytest
from django.core import mail
from django.urls import reverse
from django.utils import timezone

from apps.core.models import Resume
from apps.interviews.models import Interview, InterviewEvaluation
from apps.interviews.tasks import send_interview_reminders


@pytest.fixture(autouse=True)
def _commit_now(monkeypatch):
    # Emails are queued on commit; a test never commits, so run them at once.
    monkeypatch.setattr('django.db.transaction.on_commit', lambda fn, *args, **kwargs: fn())


@pytest.fixture
def staff(db, django_user_model):
    return [django_user_model.objects.create_user(f'panel{i}', email=f'panel{i}@sslwireless.com',
                                                  first_name=f'Panel{i}', last_name='Member', password='x')
            for i in range(3)]


@pytest.fixture
def candidate(db, sample_job):
    return Resume.objects.create(job=sample_job, candidate_name='nadia islam', email='nadia@example.com',
                                 recruiter_status='assessment')


def _day(offset=3):
    return (timezone.localdate() + timedelta(days=offset)).isoformat()


def _schedule(client, resume, panel, **extra):
    data = {'phase': '1', 'scheduled_date': _day(), 'scheduled_time': '10:00', 'duration_minutes': '60',
            'mode': 'in_person', 'location': 'Conference Room 3', 'notify_candidate': 'on',
            'notes': 'Ask about the gap in 2024', 'evaluators': [u.pk for u in panel], **extra}
    if 'notify_candidate' in extra and extra['notify_candidate'] is None:
        data.pop('notify_candidate')
    return client.post(reverse('interviews:create', kwargs={'resume_uuid': resume.uuid}), data)


def _to(address):
    return [m for m in mail.outbox if address in m.to]


def _calendar(email):
    part = email.attachments[0]
    return part.get_filename(), part.get_payload(decode=True).decode(), part


# ── scheduling ───────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_one_submit_creates_the_panel_and_emails_everyone(authenticated_client, candidate, staff):
    response = _schedule(authenticated_client, candidate, staff[:2])

    interview = Interview.objects.get(resume=candidate)
    assert response.url == reverse('interviews:detail', kwargs={'pk': interview.pk})
    assert interview.scheduled_time.strftime('%H:%M') == '10:00'
    assert [e.interviewer_email for e in interview.evaluations.all()] == [
        'panel0@sslwireless.com', 'panel1@sslwireless.com']
    assert all(e.invited_at for e in interview.evaluations.all())
    interview.refresh_from_db()
    assert interview.candidate_notified_at is not None
    assert len(mail.outbox) == 3


@pytest.mark.django_db
def test_each_evaluator_gets_their_own_link_and_a_calendar_file(authenticated_client, candidate, staff):
    _schedule(authenticated_client, candidate, staff[:1])

    email = _to('panel0@sslwireless.com')[0]
    ev = InterviewEvaluation.objects.get(evaluator=staff[0])
    assert str(ev.token) in email.body
    assert 'Nadia Islam' in email.subject and 'Conference Room 3' in email.body
    name, calendar, part = _calendar(email)
    assert name == 'interview.ics' and part.get_content_type() == 'text/calendar'
    assert part.get_param('method') == 'PUBLISH'
    assert str(part['Content-Type']).count('charset') == 1
    start = (timezone.localdate() + timedelta(days=3)).strftime('%Y%m%d')
    assert f'DTSTART:{start}T040000Z' in calendar
    assert f'DTEND:{start}T050000Z' in calendar


@pytest.mark.django_db
def test_the_candidate_email_has_the_time_and_place_but_never_the_internal_notes(
        authenticated_client, candidate, staff):
    _schedule(authenticated_client, candidate, staff[:1])

    email = _to('nadia@example.com')[0]
    html = email.alternatives[0][0]
    assert '10:00 AM' in email.body and 'Conference Room 3' in email.body
    assert 'gap in 2024' not in email.body and 'gap in 2024' not in html
    assert str(InterviewEvaluation.objects.get().token) not in email.body
    assert email.reply_to == ['jobs@sslwireless.com']
    assert _calendar(email)[0] == 'interview.ics'


@pytest.mark.django_db
def test_leaving_the_candidate_box_clear_emails_only_the_panel(authenticated_client, candidate, staff):
    _schedule(authenticated_client, candidate, staff[:1], notify_candidate=None)

    assert _to('nadia@example.com') == []
    assert len(_to('panel0@sslwireless.com')) == 1


@pytest.mark.django_db
@pytest.mark.parametrize('extra, field_error', [
    ({'scheduled_date': _day(-1)}, 'cannot be in the past'),
    ({'scheduled_time': ''}, 'required'),
    ({'location': ''}, 'room or address'),
    ({'mode': 'online', 'location': 'javascript:alert(1)'}, 'full meeting link'),
    ({'evaluators': []}, 'at least one evaluator'),
])
def test_an_incomplete_or_unsafe_schedule_is_refused(authenticated_client, candidate, staff, extra, field_error):
    response = _schedule(authenticated_client, candidate, staff[:1], **extra)

    assert response.status_code == 200
    assert field_error in response.content.decode()
    assert not Interview.objects.filter(resume=candidate).exists()
    assert mail.outbox == []


@pytest.mark.django_db
def test_a_time_earlier_today_is_refused(authenticated_client, candidate, staff):
    earlier = (timezone.localtime() - timedelta(hours=1))
    if earlier.date() != timezone.localdate():
        pytest.skip('Just after midnight there is no earlier time today.')
    response = _schedule(authenticated_client, candidate, staff[:1], scheduled_date=timezone.localdate().isoformat(),
                         scheduled_time=earlier.strftime('%H:%M'))
    assert 'already passed today' in response.content.decode()


@pytest.mark.django_db
def test_an_online_interview_takes_a_meeting_link(authenticated_client, candidate, staff):
    _schedule(authenticated_client, candidate, staff[:1], mode='online', location='https://meet.google.com/abc-defg-hij')

    email = _to('nadia@example.com')[0]
    assert 'Online' in email.body and 'https://meet.google.com/abc-defg-hij' in email.body


@pytest.mark.django_db
def test_the_form_offers_the_next_round_and_the_last_panel(authenticated_client, candidate, staff):
    _schedule(authenticated_client, candidate, staff[:2])

    page = authenticated_client.get(reverse('interviews:create', kwargs={'resume_uuid': candidate.uuid}))

    html = page.content.decode()
    assert page.context['form'].initial['phase'] == '2'
    assert 'Same panel as Interview 1' in html
    assert sorted(page.context['panels'][0]['ids']) == sorted(u.pk for u in staff[:2])


@pytest.mark.django_db
def test_staff_without_an_email_cannot_be_picked(authenticated_client, candidate, django_user_model):
    django_user_model.objects.create_user('noemail', password='x')
    html = authenticated_client.get(reverse('interviews:create', kwargs={'resume_uuid': candidate.uuid})).content.decode()
    assert 'noemail' not in html


# ── the interview page ───────────────────────────────────────────────────
@pytest.mark.django_db
def test_adding_a_staff_member_emails_them_at_once(authenticated_client, candidate, staff):
    _schedule(authenticated_client, candidate, staff[:1])
    interview = Interview.objects.get()
    mail.outbox.clear()

    authenticated_client.post(reverse('interviews:detail', kwargs={'pk': interview.pk}), {'evaluator': staff[2].pk})

    assert interview.evaluations.filter(evaluator=staff[2]).exists()
    assert len(_to('panel2@sslwireless.com')) == 1


@pytest.mark.django_db
def test_someone_already_on_the_panel_is_not_offered_again(authenticated_client, candidate, staff):
    _schedule(authenticated_client, candidate, staff[:1])
    interview = Interview.objects.get()

    response = authenticated_client.post(reverse('interviews:detail', kwargs={'pk': interview.pk}),
                                         {'evaluator': staff[0].pk})

    assert response.status_code == 200
    assert interview.evaluations.count() == 1


@pytest.mark.django_db
def test_resend_and_renew_email_the_evaluator_again(authenticated_client, candidate, staff):
    _schedule(authenticated_client, candidate, staff[:1])
    ev = InterviewEvaluation.objects.get()
    mail.outbox.clear()

    authenticated_client.post(reverse('interviews:evaluation_resend', kwargs={'token': ev.token}))
    assert len(_to('panel0@sslwireless.com')) == 1

    authenticated_client.post(reverse('interviews:evaluation_renew', kwargs={'token': ev.token}))
    ev.refresh_from_db()
    assert len(_to('panel0@sslwireless.com')) == 2
    assert str(ev.token) in mail.outbox[-1].body


@pytest.mark.django_db
def test_a_failed_email_is_shown_not_lost(authenticated_client, candidate, staff):
    with mock.patch('apps.interviews.notifications.EmailMultiAlternatives.send', side_effect=OSError('SMTP down')):
        _schedule(authenticated_client, candidate, staff[:1])

    ev = InterviewEvaluation.objects.get()
    assert ev.invited_at is None and 'SMTP down' in ev.invite_error
    page = authenticated_client.get(reverse('interviews:detail', kwargs={'pk': ev.interview_id})).content.decode()
    assert 'Email failed' in page


# ── reminders ────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_the_day_before_the_panel_and_candidate_are_reminded_once(authenticated_client, candidate, staff):
    _schedule(authenticated_client, candidate, staff[:2], scheduled_date=_day(1))
    done = InterviewEvaluation.objects.get(evaluator=staff[1])
    done.is_submitted = True
    done.save()
    mail.outbox.clear()

    first = send_interview_reminders()
    again = send_interview_reminders()

    assert first == {'evaluators': 1, 'candidates': 1}
    assert again == {'evaluators': 0, 'candidates': 0}
    assert [m.to for m in mail.outbox] == [['panel0@sslwireless.com'], ['nadia@example.com']]
    assert all(m.subject.startswith('Reminder') for m in mail.outbox)


@pytest.mark.django_db
def test_no_reminder_for_another_day_a_cancelled_interview_or_one_never_emailed(
        authenticated_client, candidate, staff, sample_job):
    _schedule(authenticated_client, candidate, staff[:1], scheduled_date=_day(2))
    other = Resume.objects.create(job=sample_job, candidate_name='Cancelled', email='c@example.com')
    _schedule(authenticated_client, other, staff[:1], scheduled_date=_day(1))
    Interview.objects.filter(resume=other).update(status=Interview.CANCELLED)
    legacy_resume = Resume.objects.create(job=sample_job, candidate_name='Legacy', email='l@example.com')
    legacy = Interview.objects.create(resume=legacy_resume, scheduled_date=timezone.localdate() + timedelta(days=1))
    InterviewEvaluation.objects.create(interview=legacy, interviewer_name='Old', interviewer_email='old@x.com')
    mail.outbox.clear()

    assert send_interview_reminders() == {'evaluators': 0, 'candidates': 0}
    assert mail.outbox == []


# ── calendar file ────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_the_calendar_file_escapes_text_and_keeps_lines_short(candidate):
    from apps.interviews.notifications import calendar_file
    interview = Interview.objects.create(
        resume=candidate, scheduled_date=timezone.localdate() + timedelta(days=2),
        scheduled_time=timezone.datetime(2000, 1, 1, 15, 30).time(), duration_minutes=90,
        location='Room 3, Level 7; SSL Wireless, Gulshan 1, Dhaka 1212, Bangladesh, near the long road')

    ics = calendar_file(interview)

    assert 'LOCATION:Room 3\\, Level 7\\; SSL Wireless' in ics.replace('\r\n ', '')
    assert all(len(line.encode()) <= 75 for line in ics.split('\r\n'))
    assert 'T093000Z' in ics and 'T110000Z' in ics



# ── fixes from the go-live review ────────────────────────────────────────
@pytest.mark.django_db
def test_a_double_submit_books_the_round_once(authenticated_client, candidate, staff):
    _schedule(authenticated_client, candidate, staff[:1])
    mail.outbox.clear()

    response = _schedule(authenticated_client, candidate, staff[:1])

    assert response.status_code == 200 and 'already scheduled' in response.content.decode()
    assert Interview.objects.filter(resume=candidate).count() == 1
    assert mail.outbox == []


@pytest.mark.django_db
@pytest.mark.parametrize('status', ['rejected', 'withdrawn', 'hired'])
def test_a_closed_candidate_cannot_be_invited(authenticated_client, candidate, staff, status):
    candidate.recruiter_status = status
    candidate.save(update_fields=['recruiter_status'])

    _schedule(authenticated_client, candidate, staff[:1])
    page = authenticated_client.get(reverse('core:resume_detail', kwargs={'uuid': candidate.uuid})).content.decode()

    assert not Interview.objects.filter(resume=candidate).exists()
    assert mail.outbox == []
    assert reverse('interviews:create', kwargs={'resume_uuid': candidate.uuid}) not in page


@pytest.mark.django_db
def test_a_link_for_an_interview_weeks_away_still_works_on_the_day(authenticated_client, candidate, staff):
    _schedule(authenticated_client, candidate, staff[:1], scheduled_date=_day(45))

    ev = InterviewEvaluation.objects.get()
    assert ev.token_expires_at > ev.interview.ends_at + timedelta(days=6)


@pytest.mark.django_db
def test_a_member_who_has_left_is_not_reminded_or_resent(authenticated_client, candidate, staff):
    _schedule(authenticated_client, candidate, staff[:2], scheduled_date=_day(1))
    staff[0].is_active = False
    staff[0].save()
    mail.outbox.clear()

    authenticated_client.post(reverse('interviews:evaluation_resend',
                                      kwargs={'token': InterviewEvaluation.objects.get(evaluator=staff[0]).token}))
    send_interview_reminders()

    assert _to('panel0@sslwireless.com') == []
    assert len(_to('panel1@sslwireless.com')) == 1


@pytest.mark.django_db
def test_a_changed_staff_address_is_followed(authenticated_client, candidate, staff):
    _schedule(authenticated_client, candidate, staff[:1])
    staff[0].email = 'new.address@sslwireless.com'
    staff[0].save()
    mail.outbox.clear()

    authenticated_client.post(reverse('interviews:evaluation_resend',
                                      kwargs={'token': InterviewEvaluation.objects.get().token}))

    assert len(_to('new.address@sslwireless.com')) == 1


@pytest.mark.django_db
@pytest.mark.parametrize('how', ['cancel', 'delete'])
def test_cancelling_or_deleting_tells_everyone_who_was_invited(authenticated_client, candidate, staff, how):
    _schedule(authenticated_client, candidate, staff[:2])
    interview = Interview.objects.get()
    mail.outbox.clear()

    if how == 'cancel':
        authenticated_client.post(reverse('interviews:status', kwargs={'pk': interview.pk}), {'action': 'cancel'})
    else:
        authenticated_client.post(reverse('interviews:delete', kwargs={'pk': interview.pk}))

    assert sorted(m.to[0] for m in mail.outbox) == [
        'nadia@example.com', 'panel0@sslwireless.com', 'panel1@sslwireless.com']
    candidate_email = _to('nadia@example.com')[0]
    assert candidate_email.subject.startswith('Interview cancelled')
    _, calendar, part = _calendar(candidate_email)
    assert part.get_param('method') == 'CANCEL' and 'STATUS:CANCELLED' in calendar and 'SEQUENCE:1' in calendar


@pytest.mark.django_db
def test_cancelling_an_interview_nobody_was_emailed_about_sends_nothing(authenticated_client, candidate):
    interview = Interview.objects.create(resume=candidate, scheduled_date=timezone.localdate() + timedelta(days=2))

    authenticated_client.post(reverse('interviews:status', kwargs={'pk': interview.pk}), {'action': 'cancel'})

    assert mail.outbox == []


# ── evaluator CV ─────────────────────────────────────────────────────────
def _with_cv(resume):
    from django.core.files.base import ContentFile
    resume.file.save('cv.pdf', ContentFile(b'%PDF-1.4 the cv'), save=True)
    return resume


@pytest.mark.django_db
def test_the_evaluator_can_open_the_cv_from_the_page_and_the_email(authenticated_client, candidate, staff, client):
    _with_cv(candidate)
    _schedule(authenticated_client, candidate, staff[:1])
    ev = InterviewEvaluation.objects.get()
    cv = reverse('interviews:evaluation_cv', kwargs={'token': ev.token})

    page = client.get(reverse('interviews:evaluate', kwargs={'token': ev.token})).content.decode()
    response = client.get(cv)

    assert cv in page
    assert cv in _to('panel0@sslwireless.com')[0].body
    assert response.status_code == 200
    assert b''.join(response.streaming_content).startswith(b'%PDF')
    assert response['Cache-Control'] == 'private, no-store, max-age=0'


@pytest.mark.django_db
@pytest.mark.parametrize('closed', ['submitted', 'expired', 'cancelled'])
def test_the_cv_link_closes_with_the_evaluation_link(authenticated_client, candidate, staff, client, closed):
    _with_cv(candidate)
    _schedule(authenticated_client, candidate, staff[:1])
    ev = InterviewEvaluation.objects.get()
    if closed == 'submitted':
        InterviewEvaluation.objects.filter(pk=ev.pk).update(is_submitted=True)
    elif closed == 'expired':
        InterviewEvaluation.objects.filter(pk=ev.pk).update(token_expires_at=timezone.now() - timedelta(minutes=1))
    else:
        Interview.objects.filter(pk=ev.interview_id).update(status=Interview.CANCELLED)

    assert client.get(reverse('interviews:evaluation_cv', kwargs={'token': ev.token})).status_code == 404


# ── reschedule ───────────────────────────────────────────────────────────
def _reschedule(client, interview, **extra):
    data = {'scheduled_date': _day(6), 'scheduled_time': '15:30', 'duration_minutes': '60',
            'mode': 'online', 'location': 'https://meet.google.com/new-room', 'notify': 'on', **extra}
    if extra.get('notify', 'on') is None:
        data.pop('notify')
    return client.post(reverse('interviews:reschedule', kwargs={'pk': interview.pk}), data)


@pytest.mark.django_db
def test_rescheduling_keeps_the_panel_and_tells_everyone_the_new_time(authenticated_client, candidate, staff):
    _schedule(authenticated_client, candidate, staff[:2])
    interview = Interview.objects.get()
    tokens = sorted(str(t) for t in interview.evaluations.values_list('token', flat=True))
    mail.outbox.clear()

    response = _reschedule(authenticated_client, interview)

    interview.refresh_from_db()
    assert response.status_code == 302
    assert interview.scheduled_time.strftime('%H:%M') == '15:30' and interview.mode == 'online'
    assert interview.schedule_version == 1
    assert sorted(str(t) for t in interview.evaluations.values_list('token', flat=True)) == tokens
    assert sorted(m.to[0] for m in mail.outbox) == [
        'nadia@example.com', 'panel0@sslwireless.com', 'panel1@sslwireless.com']
    candidate_email = _to('nadia@example.com')[0]
    assert candidate_email.subject.startswith('Interview rescheduled')
    assert '3:30 PM' in candidate_email.body and '10:00 AM' in candidate_email.body
    _, calendar, part = _calendar(candidate_email)
    assert 'SEQUENCE:1' in calendar and part.get_param('method') == 'PUBLISH'
    assert 'T093000Z' in calendar


@pytest.mark.django_db
def test_a_rescheduled_interview_is_reminded_again_and_its_links_stay_valid(authenticated_client, candidate, staff):
    _schedule(authenticated_client, candidate, staff[:1], scheduled_date=_day(1))
    send_interview_reminders()
    interview = Interview.objects.get()

    _reschedule(authenticated_client, interview, scheduled_date=_day(45))

    ev = InterviewEvaluation.objects.get()
    interview.refresh_from_db()
    assert ev.reminded_at is None and interview.candidate_reminded_at is None
    assert ev.token_expires_at > interview.ends_at + timedelta(days=6)


@pytest.mark.django_db
def test_rescheduling_without_the_box_ticked_or_without_a_change_emails_no_one(authenticated_client, candidate, staff):
    _schedule(authenticated_client, candidate, staff[:1])
    interview = Interview.objects.get()
    mail.outbox.clear()

    _reschedule(authenticated_client, interview, notify=None)
    interview.refresh_from_db()
    _reschedule(authenticated_client, interview, scheduled_date=interview.scheduled_date.isoformat(),
                scheduled_time=interview.scheduled_time.strftime('%H:%M'))

    assert mail.outbox == []


@pytest.mark.django_db
def test_only_a_scheduled_interview_can_be_rescheduled(authenticated_client, candidate, staff):
    _schedule(authenticated_client, candidate, staff[:1])
    interview = Interview.objects.get()
    Interview.objects.filter(pk=interview.pk).update(status=Interview.CANCELLED)
    mail.outbox.clear()

    _reschedule(authenticated_client, interview)

    interview.refresh_from_db()
    assert interview.scheduled_time.strftime('%H:%M') == '10:00'
    assert mail.outbox == []


# ── edge cases from the final review ─────────────────────────────────────
@pytest.mark.django_db
def test_the_evaluator_reschedule_email_has_both_times_and_the_cv(authenticated_client, candidate, staff):
    _with_cv(candidate)
    _schedule(authenticated_client, candidate, staff[:1])
    interview = Interview.objects.get()
    mail.outbox.clear()

    _reschedule(authenticated_client, interview)

    email = _to('panel0@sslwireless.com')[0]
    assert email.subject.startswith('Rescheduled: interview')
    assert '10:00 AM' in email.body and '3:30 PM' in email.body
    assert reverse('interviews:evaluation_cv', kwargs={'token': InterviewEvaluation.objects.get().token}) in email.body


@pytest.mark.django_db
def test_a_member_who_has_left_is_not_told_of_the_new_time(authenticated_client, candidate, staff):
    _schedule(authenticated_client, candidate, staff[:2])
    staff[1].is_active = False
    staff[1].save()
    mail.outbox.clear()

    _reschedule(authenticated_client, Interview.objects.get())

    assert _to('panel1@sslwireless.com') == []
    assert len(_to('panel0@sslwireless.com')) == 1


@pytest.mark.django_db
def test_an_old_interview_without_a_time_can_be_rescheduled(authenticated_client, candidate, staff):
    interview = Interview.objects.create(resume=candidate, scheduled_date=timezone.localdate() + timedelta(days=2))
    page = authenticated_client.get(reverse('interviews:reschedule', kwargs={'pk': interview.pk})).content.decode()
    assert 'Now:' in page

    response = _reschedule(authenticated_client, interview)

    interview.refresh_from_db()
    assert response.status_code == 302 and interview.scheduled_time is not None
    assert mail.outbox == []


@pytest.mark.django_db
def test_a_cv_in_word_format_downloads_with_a_bangla_name(authenticated_client, sample_job, staff, client):
    from django.core.files.base import ContentFile
    resume = Resume.objects.create(job=sample_job, candidate_name='রহিম উদ্দিন', email='rahim@example.com',
                                   recruiter_status='assessment')
    resume.file.save('cv.docx', ContentFile(b'PK\x03\x04 word'), save=True)
    _schedule(authenticated_client, resume, staff[:1])
    ev = InterviewEvaluation.objects.get()

    response = client.get(reverse('interviews:evaluation_cv', kwargs={'token': ev.token}))

    assert response.status_code == 200
    assert response['Content-Disposition'].startswith('attachment;')
    assert "filename*=utf-8''" in response['Content-Disposition']


@pytest.mark.django_db
def test_the_cv_link_closes_when_the_candidate_is_deleted(authenticated_client, candidate, staff, client):
    _with_cv(candidate)
    _schedule(authenticated_client, candidate, staff[:1])
    ev = InterviewEvaluation.objects.get()
    candidate.soft_delete()

    assert client.get(reverse('interviews:evaluation_cv', kwargs={'token': ev.token})).status_code == 404


@pytest.mark.django_db
def test_cancelling_after_a_reschedule_supersedes_the_updated_calendar_entry(authenticated_client, candidate, staff):
    _schedule(authenticated_client, candidate, staff[:1])
    interview = Interview.objects.get()
    _reschedule(authenticated_client, interview)
    mail.outbox.clear()

    authenticated_client.post(reverse('interviews:status', kwargs={'pk': interview.pk}), {'action': 'cancel'})

    _, calendar, _ = _calendar(_to('nadia@example.com')[0])
    assert 'SEQUENCE:2' in calendar and 'STATUS:CANCELLED' in calendar


# ── live delivery status on the interview page ───────────────────────────
@pytest.mark.django_db
def test_the_page_keeps_checking_while_an_invitation_is_on_its_way(authenticated_client, candidate):
    interview = Interview.objects.create(resume=candidate, scheduled_date=timezone.localdate() + timedelta(days=2),
                                         scheduled_time=timezone.datetime(2000, 1, 1, 16, 0).time(), location='Room 3')
    InterviewEvaluation.objects.create(interview=interview, interviewer_name='P', interviewer_email='p@x.com')
    url = reverse('interviews:delivery', kwargs={'pk': interview.pk})

    page = authenticated_client.get(reverse('interviews:detail', kwargs={'pk': interview.pk})).content.decode()
    assert 'Sending…' in page and url in page

    Interview.objects.filter(pk=interview.pk).update(candidate_notified_at=timezone.now())
    InterviewEvaluation.objects.update(invited_at=timezone.now())
    update = authenticated_client.get(url + '?n=1').content.decode()

    assert 'hx-swap-oob="true"' in update and 'Sent ' in update and 'Emailed ' in update
    assert url not in update


@pytest.mark.django_db
def test_the_page_stops_checking_after_two_minutes(authenticated_client, candidate):
    interview = Interview.objects.create(resume=candidate, scheduled_date=timezone.localdate() + timedelta(days=2),
                                         scheduled_time=timezone.datetime(2000, 1, 1, 16, 0).time(), location='Room 3')
    url = reverse('interviews:delivery', kwargs={'pk': interview.pk})

    assert url in authenticated_client.get(url + '?n=39').content.decode()
    assert url not in authenticated_client.get(url + '?n=40').content.decode()
