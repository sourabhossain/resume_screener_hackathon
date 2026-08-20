"""End-to-end coverage of the invite → OTP → wizard → submit flow."""
import re

import pytest
from django.core import mail
from django.urls import reverse

from apps.core.models import Resume
from apps.employee_form import schema
from apps.employee_form.models import EmployeeForm
from apps.employee_form.services import InviteError, issue_invite


@pytest.fixture
def candidate(db, sample_job):
    return Resume.objects.create(
        job=sample_job,
        candidate_name='Ayesha Rahman',
        email='ayesha@example.com',
        phone='+8801711123456',
        final_score=82,
    )


def _otp_from_outbox():
    """Pull the plaintext code out of the most recent invitation email."""
    body = mail.outbox[-1].body
    match = re.search(r'code is:\s*(\d{6})', body)
    assert match, f'No OTP found in email body:\n{body}'
    return match.group(1)


# ── Invitation ───────────────────────────────────────────────────────────
def test_shortlisting_sends_invite_with_link_and_otp(authenticated_client, candidate):
    url = reverse('core:resume_status_update', kwargs={'uuid': candidate.uuid})
    response = authenticated_client.post(url, {'recruiter_status': 'shortlisted'})

    assert response.status_code == 302
    form = EmployeeForm.objects.get(resume=candidate)
    assert form.invite_count == 1
    assert len(mail.outbox) == 1

    email = mail.outbox[0]
    assert email.to == ['ayesha@example.com']
    assert str(form.token) in email.body
    assert re.search(r'code is:\s*\d{6}', email.body)


def test_otp_is_never_stored_in_plaintext(authenticated_client, candidate):
    authenticated_client.post(
        reverse('core:resume_status_update', kwargs={'uuid': candidate.uuid}),
        {'recruiter_status': 'shortlisted'},
    )
    form = EmployeeForm.objects.get(resume=candidate)
    otp = _otp_from_outbox()

    assert otp not in form.otp_hash
    assert form.otp_hash.startswith('pbkdf2_') or '$' in form.otp_hash
    assert form.check_otp(otp) is True


def test_shortlisting_again_does_not_resend(authenticated_client, candidate):
    url = reverse('core:resume_status_update', kwargs={'uuid': candidate.uuid})
    authenticated_client.post(url, {'recruiter_status': 'shortlisted'})
    authenticated_client.post(url, {'recruiter_status': 'phone_screen'})
    authenticated_client.post(url, {'recruiter_status': 'shortlisted'})

    assert len(mail.outbox) == 1
    assert EmployeeForm.objects.get(resume=candidate).invite_count == 1


def test_recruiter_can_explicitly_resend(authenticated_client, candidate):
    authenticated_client.post(
        reverse('core:resume_status_update', kwargs={'uuid': candidate.uuid}),
        {'recruiter_status': 'shortlisted'},
    )
    authenticated_client.post(
        reverse('employee_form:send', kwargs={'uuid': candidate.uuid})
    )

    assert len(mail.outbox) == 2
    assert EmployeeForm.objects.get(resume=candidate).invite_count == 2


def test_candidate_without_email_reports_the_reason(db, sample_job):
    resume = Resume.objects.create(job=sample_job, candidate_name='No Email', email='')
    with pytest.raises(InviteError, match='no email address'):
        issue_invite(resume)
    assert len(mail.outbox) == 0


# ── OTP gate ─────────────────────────────────────────────────────────────
def test_link_requires_otp_before_the_form_opens(client, candidate):
    form = issue_invite(candidate)
    entry = reverse('employee_form:entry', kwargs={'token': form.token})

    response = client.get(entry)
    assert response.status_code == 302
    assert response.url == reverse(
        'employee_form:verify', kwargs={'token': form.token}
    )


def test_first_step_is_not_reachable_without_verifying(client, candidate):
    form = issue_invite(candidate)
    response = client.get(reverse('employee_form:step', kwargs={
        'token': form.token, 'step_key': schema.FIRST_STEP,
    }))
    assert response.status_code == 302
    assert 'verify' in response.url


def test_correct_otp_opens_the_first_step(client, candidate):
    form = issue_invite(candidate)
    otp = _otp_from_outbox()

    response = client.post(
        reverse('employee_form:verify', kwargs={'token': form.token}),
        {'code': otp},
    )
    assert response.status_code == 302
    assert response.url == reverse('employee_form:step', kwargs={
        'token': form.token, 'step_key': schema.FIRST_STEP,
    })


