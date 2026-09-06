"""External verification requests to employers and referees.

Two audiences: HR decides who is asked, and a stranger to this system answers on
an emailed link. The rules that matter are who may be contacted at all, that the
link alone is not enough, and that a respondent only ever sees their own form.
"""
import re
from datetime import timedelta

import pytest
from django.core import mail
from django.urls import reverse
from django.utils import timezone

from apps.core.models import Resume
from apps.employee_form.models import EmployeeForm
from apps.reference_checks import schema, services
from apps.reference_checks.models import ReferenceCheck


# Everything the candidate's own form gives us about who to contact.
CANDIDATE_ANSWERS = {
    'employer_1_name': 'Acme Ltd',
    'employer_1_hr_email': 'hr@acme.com',
    'employer_1_hr_contact': '+8801711000000',
    'employer_1_contact_permission': 'yes',

    'employer_2_name': 'Globex',
    'employer_2_hr_email': 'people@globex.com',
    'employer_2_contact_permission': 'no',        # candidate said no

    'reference_1_name': 'Karim Uddin',
    'reference_1_email': 'karim@acme.com',
    'reference_1_designation': 'CTO, Acme',
    'reference_1_contact': '+8801811000000',
    'reference_1_contact_permission': 'yes',

    'reference_2_name': 'Nadia Haque',
    'reference_2_email': 'nadia@example.com',
    'reference_2_contact_permission': 'yes',
}


def test_the_candidate_answers_this_suite_invents_are_real_form_keys():
    """Guards every other test here.

    Both this fixture and services.py name employee-form keys as bare strings.
    If they are wrong in the same way -- as `employer_1_hr_contact_name` once
    was, a key no form has ever written -- the rest of the suite passes while
    reading nothing. Pinning the fixture to the real schema is what makes the
    other assertions mean anything.
    """
    from apps.employee_form import schema as employee_schema

    real = {q['key'] for step in employee_schema.STEPS for q in step['questions']}
    invented = sorted(k for k in CANDIDATE_ANSWERS if k not in real)
    assert not invented, f'the employee form has no such question(s): {invented}'


def test_every_contact_detail_hr_sees_comes_from_a_real_form_key(candidate):
    """The other half: what services reads must be what the form writes."""
    from apps.employee_form import schema as employee_schema

    real = {q['key'] for step in employee_schema.STEPS for q in step['questions']}
    for suffix in ('name', 'hr_email', 'hr_contact', 'contact_permission'):
        assert f'employer_1_{suffix}' in real, f'employer_1_{suffix} is gone'
    for suffix in ('name', 'email', 'contact', 'designation', 'contact_permission'):
        assert f'reference_1_{suffix}' in real, f'reference_1_{suffix} is gone'

    row = services.contact_for(candidate, 'employer_1')
    assert row['recipient_email'] == 'hr@acme.com'
    assert row['recipient_organisation'] == 'Acme Ltd'
    assert row['permitted'] is True
    # The form asks for the employer's HR email and phone, never a person's
    # name, so the request is addressed to the department. Pinned because the
    # code once looked up a name key that no form has ever written.
    assert row['recipient_name'] == 'Acme Ltd — HR'
    assert row['recipient_phone'] == '+8801711000000'

    referee = services.contact_for(candidate, 'reference_1')
    assert referee['recipient_name'] == 'Karim Uddin'
    assert referee['recipient_phone'] == '+8801811000000'


@pytest.fixture
def candidate(db, sample_job):
    resume = Resume.objects.create(
        job=sample_job, candidate_name='Ayesha Rahman',
        email='ayesha@example.com', recruiter_status='interviewing',
    )
    EmployeeForm.objects.create(
        resume=resume, is_submitted=True, answers=dict(CANDIDATE_ANSWERS))
    return resume


@pytest.fixture
def fresher(db, sample_job):
    """No employer named -- the signal this form uses for "fresher"."""
    resume = Resume.objects.create(
        job=sample_job, candidate_name='Tanvir Ahmed',
        email='tanvir@example.com', recruiter_status='interviewing',
    )
    EmployeeForm.objects.create(resume=resume, is_submitted=True, answers={
        'reference_1_name': 'Prof. Rahman',
        'reference_1_email': 'rahman@university.edu',
        'reference_1_contact_permission': 'yes',
    })
    return resume


