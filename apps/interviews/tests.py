"""Tests for the interviews app: models, recruiter views, and the public
token-based evaluation flow."""
from datetime import date, time, timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.interviews.forms import InterviewerAddForm
from apps.interviews.models import (
    Interview,
    InterviewEvaluation,
    CRITERIA_KEYS,
    MAX_SCORE,
)

@pytest.fixture
def interview(db, sample_resume):
    return Interview.objects.create(
        resume=sample_resume, phase='1', scheduled_date=date.today()
    )

@pytest.fixture
def evaluation(db, interview):
    return interview.evaluations.create(interviewer_name='Bob Reviewer')

def _full_scores(value=4):
    """A complete, valid evaluation POST payload (all criteria scored)."""
    return {f'score_{k}': str(value) for k in CRITERIA_KEYS}

@pytest.mark.django_db
class TestInterviewModels:
    def test_evaluation_gets_token_and_expiry_on_create(self, evaluation):
        assert evaluation.token is not None
        assert evaluation.token_expires_at is not None
        assert evaluation.token_expires_at > timezone.now()

    def test_total_score_and_percentage(self, evaluation):
        evaluation.scores = {k: 4 for k in CRITERIA_KEYS}
        assert evaluation.total_score == len(CRITERIA_KEYS) * 4
        assert evaluation.percentage == round((evaluation.total_score / MAX_SCORE) * 100)

    def test_total_score_ignores_out_of_range_values(self, evaluation):
        evaluation.scores = {'educational_background': 9, 'enthusiasm': 3}
        assert evaluation.total_score == 3

    def test_impression_label_bands(self, evaluation):
        evaluation.scores = {k: 5 for k in CRITERIA_KEYS}
        assert evaluation.impression_label == 'Good'
        evaluation.scores = {k: 3 for k in CRITERIA_KEYS}
        assert evaluation.impression_label == 'Satisfactory'
        evaluation.scores = {k: 1 for k in CRITERIA_KEYS}
        assert evaluation.impression_label == 'Unsatisfactory'

    def test_is_expired_logic(self, interview):
        ev = interview.evaluations.create(interviewer_name='X')
        assert ev.is_expired is False
        ev.token_expires_at = timezone.now() - timedelta(days=1)
        ev.save(update_fields=['token_expires_at'])
        assert ev.is_expired is True
        ev.is_submitted = True
        assert ev.is_expired is False

    def test_interview_avg_and_counts(self, interview):
        assert interview.avg_score() is None
        e1 = interview.evaluations.create(interviewer_name='A', scores={k: 4 for k in CRITERIA_KEYS}, is_submitted=True)
        interview.evaluations.create(interviewer_name='B')
        assert interview.submitted_count == 1
        assert interview.pending_count == 1
        assert interview.avg_score() == e1.total_score

@pytest.mark.django_db
class TestInterviewerAddForm:
    def test_accepts_bengali_and_english_names(self):
        form = InterviewerAddForm({
            'interviewer_name': 'আসাদ হোসেন',
            'interviewer_position': 'Sr. Manager',
            'interviewer_department': 'Human Resources',
        })
        assert form.is_valid(), form.errors

    def test_accepts_hyphen_apostrophe_and_period(self):
        form = InterviewerAddForm({
            'interviewer_name': "Dr. O'Brien-Smith",
            'interviewer_position': '',
            'interviewer_department': '',
        })
        assert form.is_valid(), form.errors

    def test_rejects_special_characters(self):
        form = InterviewerAddForm({
            'interviewer_name': "ঘজক্ল;'",
            'interviewer_position': 'bad@title',
            'interviewer_department': '',
        })
        assert not form.is_valid()
        assert 'interviewer_name' in form.errors
        assert 'interviewer_position' in form.errors

    def test_rejects_name_without_letters(self):
        form = InterviewerAddForm({
            'interviewer_name': '12345',
            'interviewer_position': '',
            'interviewer_department': '',
        })
        assert not form.is_valid()
        assert 'interviewer_name' in form.errors

    def test_trims_whitespace(self):
        form = InterviewerAddForm({
            'interviewer_name': '  Carol  ',
            'interviewer_position': '  Lead  ',
            'interviewer_department': '',
        })
        assert form.is_valid(), form.errors
        assert form.cleaned_data['interviewer_name'] == 'Carol'
        assert form.cleaned_data['interviewer_position'] == 'Lead'