def test_wrong_otp_counts_attempts_and_locks_out(client, candidate):
    form = issue_invite(candidate)
    url = reverse('employee_form:verify', kwargs={'token': form.token})

    for _ in range(EmployeeForm.OTP_MAX_ATTEMPTS):
        client.post(url, {'code': '000000'})

    form.refresh_from_db()
    assert form.otp_is_locked

    # The real code no longer works once locked out.
    assert form.check_otp(_otp_from_outbox()) is False


def test_expired_otp_is_rejected(client, candidate):
    from datetime import timedelta
    from django.utils import timezone

    form = issue_invite(candidate)
    otp = _otp_from_outbox()
    form.otp_expires_at = timezone.now() - timedelta(minutes=1)
    form.save(update_fields=['otp_expires_at'])

    assert form.otp_is_expired
    assert form.check_otp(otp) is False


def test_resend_issues_a_new_code_and_clears_attempts(client, candidate):
    form = issue_invite(candidate)
    first_otp = _otp_from_outbox()
    form.otp_attempts = 3
    form.save(update_fields=['otp_attempts'])

    client.post(reverse('employee_form:resend_code', kwargs={'token': form.token}))

    form.refresh_from_db()
    second_otp = _otp_from_outbox()
    assert form.otp_attempts == 0
    assert second_otp != first_otp
    assert form.check_otp(first_otp) is False


# ── Wizard ───────────────────────────────────────────────────────────────
def _verified_client(client, candidate):
    form = issue_invite(candidate)
    client.post(
        reverse('employee_form:verify', kwargs={'token': form.token}),
        {'code': _otp_from_outbox()},
    )
    return client, form


def test_expired_link_shows_the_expired_page(client, candidate):
    from datetime import timedelta
    from django.utils import timezone

    form = issue_invite(candidate)
    form.token_expires_at = timezone.now() - timedelta(days=1)
    form.save(update_fields=['token_expires_at'])

    response = client.get(reverse('employee_form:entry', kwargs={'token': form.token}))
    assert response.status_code == 200
    assert b'This link has expired' in response.content


def test_submitted_form_cannot_be_opened_again(client, candidate):
    client, form = _verified_client(client, candidate)
    form.is_submitted = True
    form.save(update_fields=['is_submitted'])

    for name in ('entry', 'verify'):
        response = client.get(reverse(f'employee_form:{name}', kwargs={'token': form.token}))
        assert b'already submitted' in response.content.lower()

    response = client.get(reverse('employee_form:step', kwargs={
        'token': form.token, 'step_key': schema.FIRST_STEP,
    }))
    assert b'already submitted' in response.content.lower()


def test_submitted_form_rejects_further_posts(client, candidate):
    client, form = _verified_client(client, candidate)
    form.is_submitted = True
    form.save(update_fields=['is_submitted'])

    response = client.post(
        reverse('employee_form:step',
                kwargs={'token': form.token, 'step_key': schema.FIRST_STEP}),
        {'candidate_full_name': 'Tampered'},
    )
    form.refresh_from_db()
    assert b'already submitted' in response.content.lower()
    assert 'candidate_full_name' not in (form.answers or {})


def test_step_off_the_branch_redirects_back(client, candidate):
    """A hand-typed URL for a section the answers do not lead to is bounced.

    Nothing says the candidate has previous employment yet, so the employer
    sections are not on their path at all.
    """
    client, form = _verified_client(client, candidate)

    response = client.get(reverse('employee_form:step', kwargs={
        'token': form.token, 'step_key': 'employer_1',
    }))
    assert response.status_code == 302
    assert schema.FIRST_STEP in response.url


def test_cannot_skip_ahead_to_a_later_step(client, candidate):
    """The declaration is on the empty-answer path, so it must still be gated.

    Without this the candidate could open the final step directly and submit,
    bypassing Sections A-C.
    """
    client, form = _verified_client(client, candidate)

    response = client.get(reverse('employee_form:step', kwargs={
        'token': form.token, 'step_key': 'd7_declaration',
    }))
    assert response.status_code == 302
    assert schema.FIRST_STEP in response.url


def test_cannot_submit_by_posting_the_final_step_early(client, candidate):
    client, form = _verified_client(client, candidate)

    client.post(
        reverse('employee_form:step',
                kwargs={'token': form.token, 'step_key': 'd7_declaration'}),
        {
            'total_experience_years': '5',
            'current_responsibilities': 'Everything',
            'measurable_achievements': 'Many',
            'availability_status': 'immediately_available',
            'declaration_agreement': 'agree',
            'typed_signature': 'Ayesha Rahman',
            'declaration_date': '2026-08-20',
        },
    )

    form.refresh_from_db()
    assert form.is_submitted is False
    assert form.current_step == schema.FIRST_STEP