@pytest.fixture
def hr_user(db, django_user_model):
    return django_user_model.objects.create_user(
        username='hradmin', password='hrpass123', is_staff=True)


@pytest.fixture
def hr_client(client, hr_user):
    client.login(username='hradmin', password='hrpass123')
    return client


def _manage_url(resume):
    return reverse('reference_checks:manage', kwargs={'uuid': resume.uuid})


def _send_url(resume, source_key):
    return reverse('reference_checks:send',
                   kwargs={'uuid': resume.uuid, 'source_key': source_key})


def _send(hr_client, resume, source_key, **overrides):
    row = services.contact_for(resume, source_key)
    data = {
        'kind': row['default_kind'],
        'recipient_name': row['recipient_name'],
        'recipient_email': row['recipient_email'],
        'recipient_organisation': row['recipient_organisation'],
        **overrides,
    }
    return hr_client.post(_send_url(resume, source_key), data)


def _otp_from_outbox():
    body = mail.outbox[-1].body
    match = re.search(r'code is:\s*(\d{6})', body)
    assert match, f'no code in:\n{body}'
    return match.group(1)


# ── Who can be asked ─────────────────────────────────────────────────────
def test_contacts_come_from_the_candidates_own_form(candidate):
    rows = {r['source_key']: r for r in services.candidate_contacts(candidate)}

    assert set(rows) == {'employer_1', 'employer_2', 'reference_1', 'reference_2'}
    assert rows['employer_1']['recipient_email'] == 'hr@acme.com'
    assert rows['reference_1']['recipient_name'] == 'Karim Uddin'


def test_an_unnamed_employer_is_not_offered(candidate):
    """Employers 3 and 4 were left blank, so there is nobody there to ask."""
    keys = {r['source_key'] for r in services.candidate_contacts(candidate)}
    assert 'employer_3' not in keys and 'employer_4' not in keys


def test_a_fresher_gets_the_academic_form_by_default(fresher):
    row = services.contact_for(fresher, 'reference_1')
    assert services.is_fresher(fresher) is True
    assert row['default_kind'] == schema.ACADEMIC


def test_an_experienced_candidates_referees_get_the_professional_form(candidate):
    assert services.is_fresher(candidate) is False
    assert services.contact_for(candidate, 'reference_1')['default_kind'] == \
        schema.PROFESSIONAL
    assert services.contact_for(candidate, 'employer_1')['default_kind'] == \
        schema.EMPLOYER


# ── Consent ──────────────────────────────────────────────────────────────
def test_a_refused_contact_cannot_be_sent(hr_client, candidate):
    """The candidate said no to Employer 2. That answer has to mean something."""
    _send(hr_client, candidate, 'employer_2')

    assert not ReferenceCheck.objects.filter(source_key='employer_2').exists()
    assert len(mail.outbox) == 0


def test_a_blank_permission_is_not_consent(hr_client, candidate):
    form = candidate.employee_form
    form.answers = {**form.answers, 'employer_1_contact_permission': ''}
    form.save()

    _send(hr_client, candidate, 'employer_1')

    assert not ReferenceCheck.objects.filter(source_key='employer_1').exists()


def test_the_refused_row_says_why(hr_client, candidate):
    body = hr_client.get(_manage_url(candidate)).content.decode()
    assert 'Candidate did not permit contact' in body


# ── Sending ──────────────────────────────────────────────────────────────
def test_sending_emails_a_link_and_a_code(hr_client, candidate):
    _send(hr_client, candidate, 'employer_1')

    check = ReferenceCheck.objects.get(source_key='employer_1')
    assert check.kind == schema.EMPLOYER
    assert check.invite_count == 1
    assert len(mail.outbox) == 1

    email = mail.outbox[0]
    assert email.to == ['hr@acme.com']
    assert str(check.token) in email.body
    assert re.search(r'code is:\s*\d{6}', email.body)


def test_the_code_is_never_stored_in_plaintext(hr_client, candidate):
    _send(hr_client, candidate, 'employer_1')
    check = ReferenceCheck.objects.get(source_key='employer_1')
    otp = _otp_from_outbox()

    assert otp not in check.otp_hash
    assert check.check_otp(otp) is True