@pytest.mark.django_db
class TestRecruiterViews:
    def test_create_requires_login(self, client, sample_resume):
        url = reverse('interviews:create', kwargs={'resume_uuid': sample_resume.uuid})
        resp = client.get(url)
        assert resp.status_code == 302
        assert 'login' in resp.url

    def test_create_get_and_post(self, authenticated_client, sample_resume):
        url = reverse('interviews:create', kwargs={'resume_uuid': sample_resume.uuid})
        assert authenticated_client.get(url).status_code == 200
        future = (timezone.now().date() + timedelta(days=7)).isoformat()
        resp = authenticated_client.post(url, {'phase': '1', 'scheduled_date': future, 'notes': 'x'})
        assert resp.status_code == 302
        assert Interview.objects.filter(resume=sample_resume).exists()

    def test_create_rejects_past_date(self, authenticated_client, sample_resume):
        url = reverse('interviews:create', kwargs={'resume_uuid': sample_resume.uuid})
        past = (timezone.now().date() - timedelta(days=1)).isoformat()
        resp = authenticated_client.post(url, {'phase': '1', 'scheduled_date': past, 'notes': 'x'})
        assert resp.status_code == 200
        assert resp.context['form'].errors['scheduled_date'] == ['Interview date cannot be in the past.']
        assert not Interview.objects.filter(resume=sample_resume).exists()

    def test_create_accepts_empty_time(self, authenticated_client, sample_resume):
        url = reverse('interviews:create', kwargs={'resume_uuid': sample_resume.uuid})
        future = (timezone.now().date() + timedelta(days=7)).isoformat()
        resp = authenticated_client.post(url, {'phase': '1', 'scheduled_date': future, 'scheduled_time': '', 'notes': ''})
        assert resp.status_code == 302
        iv = Interview.objects.get(resume=sample_resume)
        assert iv.scheduled_time is None

    def test_create_accepts_valid_time(self, authenticated_client, sample_resume):
        url = reverse('interviews:create', kwargs={'resume_uuid': sample_resume.uuid})
        future = (timezone.now().date() + timedelta(days=7)).isoformat()
        resp = authenticated_client.post(url, {'phase': '1', 'scheduled_date': future, 'scheduled_time': '14:30', 'notes': ''})
        assert resp.status_code == 302
        iv = Interview.objects.get(resume=sample_resume)
        assert iv.scheduled_time is not None
        assert iv.scheduled_time.strftime('%H:%M') == '14:30'

    def test_detail_renders(self, authenticated_client, interview):
        resp = authenticated_client.get(reverse('interviews:detail', kwargs={'pk': interview.pk}))
        assert resp.status_code == 200

    def test_detail_add_interviewer(self, authenticated_client, interview):
        url = reverse('interviews:detail', kwargs={'pk': interview.pk})
        resp = authenticated_client.post(url, {'interviewer_name': 'Carol', 'interviewer_position': 'Lead'})
        assert resp.status_code == 302
        assert interview.evaluations.filter(interviewer_name='Carol').exists()

    def test_detail_rejects_invalid_interviewer_input(self, authenticated_client, interview):
        url = reverse('interviews:detail', kwargs={'pk': interview.pk})
        before = interview.evaluations.count()
        resp = authenticated_client.post(url, {
            'interviewer_name': 'bad@name',
            'interviewer_position': 'Lead',
            'interviewer_department': '',
        })
        assert resp.status_code == 200
        assert interview.evaluations.count() == before
        assert b'dj-messages' in resp.content
        assert b'invalid characters' in resp.content.lower()
        assert b'ring-red-400/50' not in resp.content

    def test_delete_soft_deletes(self, authenticated_client, interview):
        url = reverse('interviews:delete', kwargs={'pk': interview.pk})
        resp = authenticated_client.post(url)
        assert resp.status_code == 302
        interview.refresh_from_db()
        assert interview.is_deleted is True

    def test_evaluation_renew_changes_token(self, authenticated_client, evaluation):
        old = evaluation.token
        url = reverse('interviews:evaluation_renew', kwargs={'token': evaluation.token})
        authenticated_client.post(url)
        evaluation.refresh_from_db()
        assert evaluation.token != old

    def test_evaluation_delete(self, authenticated_client, evaluation):
        url = reverse('interviews:evaluation_delete', kwargs={'token': evaluation.token})
        authenticated_client.post(url)
        assert not InterviewEvaluation.objects.filter(pk=evaluation.pk).exists()

    def test_any_authenticated_recruiter_can_access_others_interview(
        self, client, django_user_model, interview
    ):
        """Single-company: a non-owner, non-staff recruiter still has access
        (consistent with unscoped jobs/resumes in core)."""
        interview.resume.job.owner = django_user_model.objects.create_user(
            username='owner2', password='x'
        )
        interview.resume.job.save()
        other = django_user_model.objects.create_user(username='recruiter2', password='x')
        client.force_login(other)
        resp = client.get(reverse('interviews:detail', kwargs={'pk': interview.pk}))
        assert resp.status_code == 200