def test_back_to_an_earlier_step_is_allowed(client, candidate, django_user_model):
    client, form = _verified_client(client, candidate)
    form.current_step = 'employment_gate'
    form.answers = {'candidate_full_name': 'Ayesha Rahman'}
    form.save(update_fields=['current_step', 'answers'])

    response = client.get(reverse('employee_form:step', kwargs={
        'token': form.token, 'step_key': schema.FIRST_STEP,
    }))
    assert response.status_code == 200


def test_unknown_step_is_404(client, candidate):
    client, form = _verified_client(client, candidate)
    response = client.get(reverse('employee_form:step', kwargs={
        'token': form.token, 'step_key': 'not-a-step',
    }))
    assert response.status_code == 404


# ── Flow (PDF: linear Sections A-C, then Section D branches) ─────────────
def test_section_c_is_linear_all_four_employers_then_references():
    """The PDF has no employment gate and no "another employer?" branch."""
    path = schema.step_path({})
    expected = [
        'section_a', 'section_b',
        'employer_1', 'employer_2', 'employer_3', 'employer_4',
        'reference_1', 'reference_2', 'department',
    ]
    assert path[:len(expected)] == expected


def test_no_employer_block_is_hard_required():
    """A fresher must be able to submit, so no employer field is required outright."""
    for index in (1, 2, 3, 4):
        for question in schema.STEPS_BY_KEY[f'employer_{index}']['questions']:
            assert not question['required'], question['key']


def test_banking_department_routes_to_d1_sales():
    """The one department-to-section mapping confirmed by the client's own form."""
    answers = {'department': 'banking_financial_services'}
    # D1 is rendered inside the department page, so it is absorbed rather than
    # being its own step -- but it still names itself for the recruiter view.
    assert schema.inline_target('department', answers) == 'd1_sales'
    assert 'd1_sales' not in schema.step_path(answers)
    assert 'd1_sales' in schema.review_path(answers)
    assert schema.step_path(answers)[-1] == schema.FINAL_STEP


def test_each_department_reaches_its_mapped_role_section():
    """D1-D6 all carry questions now, so every mapping must actually land."""
    for value, label in schema.DEPARTMENT_CHOICES:
        target = schema.DEPARTMENT_ROUTING.get(value)
        assert target, f'{value} has no routing entry'
        answers = {'department': value}
        assert schema.inline_target('department', answers) == target, (
            f'{label} does not route to {target}')
        keys = {q['key'] for q in schema.wizard_questions('department', answers)}
        assert keys >= {q['key'] for q in schema.get_step(target)['questions']}, (
            f'{label} does not render {target} on the department page')
        assert schema.step_path(answers)[-1] == schema.FINAL_STEP, (
            f'{label} does not reach the declaration')


def test_only_one_role_section_is_ever_shown():
    """A candidate must not be asked another department's questions."""
    role_steps = {'d1_sales', 'd2_marketing', 'd3_finance',
                  'd4_technology', 'd5_operations', 'd6_corporate'}
    for value, label in schema.DEPARTMENT_CHOICES:
        answers = {'department': value}
        seen = set(schema.review_path(answers)) & role_steps
        assert len(seen) == 1, f'{label} sees {seen}'
        # And the rendered page carries exactly that section's questions.
        asked = {q['key'] for q in schema.wizard_questions('department', answers)}
        for other in role_steps - seen:
            other_keys = {q['key'] for q in schema.get_step(other)['questions']}
            assert not (asked & other_keys), f'{label} is asked {other} questions'


def test_every_role_section_is_reachable_by_some_department():
    """A section no department maps to would be dead weight."""
    targets = set(schema.DEPARTMENT_ROUTING.values())
    for key in ('d1_sales', 'd2_marketing', 'd3_finance',
                'd4_technology', 'd5_operations', 'd6_corporate'):
        assert key in targets, f'{key} is unreachable'


# ── Schema integrity ─────────────────────────────────────────────────────
def test_question_keys_are_unique():
    keys = [q['key'] for step in schema.STEPS for q in step['questions']]
    assert len(keys) == len(set(keys)), 'duplicate question key in schema'