def test_hr_can_correct_a_stale_address(hr_client, candidate):
    _send(hr_client, candidate, 'employer_1',
          recipient_email='newhr@acme.com', recipient_name='Acme People Team')

    check = ReferenceCheck.objects.get(source_key='employer_1')
    assert check.recipient_email == 'newhr@acme.com'
    assert mail.outbox[0].to == ['newhr@acme.com']


def test_hr_can_override_which_form_is_sent(hr_client, fresher):
    """The fresher signal is a default, not a verdict."""
    _send(hr_client, fresher, 'reference_1', kind=schema.PROFESSIONAL)

    assert ReferenceCheck.objects.get(source_key='reference_1').kind == \
        schema.PROFESSIONAL


def test_sending_twice_resends_to_the_same_row(hr_client, candidate):
    _send(hr_client, candidate, 'employer_1')
    first = _otp_from_outbox()
    _send(hr_client, candidate, 'employer_1')

    assert ReferenceCheck.objects.filter(source_key='employer_1').count() == 1
    check = ReferenceCheck.objects.get(source_key='employer_1')
    assert check.invite_count == 2
    assert check.check_otp(first) is False, 'the old code still works'


def test_nothing_is_sent_before_interviewing(hr_client, candidate):
    candidate.recruiter_status = 'shortlisted'
    candidate.save()

    _send(hr_client, candidate, 'employer_1')

    assert not ReferenceCheck.objects.exists()


def test_a_completed_check_is_not_resent(hr_client, candidate):
    _send(hr_client, candidate, 'employer_1')
    check = ReferenceCheck.objects.get(source_key='employer_1')
    check.is_submitted = True
    check.save()
    mail.outbox.clear()

    _send(hr_client, candidate, 'employer_1')

    assert len(mail.outbox) == 0


# ── HR access ────────────────────────────────────────────────────────────
def test_an_ordinary_recruiter_cannot_manage_checks(authenticated_client, candidate):
    response = authenticated_client.get(_manage_url(candidate))
    assert response.status_code == 302
    assert reverse('core:dashboard') in response.url


def test_an_ordinary_recruiter_does_not_see_the_card(authenticated_client, candidate):
    body = authenticated_client.get(
        reverse('core:resume_detail', kwargs={'uuid': candidate.uuid})
    ).content.decode()
    assert 'Reference &amp; Employment Checks' not in body


def test_hr_sees_the_card(hr_client, candidate):
    body = hr_client.get(
        reverse('core:resume_detail', kwargs={'uuid': candidate.uuid})
    ).content.decode()
    assert 'Reference &amp; Employment Checks' in body


# ── The respondent's side ────────────────────────────────────────────────
@pytest.fixture
def sent_check(hr_client, candidate):
    _send(hr_client, candidate, 'employer_1')
    return ReferenceCheck.objects.get(source_key='employer_1')


def _entry(check):
    return reverse('reference_checks:entry', kwargs={'token': check.token})


def _verify(check):
    return reverse('reference_checks:verify', kwargs={'token': check.token})


def _step(check, step_key):
    return reverse('reference_checks:step',
                   kwargs={'token': check.token, 'step_key': step_key})


def test_no_section_is_named_after_a_reserved_url_segment():
    """Sections are served from /verification/<token>/<step_key>/, the last
    pattern in the list. A section called `verify` or `done` would be swallowed
    by the pattern above it and become permanently unreachable -- with the
    respondent bounced back to the code page forever, and nothing in the logs
    to say why."""
    reserved = {'verify', 'done', 'resend-code', 'resend_code'}
    for kind in (schema.EMPLOYER, schema.PROFESSIONAL, schema.ACADEMIC):
        clash = reserved.intersection(schema.step_keys(kind))
        assert not clash, f'{kind} has section(s) named {sorted(clash)}'