@pytest.mark.django_db
class TestPublicEvaluate:
    def test_evaluate_get_valid(self, client, evaluation):
        resp = client.get(reverse('interviews:evaluate', kwargs={'token': evaluation.token}))
        assert resp.status_code == 200

    def test_evaluate_bogus_token_404(self, client):
        import uuid
        resp = client.get(reverse('interviews:evaluate', kwargs={'token': uuid.uuid4()}))
        assert resp.status_code == 404

    def test_submit_auto_recommendation_yes(self, client, evaluation):
        url = reverse('interviews:evaluate', kwargs={'token': evaluation.token})
        resp = client.post(url, _full_scores(4))
        assert resp.status_code == 302
        evaluation.refresh_from_db()
        assert evaluation.is_submitted is True
        assert evaluation.recommendation == 'yes'
        assert len(evaluation.scores) == len(CRITERIA_KEYS)

    def test_submit_auto_recommendation_maybe_and_no(self, client, interview):
        e_maybe = interview.evaluations.create(interviewer_name='M')
        client.post(reverse('interviews:evaluate', kwargs={'token': e_maybe.token}), _full_scores(3))
        e_maybe.refresh_from_db()
        assert e_maybe.recommendation == 'maybe'

        e_no = interview.evaluations.create(interviewer_name='N')
        client.post(reverse('interviews:evaluate', kwargs={'token': e_no.token}), _full_scores(1))
        e_no.refresh_from_db()
        assert e_no.recommendation == 'no'

    def test_manual_recommendation_overrides_score(self, client, evaluation):
        url = reverse('interviews:evaluate', kwargs={'token': evaluation.token})
        data = _full_scores(1)
        data['recommendation'] = 'yes'
        client.post(url, data)
        evaluation.refresh_from_db()
        assert evaluation.recommendation == 'yes'

    def test_resubmit_blocked(self, client, evaluation):
        url = reverse('interviews:evaluate', kwargs={'token': evaluation.token})
        client.post(url, _full_scores(4))
        resp = client.get(url)
        assert resp.status_code == 200
        assert b'score-radio' not in resp.content

    def test_expired_token_shows_expired_page(self, client, evaluation):
        evaluation.token_expires_at = timezone.now() - timedelta(days=1)
        evaluation.save(update_fields=['token_expires_at'])
        resp = client.get(reverse('interviews:evaluate', kwargs={'token': evaluation.token}))
        assert resp.status_code == 200
        assert b'score-radio' not in resp.content

    def test_evaluate_done_renders(self, client, evaluation):
        resp = client.get(reverse('interviews:evaluate_done', kwargs={'token': evaluation.token}))
        assert resp.status_code == 200


def _monday(d=None):
    d = d or timezone.localdate()
    return d - timedelta(days=d.weekday())