def test_choice_questions_all_declare_choices():
    for question in schema.QUESTIONS_BY_KEY.values():
        if question['type'] in schema.CHOICE_TYPES:
            assert question.get('choices'), f"{question['key']} has no choices"


def test_every_step_key_referenced_exists():
    for step in schema.STEPS:
        nxt = step['next']
        if isinstance(nxt, str):
            assert nxt in schema.STEPS_BY_KEY, f"{step['key']} points at missing {nxt}"
    for target in schema.DEPARTMENT_ROUTING.values():
        assert target in schema.STEPS_BY_KEY


def test_numbering_is_sequential_with_no_gaps():
    answers = {'department': 'banking_financial_services'}
    numbers = []
    for step_key in schema.review_path(answers):
        numbers += [q['number'] for q in schema.numbered_questions(step_key, answers)]
    assert numbers == list(range(1, len(numbers) + 1))


# ── Prefill ──────────────────────────────────────────────────────────────
def test_known_details_are_prefilled(client, candidate):
    """Name, phone, email and position come from the application itself."""
    form = issue_invite(candidate)
    client.post(reverse('employee_form:verify', kwargs={'token': form.token}),
                {'code': _otp_from_outbox()})

    response = client.get(reverse('employee_form:step', kwargs={
        'token': form.token, 'step_key': schema.FIRST_STEP}))
    body = response.content.decode()

    assert 'value="Ayesha Rahman"' in body
    assert 'value="+8801711123456"' in body
    assert 'value="ayesha@example.com"' in body
    assert f'value="{candidate.job.title}"' in body
    assert 'please check it matches your documents' in body


def test_ai_extracted_fields_are_not_prefilled(client, db, sample_job):
    """The candidate must declare document-backed facts themselves."""
    resume = Resume.objects.create(
        job=sample_job, candidate_name='Extracted Person',
        email='ex@example.com', experience_years=7.5,
        education=['BSc in CSE, University of Dhaka'],
        certifications=['AWS Solutions Architect'],
    )
    from apps.employee_form.prefill import prefill_answers
    values = prefill_answers(resume)

    for key in ('bachelors_institution', 'total_experience_years',
                'training_certification_names', 'hsc_result', 'nid_number'):
        assert key not in values, f'{key} must not be prefilled from AI extraction'


def test_signature_is_never_prefilled(candidate):
    from apps.employee_form.prefill import prefill_answers
    values = prefill_answers(candidate)
    assert 'typed_signature' not in values
    assert values['declaration_date']


def test_saved_answers_are_never_overwritten_by_prefill(client, candidate):
    form = issue_invite(candidate)
    form.answers = {'candidate_full_name': 'Name As On NID'}
    form.save(update_fields=['answers'])
    client.post(reverse('employee_form:verify', kwargs={'token': form.token}),
                {'code': _otp_from_outbox()})

    response = client.get(reverse('employee_form:step', kwargs={
        'token': form.token, 'step_key': schema.FIRST_STEP}))
    body = response.content.decode()

    assert 'value="Name As On NID"' in body
    assert 'value="Ayesha Rahman"' not in body


def test_prefilled_values_are_stored_when_the_step_is_submitted(client, candidate):
    form = issue_invite(candidate)
    client.post(reverse('employee_form:verify', kwargs={'token': form.token}),
                {'code': _otp_from_outbox()})

    from django.core.files.uploadedfile import SimpleUploadedFile
    client.post(
        reverse('employee_form:step',
                kwargs={'token': form.token, 'step_key': 'section_a'}),
        {
            'candidate_full_name': 'Ayesha Rahman',
            'mobile_number': '+8801711123456',
            'personal_email': 'ayesha@example.com',
            'position_applied_for': candidate.job.title,
            'nid_number': '123', 'date_of_birth': '1996-04-12',
            'present_address': 'A', 'permanent_address': 'B',
            'address_same': 'no', 'verification_consent': 'yes',
            'nid_copy': SimpleUploadedFile(
                'n.pdf', b'%PDF-1.4 x', content_type='application/pdf'),
        })

    form.refresh_from_db()
    assert form.answers['position_applied_for'] == candidate.job.title


# ── Layout metadata ──────────────────────────────────────────────────────
def test_grouping_never_drops_a_question():
    """A typo in STEP_GROUPS must not silently hide a question."""
    for step in schema.STEPS:
        if not step['questions']:
            continue
        grouped = schema.question_groups(step['key'], {})
        keys = [q['key'] for block in grouped for q in block['questions']]
        expected = [q['key'] for q in schema.wizard_questions(step['key'], {})]
        assert sorted(keys) == sorted(expected), step['key']
        assert len(keys) == len(set(keys)), f"{step['key']} renders a question twice"