def test_the_link_alone_never_reveals_who_applied(client, sent_check):
    """The code is emailed to the same inbox as the link, so it cannot defend
    against someone reading that inbox. What it does defend against is the link
    escaping it -- forwarded, pasted, left in a shared browser. For that to be
    worth anything, no page reachable with the token alone may name the
    candidate.
    """
    name = sent_check.resume.candidate_name
    surname = name.split()[-1]

    pages = [client.get(_verify(sent_check), follow=True)]

    sent_check.is_submitted = True
    sent_check.submitted_at = timezone.now()
    sent_check.save(update_fields=['is_submitted', 'submitted_at'])
    pages.append(client.get(_entry(sent_check), follow=True))
    pages.append(client.get(
        reverse('reference_checks:done', kwargs={'token': sent_check.token}),
        follow=True))

    sent_check.is_submitted = False
    sent_check.token_expires_at = timezone.now() - timedelta(days=1)
    sent_check.save(update_fields=['is_submitted', 'token_expires_at'])
    pages.append(client.get(_entry(sent_check), follow=True))

    for page in pages:
        body = page.content.decode()
        assert name not in body, f'{page.request["PATH_INFO"]} names the candidate'
        assert surname not in body, f'{page.request["PATH_INFO"]} leaks the surname'


def test_the_link_alone_does_not_open_the_form(client, sent_check):
    response = client.get(_entry(sent_check))
    assert response.status_code == 302
    assert 'verify' in response.url

    response = client.get(_step(sent_check, 'verifier'))
    assert response.status_code == 302
    assert 'verify' in response.url


def test_the_right_code_opens_the_first_section(client, sent_check):
    response = client.post(_verify(sent_check), {'code': _otp_from_outbox()})

    assert response.status_code == 302
    assert response.url == _step(sent_check, 'verifier')


def test_wrong_codes_lock_the_link(client, sent_check):
    for _ in range(ReferenceCheck.OTP_MAX_ATTEMPTS):
        client.post(_verify(sent_check), {'code': '000000'})

    sent_check.refresh_from_db()
    assert sent_check.otp_is_locked
    assert sent_check.check_otp(_otp_from_outbox()) is False


def test_an_unknown_token_is_a_page_not_a_crash(db, client):
    import uuid as _uuid
    response = client.get(
        reverse('reference_checks:entry', kwargs={'token': _uuid.uuid4()}))
    assert response.status_code == 404
    assert b'no longer valid' in response.content


def test_a_respondent_sees_only_their_own_candidate(client, sent_check):
    client.post(_verify(sent_check), {'code': _otp_from_outbox()})

    body = client.get(_step(sent_check, 'verifier')).content.decode()

    assert 'Ayesha Rahman' in body
    # Nothing about how the candidate was scored, or who else was asked.
    assert 'Nadia Haque' not in body
    assert 'recruiter' not in body.lower()


# ── Filling it in ────────────────────────────────────────────────────────
def _verified(client, check):
    client.post(_verify(check), {'code': _otp_from_outbox()})
    return client


VERIFIER = {
    'verifier_name': 'Rehana Karim',
    'verifier_organisation': 'Acme Ltd',
    'verifier_designation': 'Head of HR',
    'verifier_relationship': 'hr',
}


def test_a_respondents_save_cannot_undo_a_code_hr_issued_meanwhile(
        client, sent_check, monkeypatch):
    """The mirror of the resend race, and the half that select_for_update does
    not cover: the row lock only holds off other lockers, and HR's resend takes
    no lock. If this view writes the whole row, it puts back the OTP columns as
    they were when it loaded them -- so the code HR just emailed stops working
    and the respondent is locked out of a form they were mid-way through.
    """
    from apps.reference_checks.forms import StepForm

    _verified(client, sent_check)
    original_storable = StepForm.storable_answers

    def storable_while_hr_resends(self):
        # HR presses Resend between this view taking the row lock and writing.
        hr_copy = ReferenceCheck.objects.get(pk=sent_check.pk)
        hr_copy.issue_otp()
        hr_copy.save(update_fields=[*ReferenceCheck.OTP_FIELDS, 'updated_at'])
        return original_storable(self)

    monkeypatch.setattr(StepForm, 'storable_answers', storable_while_hr_resends)
    before = ReferenceCheck.objects.get(pk=sent_check.pk).otp_hash

    client.post(_step(sent_check, 'verifier'), VERIFIER)

    after = ReferenceCheck.objects.get(pk=sent_check.pk)
    assert after.otp_hash != before, (
        "HR's new code is gone -- either this view wrote the whole row and put "
        'the old one back, or the interleave above never ran'
    )
    assert after.answers['verifier_name'] == 'Rehana Karim', 'the section was lost'
    assert after.current_step == 'employment'