@pytest.mark.django_db
class TestInterviewCalendar:
    url = reverse('interviews:calendar')

    def test_requires_login(self, client):
        resp = client.get(self.url)
        assert resp.status_code == 302
        assert 'login' in resp.url

    def test_shows_interview_in_correct_day_column(self, authenticated_client, sample_resume):
        # Wednesday of the current week (offset 2 from Monday).
        wednesday = _monday() + timedelta(days=2)
        iv = Interview.objects.create(resume=sample_resume, phase='1', scheduled_date=wednesday)
        resp = authenticated_client.get(self.url)
        assert resp.status_code == 200
        assert resp.context['interview_count'] == 1
        assert sample_resume.candidate_name.title().encode() in resp.content

        days = resp.context['days']
        assert len(days) == 7
        for day in days:
            if day['date'] == wednesday:
                assert iv in day['interviews']
            else:
                assert iv not in day['interviews']

    def test_renders_seven_day_columns_and_controls(self, authenticated_client, sample_resume):
        Interview.objects.create(resume=sample_resume, phase='1', scheduled_date=_monday())
        resp = authenticated_client.get(self.url)
        assert resp.content.count(b'data-day-column') == 7
        assert b'?week=' in resp.content            # prev/next controls
        assert b'Today' in resp.content
        assert b'1 interview this week' in resp.content

    def test_excludes_soft_deleted_interview(self, authenticated_client, sample_resume):
        iv = Interview.objects.create(resume=sample_resume, phase='1', scheduled_date=_monday())
        iv.soft_delete()
        resp = authenticated_client.get(self.url)
        assert resp.context['interview_count'] == 0

    def test_excludes_interview_of_soft_deleted_resume(self, authenticated_client, sample_resume):
        Interview.objects.create(resume=sample_resume, phase='1', scheduled_date=_monday())
        sample_resume.soft_delete()
        resp = authenticated_client.get(self.url)
        assert resp.context['interview_count'] == 0

    def test_excludes_interview_of_soft_deleted_job(self, authenticated_client, sample_resume):
        Interview.objects.create(resume=sample_resume, phase='1', scheduled_date=_monday())
        sample_resume.job.soft_delete()
        resp = authenticated_client.get(self.url)
        assert resp.context['interview_count'] == 0

    def test_week_navigation_moves_window(self, authenticated_client, sample_resume):
        next_monday = _monday() + timedelta(days=7)
        Interview.objects.create(resume=sample_resume, phase='1', scheduled_date=next_monday)
        # Not visible in the current week...
        assert authenticated_client.get(self.url).context['interview_count'] == 0
        # ...but visible when navigating to that week.
        resp = authenticated_client.get(self.url, {'week': next_monday.isoformat()})
        assert resp.context['interview_count'] == 1
        assert resp.context['week_start'] == next_monday

    def test_empty_week_renders_empty_state(self, authenticated_client):
        far = (_monday() + timedelta(days=70)).isoformat()
        resp = authenticated_client.get(self.url, {'week': far})
        assert resp.context['interview_count'] == 0
        assert b'No interviews scheduled this week' in resp.content

    def test_query_count_does_not_grow_with_interviews(self, authenticated_client, sample_job):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        from apps.core.models import Resume

        def make(n, phase='1'):
            r = Resume.objects.create(job=sample_job, candidate_name=f'Cand {n}', final_score=70)
            Interview.objects.create(resume=r, phase=phase, scheduled_date=_monday())

        make(1); make(2)
        with CaptureQueriesContext(connection) as ctx_small:
            assert authenticated_client.get(self.url).context['interview_count'] == 2
        n_small = len(ctx_small)

        for i in range(3, 11):
            make(i)
        with CaptureQueriesContext(connection) as ctx_large:
            assert authenticated_client.get(self.url).context['interview_count'] == 10
        n_large = len(ctx_large)

        assert n_small == n_large, f'query count grew: {n_small} -> {n_large}'

    def test_day_ordering_timed_before_untimed(self, authenticated_client, sample_job):
        from apps.core.models import Resume
        d = _monday() + timedelta(days=1)

        def mk(name, t):
            r = Resume.objects.create(job=sample_job, candidate_name=name, final_score=70)
            return Interview.objects.create(resume=r, phase='1', scheduled_date=d, scheduled_time=t)

        untimed = mk('Untimed', None)
        late = mk('Late', time(14, 0))
        early = mk('Early', time(9, 0))

        resp = authenticated_client.get(self.url, {'week': d.isoformat()})
        day = next(x for x in resp.context['days'] if x['date'] == d)
        # Timed ascending first, untimed last.
        assert day['interviews'] == [early, late, untimed]

    # --- Part B: rendered-HTML / presentation checks -----------------------

    def test_desktop_seven_column_grid_markup(self, authenticated_client, sample_resume):
        Interview.objects.create(resume=sample_resume, phase='1', scheduled_date=_monday())
        resp = authenticated_client.get(self.url)
        assert b'lg:grid-cols-7' in resp.content          # single 7-col desktop grid
        assert resp.content.count(b'data-day-column') == 7

    def test_card_shows_time_job_title_and_ics_link(self, authenticated_client, sample_resume):
        d = _monday() + timedelta(days=2)
        iv = Interview.objects.create(resume=sample_resume, phase='2',
                                      scheduled_date=d, scheduled_time=time(9, 30))
        resp = authenticated_client.get(self.url, {'week': d.isoformat()})
        content = resp.content.decode()
        assert '09:30' in content                          # HH:MM on a timed card
        assert sample_resume.job.title in content          # job title (line 3)
        assert reverse('interviews:ics', kwargs={'pk': iv.pk}) in content  # per-card ics link

    def test_today_column_highlight_present_on_current_week(self, authenticated_client, sample_resume):
        Interview.objects.create(resume=sample_resume, phase='1', scheduled_date=_monday())
        resp = authenticated_client.get(self.url)          # defaults to current week
        assert b'day-today' in resp.content

    def test_today_column_highlight_absent_on_other_week(self, authenticated_client):
        far = (_monday() + timedelta(days=70)).isoformat()
        resp = authenticated_client.get(self.url, {'week': far})
        assert b'day-today' not in resp.content