def test_short_labels_only_shorten_never_invent():
    """Every wizard label must be derived from the source label, not replaced."""
    for key, short in schema.SHORT_LABELS.items():
        assert key in schema.QUESTIONS_BY_KEY, key
        assert short.strip(), key
        full = schema.QUESTIONS_BY_KEY[key]['label']
        assert len(short) <= len(full), f'{key}: short label is longer than the source'


def test_full_labels_survive_on_the_review_page(client, candidate):
    """The recruiter view has no group headings, so it keeps the source wording."""
    form = issue_invite(candidate)
    form.answers = {'hsc_board': 'Dhaka'}
    form.save(update_fields=['answers'])

    rows = [r for s in form.answered_sections() for r in s['rows']]
    labels = {r['key']: r['label'] for r in rows}
    assert labels['hsc_board'] == 'HSC / A Level / Equivalent — Education Board'


def test_wide_fields_are_never_half_width():
    """Textareas, radios and uploads always take a full row."""
    for question in schema.QUESTIONS_BY_KEY.values():
        if question['type'] in schema.FILE_TYPES or question['type'] in (
                schema.TEXTAREA, schema.RADIO, schema.CHECKBOX):
            assert not schema.is_half_width(question), question['key']


# ── Absorbed sections must still be readable ─────────────────────────────
def test_role_answers_reach_the_recruiter_view(candidate):
    """Section D absorbs its role section for the candidate, not for the reviewer.

    Regression: `answered_sections()` walked the wizard path, so once D4 was
    rendered inside the department page its answers were stored but never shown.
    """
    form = issue_invite(candidate)
    form.answers = {
        'department': 'engineering',
        'tech_stack': 'Django, Postgres, Redis',
        'tech_achievement': 'Cut p95 latency by 40%',
    }
    form.save(update_fields=['answers'])

    assert 'd4_technology' not in form.path          # not a wizard step
    assert 'd4_technology' in form.review_path       # but a reviewable section

    sections = {s['key']: s for s in form.answered_sections()}
    assert 'd4_technology' in sections, 'role answers are invisible to the recruiter'
    values = [r['value'] for r in sections['d4_technology']['rows']]
    assert 'Django, Postgres, Redis' in values
    assert 'Cut p95 latency by 40%' in values


def test_every_role_section_is_readable_back(candidate):
    """Whichever department is chosen, that section's answers must be shown."""
    form = issue_invite(candidate)
    for value, label in schema.DEPARTMENT_CHOICES:
        target = schema.DEPARTMENT_ROUTING[value]
        # First free-text question: a checkbox answer is a list, not a string.
        first_key = next(
            q['key'] for q in schema.get_step(target)['questions']
            if q['type'] not in schema.CHOICE_TYPES
        )
        form.answers = {'department': value, first_key: 'sample answer'}
        form.save(update_fields=['answers'])

        sections = {s['key']: s for s in form.answered_sections()}
        assert target in sections, f'{label}: {target} missing from the review'
        values = [r['value'] for r in sections[target]['rows']]
        assert 'sample answer' in values, f'{label}: answer not shown'


# ── An unknown link explains itself ──────────────────────────────────────
def test_unknown_token_shows_a_readable_page(db, client):
    """A superseded or truncated link must not dump a raw 404 on a candidate."""
    import uuid as uuid_mod
    stale = uuid_mod.uuid4()

    for name, kwargs in [
        ('entry', {}),
        ('verify', {}),
        ('done', {}),
    ]:
        response = client.get(
            reverse(f'employee_form:{name}', kwargs={'token': stale, **kwargs})
        )
        assert response.status_code == 404, name
        body = response.content.decode()
        assert 'This link is no longer valid' in body, name
        # Says nothing about whether that token ever existed.
        assert 'deleted' not in body.lower()

    response = client.get(reverse('employee_form:step', kwargs={
        'token': stale, 'step_key': schema.FIRST_STEP}))
    assert response.status_code == 404
    assert 'This link is no longer valid' in response.content.decode()


def test_unknown_token_on_the_htmx_fragment_is_a_plain_404(db, client):
    import uuid as uuid_mod
    response = client.get(reverse('employee_form:role_fields', kwargs={
        'token': uuid_mod.uuid4(), 'step_key': 'department'}))
    assert response.status_code == 404
    assert 'This link is no longer valid' not in response.content.decode()