def test_sections_save_and_advance(client, sent_check):
    _verified(client, sent_check)

    response = client.post(_step(sent_check, 'verifier'), VERIFIER)

    sent_check.refresh_from_db()
    assert response.status_code == 302
    assert sent_check.current_step == 'employment'
    assert sent_check.answers['verifier_name'] == 'Rehana Karim'


def test_a_respondent_cannot_skip_to_the_last_section(client, sent_check):
    """The final section carries the rehire answer; it must not stand alone."""
    _verified(client, sent_check)

    response = client.get(_step(sent_check, 'conduct'))

    assert response.status_code == 302
    assert response.url == _step(sent_check, 'verifier')


def test_yes_without_the_detail_is_rejected(client, sent_check):
    _verified(client, sent_check)
    client.post(_step(sent_check, 'verifier'), VERIFIER)

    client.post(_step(sent_check, 'employment'), {
        'was_employed': 'yes', 'had_promotion': 'yes',   # no promotion_details
    })

    sent_check.refresh_from_db()
    assert sent_check.current_step == 'employment', 'saved without the detail'


def test_yes_with_the_detail_saves(client, sent_check):
    _verified(client, sent_check)
    client.post(_step(sent_check, 'verifier'), VERIFIER)

    client.post(_step(sent_check, 'employment'), {
        'was_employed': 'yes', 'had_promotion': 'yes',
        'promotion_details': 'Promoted to Senior Engineer in 2023',
    })

    sent_check.refresh_from_db()
    assert sent_check.current_step == 'conduct'


def test_not_known_needs_no_detail(client, sent_check):
    _verified(client, sent_check)
    client.post(_step(sent_check, 'verifier'), VERIFIER)

    client.post(_step(sent_check, 'employment'),
                {'was_employed': 'yes', 'had_promotion': 'not_known'})

    sent_check.refresh_from_db()
    assert sent_check.current_step == 'conduct'


def test_the_last_section_completes_the_request(client, sent_check):
    _verified(client, sent_check)
    client.post(_step(sent_check, 'verifier'), VERIFIER)
    client.post(_step(sent_check, 'employment'), {'was_employed': 'yes'})

    response = client.post(_step(sent_check, 'conduct'), {
        'rating_overall': 'good',
        'disciplinary_action': 'no',
        'integrity_concerns': 'no',
    })

    sent_check.refresh_from_db()
    assert sent_check.is_submitted
    assert sent_check.submitted_at
    assert response.url == reverse('reference_checks:done',
                                   kwargs={'token': sent_check.token})


def test_a_completed_request_cannot_be_reopened(client, sent_check):
    sent_check.is_submitted = True
    sent_check.save()
    _verified(client, sent_check)

    for url in (_entry(sent_check), _step(sent_check, 'verifier')):
        assert b'already have your response' in client.get(url).content


def test_a_resend_cannot_revert_answers_saved_while_it_was_running(
        sent_check, monkeypatch):
    """HR and the respondent write the same row from different processes.

    The send task loads the row, generates a code, then writes back. If it
    writes the whole row, everything the respondent saved inside that window is
    replaced by what the task read on the way in -- their work simply vanishes,
    with nothing logged. The interleave is forced here because in production it
    is a window of microseconds that no ordinary test would ever hit.
    """
    from apps.reference_checks.tasks import send_reference_check_request

    original_issue_otp = ReferenceCheck.issue_otp

    def issue_otp_while_the_respondent_saves(self):
        ReferenceCheck.objects.filter(pk=self.pk).update(
            answers={'was_employed': 'yes'}, current_step='conduct')
        return original_issue_otp(self)

    monkeypatch.setattr(ReferenceCheck, 'issue_otp',
                        issue_otp_while_the_respondent_saves)
    send_reference_check_request(sent_check.pk)

    fresh = ReferenceCheck.objects.get(pk=sent_check.pk)
    assert fresh.answers == {'was_employed': 'yes'}
    assert fresh.current_step == 'conduct'
    assert fresh.invited_at is not None, 'the resend itself must still happen'