@pytest.mark.django_db
class TestInterviewICS:
    def test_requires_login(self, client, interview):
        resp = client.get(reverse('interviews:ics', kwargs={'pk': interview.pk}))
        assert resp.status_code == 302
        assert 'login' in resp.url

    def test_content_type_and_disposition(self, authenticated_client, interview):
        resp = authenticated_client.get(reverse('interviews:ics', kwargs={'pk': interview.pk}))
        assert resp.status_code == 200
        assert resp['Content-Type'] == 'text/calendar; charset=utf-8'
        assert resp['Content-Disposition'] == f'attachment; filename="interview-{interview.pk}.ics"'

    def test_contains_vevent_name_and_date(self, authenticated_client, interview):
        resp = authenticated_client.get(reverse('interviews:ics', kwargs={'pk': interview.pk}))
        body = resp.content.decode()
        assert 'BEGIN:VCALENDAR' in body
        assert 'BEGIN:VEVENT' in body
        assert 'STATUS:CONFIRMED' in body
        assert interview.resume.candidate_name in body
        assert f'DTSTART;VALUE=DATE:{interview.scheduled_date.strftime("%Y%m%d")}' in body
        assert '\r\n' in body                       # CRLF line endings
        assert f'UID:interview-{interview.pk}@' in body

    def test_special_characters_escaped(self, authenticated_client, sample_job):
        from apps.core.models import Resume
        r = Resume.objects.create(job=sample_job, candidate_name='Khan, Md; Test', final_score=80)
        iv = Interview.objects.create(resume=r, phase='2', scheduled_date=timezone.localdate())
        body = authenticated_client.get(reverse('interviews:ics', kwargs={'pk': iv.pk})).content.decode()
        assert 'Khan\\, Md\\; Test' in body          # comma + semicolon escaped
        assert 'SUMMARY:Interview - Khan, Md; Test' not in body   # raw form must not appear

    def test_no_pii_or_scores_in_output(self, authenticated_client, sample_job):
        from apps.core.models import Resume
        r = Resume.objects.create(
            job=sample_job, candidate_name='Jane Roe',
            email='secret.person@example.com', phone='01711223344', final_score=91,
        )
        iv = Interview.objects.create(resume=r, phase='1', scheduled_date=timezone.localdate())
        body = authenticated_client.get(reverse('interviews:ics', kwargs={'pk': iv.pk})).content.decode()
        assert 'secret.person@example.com' not in body
        assert '01711223344' not in body
        assert 'score' not in body.lower()

    def test_soft_deleted_interview_404(self, authenticated_client, interview):
        interview.soft_delete()
        resp = authenticated_client.get(reverse('interviews:ics', kwargs={'pk': interview.pk}))
        assert resp.status_code == 404

    def test_ics_timed_event(self, authenticated_client, sample_job):
        from apps.core.models import Resume
        r = Resume.objects.create(job=sample_job, candidate_name='Timed Person', final_score=70)
        iv = Interview.objects.create(
            resume=r, phase='1', scheduled_date=timezone.localdate(), scheduled_time=time(14, 30)
        )
        body = authenticated_client.get(reverse('interviews:ics', kwargs={'pk': iv.pk})).content.decode()
        day = iv.scheduled_date.strftime('%Y%m%d')
        # TIME_ZONE is UTC, so 14:30 local == 14:30Z; DTEND is one hour later.
        assert f'DTSTART:{day}T143000Z' in body
        assert f'DTEND:{day}T153000Z' in body
        assert 'VALUE=DATE' not in body

    def test_ics_untimed_still_all_day(self, authenticated_client, interview):
        # Regression: the `interview` fixture has scheduled_time=None.
        body = authenticated_client.get(reverse('interviews:ics', kwargs={'pk': interview.pk})).content.decode()
        assert f'DTSTART;VALUE=DATE:{interview.scheduled_date.strftime("%Y%m%d")}' in body
        assert 'T143000Z' not in body