def test_an_expired_link_says_so(client, sent_check):
    sent_check.token_expires_at = timezone.now() - timedelta(days=1)
    sent_check.save()

    assert b'has expired' in client.get(_entry(sent_check)).content


# ── What HR gets back ────────────────────────────────────────────────────
def test_a_concerning_reply_is_flagged(candidate):
    check = ReferenceCheck.objects.create(
        resume=candidate, kind=schema.EMPLOYER, source_key='employer_1',
        recipient_name='Acme HR', recipient_email='hr@acme.com',
        is_submitted=True,
        answers={'integrity_concerns': 'yes', 'integrity_details': 'Substantiated'},
    )
    assert check.flagged is True


def test_a_clean_reply_is_not_flagged(candidate):
    check = ReferenceCheck.objects.create(
        resume=candidate, kind=schema.EMPLOYER, source_key='employer_1',
        recipient_name='Acme HR', recipient_email='hr@acme.com',
        is_submitted=True,
        answers={'integrity_concerns': 'no', 'disciplinary_action': 'no',
                 'rehire_eligible': 'yes', 'separation_nature': 'resignation'},
    )
    assert check.flagged is False


def test_involuntary_separation_is_flagged_on_its_own(candidate):
    check = ReferenceCheck.objects.create(
        resume=candidate, kind=schema.EMPLOYER, source_key='employer_1',
        recipient_name='Acme HR', recipient_email='hr@acme.com',
        is_submitted=True,
        answers={'integrity_concerns': 'no', 'disciplinary_action': 'no',
                 'separation_nature': 'involuntary'},
    )
    assert check.flagged is True


VERDICT_CHOICES = [
    # kind, question, value, must the badge appear
    (schema.EMPLOYER, 'rehire_eligible', 'yes', False),
    (schema.EMPLOYER, 'rehire_eligible', 'conditional', True),
    (schema.EMPLOYER, 'rehire_eligible', 'no', True),
    (schema.EMPLOYER, 'rehire_eligible', 'not_disclosed', False),
    (schema.PROFESSIONAL, 'hire_again', 'yes', False),
    (schema.PROFESSIONAL, 'hire_again', 'yes_reservations', True),
    (schema.PROFESSIONAL, 'hire_again', 'no', True),
    (schema.PROFESSIONAL, 'hire_again', 'unable', False),
    (schema.PROFESSIONAL, 'recommend', 'yes', False),
    (schema.PROFESSIONAL, 'recommend', 'yes_reservations', True),
    (schema.PROFESSIONAL, 'recommend', 'no', True),
    (schema.ACADEMIC, 'recommend', 'strongly', False),
    (schema.ACADEMIC, 'recommend', 'recommend', False),
    (schema.ACADEMIC, 'recommend', 'reservations', True),
    (schema.ACADEMIC, 'recommend', 'unable', True),
]


@pytest.mark.parametrize('kind,question,value,expected', VERDICT_CHOICES)
def test_every_verdict_answer_flags_or_does_not_as_intended(
        candidate, kind, question, value, expected):
    """Pin each choice to its badge, so renaming one in the schema breaks a
    test rather than quietly switching the flag off."""
    assert value in dict(schema.questions_by_key(kind)[question]['choices']), (
        f'{kind}.{question} no longer offers {value!r}'
    )
    check = ReferenceCheck.objects.create(
        resume=candidate, kind=kind, source_key='employer_1',
        recipient_name='Referee', recipient_email='referee@example.com',
        is_submitted=True, answers={question: value},
    )
    assert check.flagged is expected


def test_a_section_left_blank_is_shown_as_blank_not_as_an_empty_box(
        hr_client, candidate):
    """Silence on a conduct question is information. The section must still
    appear, and must say plainly that nothing was answered -- a bare heading
    with nothing under it reads as a rendering fault."""
    answered, blank = 'employment', 'conduct'
    assert 'was_employed' in schema.questions_by_key(schema.EMPLOYER), \
        'the key this test answers no longer exists'

    check = ReferenceCheck.objects.create(
        resume=candidate, kind=schema.EMPLOYER, source_key='employer_1',
        recipient_name='Acme HR', recipient_email='hr@acme.com',
        is_submitted=True, answers={'was_employed': 'yes'},
    )
    sections = {s['key']: s for s in check.answered_sections()}
    assert len(sections[answered]['rows']) == 1, 'the answered section lost its row'
    assert sections[blank]['rows'] == [], 'the untouched section should hold nothing'

    body = hr_client.get(reverse('reference_checks:response',
                                 kwargs={'uuid': candidate.uuid,
                                         'pk': check.pk})).content.decode()

    # Titles are escaped in the page, so compare the way Django wrote them.
    from django.utils.html import escape
    assert escape(sections[blank]['title']) in body, 'the blank section vanished'
    assert escape(sections[answered]['title']) in body
    assert 'left this section blank' in body


def test_hr_can_read_a_completed_response(hr_client, candidate):
    check = ReferenceCheck.objects.create(
        resume=candidate, kind=schema.PROFESSIONAL, source_key='reference_1',
        recipient_name='Karim Uddin', recipient_email='karim@acme.com',
        is_submitted=True,
        answers={'referee_name': 'Karim Uddin', 'recommend': 'yes',
                 'strongest_qualities': 'Very thorough'},
    )

    body = hr_client.get(reverse('reference_checks:response',
                                 kwargs={'uuid': candidate.uuid,
                                         'pk': check.pk})).content.decode()

    assert 'Very thorough' in body
    assert 'Recommends' in body


def test_the_summary_counts_only_contactable_people(candidate):
    """Employer 2 was refused, so it is not part of the denominator."""
    summary = services.summarise(candidate)
    assert summary['contactable'] == 3
    assert summary['completed'] == 0


# ── Schema integrity ─────────────────────────────────────────────────────
@pytest.mark.parametrize('kind', [schema.EMPLOYER, schema.PROFESSIONAL,
                                  schema.ACADEMIC])
def test_every_form_is_three_sections_that_chain(kind):
    keys = schema.step_keys(kind)
    assert len(keys) == 3
    for index, key in enumerate(keys):
        expected = keys[index + 1] if index + 1 < len(keys) else None
        assert schema.get_step(kind, key)['next'] == expected


@pytest.mark.parametrize('kind', [schema.EMPLOYER, schema.PROFESSIONAL,
                                  schema.ACADEMIC])
def test_no_duplicate_keys(kind):
    keys = [q['key'] for step in schema.steps(kind) for q in step['questions']]
    assert len(keys) == len(set(keys))


@pytest.mark.parametrize('kind', [schema.EMPLOYER, schema.PROFESSIONAL,
                                  schema.ACADEMIC])
def test_every_judgement_has_an_escape_hatch(kind):
    """A respondent who cannot comment must be able to say so, not guess."""
    for step in schema.steps(kind):
        for question in step['questions']:
            if not question['key'].startswith('rating_'):
                continue
            values = {value for value, _ in question['choices']}
            assert values & {'na', 'unable'}, question['key']


@pytest.mark.parametrize('kind', [schema.EMPLOYER, schema.PROFESSIONAL,
                                  schema.ACADEMIC])
def test_conditional_rules_point_at_real_questions(kind):
    by_key = schema.questions_by_key(kind)
    for rule in schema.CONDITIONAL_RULES[kind]:
        assert rule['trigger'] in by_key, rule['trigger']
        allowed = {v for v, _ in by_key[rule['trigger']]['choices']}
        assert set(rule['when']) <= allowed, rule
        for key in rule['keys']:
            assert key in by_key, key
            # A conditionally-required field must not also be required outright.
            assert not by_key[key]['required'], key


def test_no_section_letters_are_shown():
    """The paper forms label sections A-E; those mean nothing to a respondent."""
    for kind in (schema.EMPLOYER, schema.PROFESSIONAL, schema.ACADEMIC):
        for step in schema.steps(kind):
            for text in [step['title'], step.get('description', '')]:
                assert not re.search(r'\bSection [A-G]\b', text), text
