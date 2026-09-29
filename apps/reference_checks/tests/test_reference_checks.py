"""External verification requests to employers and referees.

HR decides who is asked; a stranger answers on an emailed link plus a code. The
two forms follow the client's FINAL PDFs exactly, so the questions are pinned
here label by label.
"""
import re
from datetime import date, timedelta

import pytest
from django.core import mail
from django.urls import reverse
from django.utils import timezone

from apps.core.models import Resume
from apps.employee_form import schema as employee_schema
from apps.employee_form.models import EmployeeForm
from apps.reference_checks import schema, services
from apps.reference_checks.models import ReferenceCheck

EIF_KEYS = {q['key'] for step in employee_schema.STEPS for q in step['questions']}

CANDIDATE_ANSWERS = {
    'candidate_full_name': 'Ayesha Siddiqua Rahman',
    'verification_consent': 'yes',
    'has_employment': 'yes',

    'employer_1_name': 'Acme Ltd',
    'employer_1_hr_email': 'hr@acme.com',
    'employer_1_hr_contact': '+8801711000000',
    'employer_1_contact_permission': 'yes',
    'employer_1_another': 'yes',

    'employer_2_name': 'Globex',
    'employer_2_hr_email': 'people@globex.com',
    'employer_2_contact_permission': 'no',
    'employer_2_another': 'no',

    'reference_1_name': 'Karim Uddin',
    'reference_1_email': 'karim@acme.com',
    'reference_1_designation': 'CTO, Acme Ltd',
    'reference_1_relationship': 'direct_manager',
    'reference_1_contact': '+8801811000000',
    'reference_1_contact_permission': 'yes',

    'reference_2_name': 'Nadia Haque',
    'reference_2_email': 'nadia@example.com',
    'reference_2_designation': 'Professor',
    'reference_2_relationship': 'academic',
    'reference_2_contact_permission': 'yes',
}


def test_the_candidate_answers_this_suite_invents_are_real_form_keys():
    invented = sorted(k for k in CANDIDATE_ANSWERS if k not in EIF_KEYS)
    assert not invented, f'the employee form has no such question(s): {invented}'


def test_every_eif_key_services_reads_is_real():
    for suffix in ('name', 'hr_email', 'hr_contact', 'contact_permission', 'another'):
        assert f'employer_1_{suffix}' in EIF_KEYS, suffix
    for suffix in ('name', 'email', 'contact', 'designation', 'relationship',
                   'contact_permission'):
        assert f'reference_1_{suffix}' in EIF_KEYS, suffix
    assert 'candidate_full_name' in EIF_KEYS
    assert 'verification_consent' in EIF_KEYS


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
    resume = Resume.objects.create(
        job=sample_job, candidate_name='Tanvir Ahmed',
        email='tanvir@example.com', recruiter_status='interviewing',
    )
    EmployeeForm.objects.create(resume=resume, is_submitted=True, answers={
        'has_employment': 'no',
        'reference_1_name': 'Prof. Rahman',
        'reference_1_email': 'rahman@university.edu',
        'reference_1_relationship': 'academic',
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


def _send(hr_client, resume, source_key, **overrides):
    row = services.contact_for(resume, source_key)
    data = {
        'kind': row['default_kind'],
        'recipient_name': row['recipient_name'],
        'recipient_email': row['recipient_email'],
        'recipient_organisation': row['recipient_organisation'],
        **overrides,
    }
    return hr_client.post(reverse('reference_checks:send', kwargs={
        'uuid': resume.uuid, 'source_key': source_key}), data)


def _otp_from_outbox():
    body = mail.outbox[-1].body
    match = re.search(r'code is:\s*(\d{6})', body)
    assert match, f'no code in:\n{body}'
    return match.group(1)


def _entry(check):
    return reverse('reference_checks:entry', kwargs={'token': check.token})


def _verify(check):
    return reverse('reference_checks:verify', kwargs={'token': check.token})


def _step(check, step_key):
    return reverse('reference_checks:step',
                   kwargs={'token': check.token, 'step_key': step_key})


def _verified(client, check):
    client.post(_verify(check), {'code': _otp_from_outbox()})
    return client


# ── The forms, exactly as the FINAL PDFs print them ──────────────────────
YES_NO = ['Yes', 'No']
RATING6 = ['Excellent', 'Very Good', 'Good', 'Satisfactory', 'Needs Improvement',
           'Unable to Comment']

EMPLOYER_PDF = [
    (1, 'Candidate Full Name', 'text', True, None),
    (2, 'Organisation / Employer Name', 'text', True, None),
    (3, 'SSL Wireless Verification Reference ID', 'text', True, None),
    (4, 'Your Full Name', 'text', True, None),
    (5, 'Your Designation / Position', 'text', True, None),
    (6, 'Department / Function', 'text', False, None),
    (7, 'Official Work Email Address', 'email', True, None),
    (8, 'Official Contact Number', 'phone', True, None),
    (9, 'Are you authorised to provide employment verification information on behalf '
        'of this organisation?', 'radio', True, YES_NO),
    (10, 'Can you confirm that the candidate was / is employed by your organisation?',
     'radio', True, ['Yes', 'No', 'Unable to Verify']),
    (11, 'Confirmed Employment Type', 'radio', True,
     ['Full-time / Permanent', 'Contractual', 'Project-based', 'Consultant',
      'Internship / Trainee', 'Other', 'Not Disclosed']),
    (12, 'Confirmed Most Recent / Final Position or Designation', 'text', True, None),
    (13, 'Confirmed Department / Business Unit (if available)', 'text', False, None),
    (14, 'Confirmed Employment Start Date', 'date', True, None),
    (15, 'Is the candidate currently employed by your organisation?', 'radio', True,
     YES_NO),
    (16, 'Confirmed Employment End Date', 'date', True, None),
    (17, 'Confirmed Reason for Leaving / Separation', 'textarea', False, None),
    (18, 'Nature of Separation', 'radio', False,
     ['Currently Employed', 'Voluntary Resignation', 'Contract Completion',
      'Redundancy / Retrenchment', 'Asked to Resign', 'Termination / Dismissal', 'Other',
      'Not Disclosed']),
    (19, 'Is the candidate eligible for rehire / re-employment?', 'radio', False,
     ['Yes', 'No', 'Conditional / With Reservations', 'Not Disclosed', 'Not Applicable']),
    (20, 'Any additional factual employment information or correction you would like '
         'SSL Wireless to note?', 'textarea', False, None),
    (21, 'To your direct knowledge, is there any formal or substantiated performance, '
         'disciplinary, integrity or conduct concern recorded by the organisation that is '
         'relevant to employment verification?', 'radio', True,
     ['No', 'Yes', 'Not Disclosed / Unable to Comment']),
    (22, 'If Yes, please provide factual details that you are authorised to disclose.',
     'textarea', True, None),
    (23, 'May SSL Wireless HR or its authorised background verification representative '
         'contact you if clarification is required?', 'radio', True, YES_NO),
    (24, 'Declaration', 'boolean', True, ['Confirmed', 'Not confirmed']),
]

PROFESSIONAL_PDF = [
    (1, 'Candidate Full Name', 'text', True, None),
    (2, 'Position Applied For at SSL Wireless', 'text', False, None),
    (3, 'SSL Wireless Verification Reference ID', 'text', True, None),
    (4, 'Your Full Name', 'text', True, None),
    (5, 'Your Designation / Position', 'text', True, None),
    (6, 'Your Organisation / Company / Institution', 'text', True, None),
    (7, 'Official Work Email Address', 'email', True, None),
    (8, 'Contact Number', 'phone', True, None),
    (9, 'Your professional relationship with the candidate', 'radio', True,
     ['Direct Manager', 'Skip-level Manager', 'Peer / Colleague', 'Direct Report',
      'HR Representative', 'Client / Business Stakeholder',
      'Academic Supervisor / Faculty', 'Other']),
    (10, 'Approximately how long have you known or worked with the candidate?', 'text',
     True, None),
    (11, 'In what organisation, team, project or professional context did you work with '
         'the candidate?', 'textarea', True, None),
    (12, "Please briefly describe the candidate's role and key responsibilities as you "
         'directly observed them.', 'textarea', True, None),
    (13, 'How closely did you work with the candidate?', 'radio', True,
     ['Daily / Very Closely', 'Frequently', 'Occasionally', 'Limited Interaction',
      'Other']),
    (14, "What would you consider the candidate's key professional strengths?",
     'textarea', True, None),
    (15, "How would you rate the candidate's reliability, ownership and ability to "
         'deliver commitments?', 'radio', True, RATING6),
    (16, "How would you rate the candidate's communication and teamwork?", 'radio', True,
     RATING6),
    (17, "How would you rate the candidate's ability to work with managers, colleagues, "
         'clients or other stakeholders?', 'radio', True, RATING6),
    (18, 'How did the candidate respond to feedback, pressure, setbacks or changing '
         'priorities?', 'textarea', True, None),
    (19, "If applicable, how would you describe the candidate's leadership / "
         'people-management capability?', 'radio', False,
     ['Excellent', 'Very Good', 'Good', 'Satisfactory', 'Needs Improvement',
      'Not Applicable / Unable to Comment']),
    (20, 'What areas, if any, would you recommend the candidate develop further?',
     'textarea', False, None),
    (21, 'To your direct knowledge, is there any material performance, disciplinary, '
         "integrity or conduct concern relevant to the candidate's professional "
         'suitability?', 'radio', True,
     ['No', 'Yes', 'Not Disclosed / Unable to Comment']),
    (22, 'If Yes, please provide factual details that you are authorised to disclose.',
     'textarea', True, None),
    (23, 'Would you work with, rehire or professionally recommend the candidate again?',
     'radio', True, ['Yes', 'No', 'Conditional / With Reservations',
                     'Not Applicable / Unable to Comment']),
    (24, 'Please explain your overall recommendation or any reservations.', 'textarea',
     True, None),
    (25, 'May SSL Wireless HR or its authorised background verification representative '
         'contact you if clarification is required?', 'radio', True, YES_NO),
    (26, 'Declaration', 'boolean', True, ['Confirmed', 'Not confirmed']),
]


def _numbered(kind):
    return [q for step in schema.steps(kind) for q in step['questions'] if 'no' in q]


@pytest.mark.parametrize('kind,expected', [
    (schema.EMPLOYER, EMPLOYER_PDF), (schema.PROFESSIONAL, PROFESSIONAL_PDF)])
def test_every_pdf_question_is_present_exactly(kind, expected):
    actual = [
        (q['no'], q['label'], q['type'], q['required'],
         [label for _, label in q['choices']] if 'choices' in q else None)
        for q in _numbered(kind)
    ]
    assert actual == expected


@pytest.mark.parametrize('kind,sections', [
    (schema.EMPLOYER, [
        ('Section A', 'Candidate & Verification Reference', [1, 2, 3]),
        ('Section B', 'Respondent / Authorised Representative Details', range(4, 10)),
        ('Section C', 'Employment Verification', range(10, 21)),
        ('Section D', 'Conduct / Integrity Information', [21, 22]),
        ('Section E', 'Verification Confirmation', [23, 24]),
    ]),
    (schema.PROFESSIONAL, [
        ('Section A', 'Candidate & Reference Details', range(1, 11)),
        ('Section B', 'Working Relationship & Role Context', [11, 12, 13]),
        ('Section C', 'Professional Performance & Behaviour', range(14, 21)),
        ('Section D', 'Conduct, Integrity & Recommendation', range(21, 25)),
        ('Section E', 'Confirmation', [25, 26]),
    ]),
])
def test_sections_follow_the_pdf(kind, sections):
    steps = schema.steps(kind)
    assert len(steps) == len(sections)
    for step, (section, title, numbers) in zip(steps, sections):
        assert step['section'] == section
        assert step['title'] == title
        assert [q['no'] for q in step['questions'] if 'no' in q] == list(numbers)


def test_section_notes_are_verbatim():
    employer = {s['key']: s['description'] for s in schema.steps(schema.EMPLOYER)}
    assert employer['employment'] == (
        'Please answer from official organisational records. SSL Wireless will compare '
        'the information internally; you do not need to assess whether it matches '
        'information provided by the candidate.')
    assert employer['conduct'] == (
        'Please provide only substantiated information that your organisation is '
        'authorised to disclose. Do not include rumours, speculation or unverified '
        'allegations.')
    professional = {s['key']: s['description'] for s in schema.steps(schema.PROFESSIONAL)}
    assert professional['conduct'] == (
        'Please provide only substantiated information based on your direct knowledge. '
        'Do not include rumours, speculation or information you are not authorised to '
        'disclose.')


def test_headers_intros_and_declarations_are_verbatim():
    assert schema.HEADERS[schema.EMPLOYER] == (
        'CONFIDENTIAL — For employment background verification purposes only')
    assert schema.HEADERS[schema.PROFESSIONAL] == (
        'CONFIDENTIAL — For recruitment background verification purposes only')
    assert schema.INTROS[schema.EMPLOYER].startswith(
        'SSL Wireless is conducting an employment background verification')
    assert schema.INTROS[schema.EMPLOYER].endswith(
        'only information you are authorised to disclose.')
    assert schema.INTROS[schema.PROFESSIONAL].startswith(
        'SSL Wireless is conducting a professional reference check')
    assert schema.INTROS[schema.PROFESSIONAL].endswith(
        'factual information that you are authorised to disclose.')
    employer = schema.questions_by_key(schema.EMPLOYER)['declaration']['statement']
    assert employer.startswith('I confirm that the information provided above')
    assert 'is based on information I am authorised to disclose' in employer
    professional = schema.questions_by_key(schema.PROFESSIONAL)['declaration']['statement']
    assert 'is based on my direct professional knowledge of the candidate' in professional
    for text in (employer, professional):
        assert text.endswith('By submitting this form, I provide my confirmation.')


OTHER_COMPANIONS = [
    (schema.EMPLOYER, 'employment_type', 'employment_type_other'),
    (schema.EMPLOYER, 'separation_nature', 'separation_nature_other'),
    (schema.PROFESSIONAL, 'referee_relationship', 'referee_relationship_other'),
    (schema.PROFESSIONAL, 'working_closeness', 'working_closeness_other'),
]


@pytest.mark.parametrize('kind,choice_key,other_key', OTHER_COMPANIONS)
def test_every_other_option_has_a_free_text_companion(kind, choice_key, other_key):
    by_key = schema.questions_by_key(kind)
    other = by_key[other_key]
    assert 'other' in dict(by_key[choice_key]['choices'])
    assert other['type'] == schema.TEXT
    assert other['required'] is True
    assert other['show_if'] == {'q': choice_key, 'in': ['other']}
    keys = list(by_key)
    assert keys.index(other_key) == keys.index(choice_key) + 1


def test_the_conditional_rules_are_the_pdfs():
    employer = schema.questions_by_key(schema.EMPLOYER)
    assert employer['employment_end_date']['show_if'] == {
        'q': 'currently_employed', 'in': ['no']}
    assert employer['employment_end_date']['required'] is True
    assert 'show_if' not in employer['separation_reason']
    assert employer['separation_reason']['required_if'] == {
        'q': 'currently_employed', 'in': ['no']}
    assert 'show_if' not in employer['separation_nature']
    assert employer['separation_nature']['required_if'] == {
        'q': 'currently_employed', 'in': ['no']}
    assert employer['conduct_details']['show_if'] == {'q': 'conduct_concerns', 'in': ['yes']}
    professional = schema.questions_by_key(schema.PROFESSIONAL)
    assert professional['conduct_details']['show_if'] == {
        'q': 'conduct_concerns', 'in': ['yes']}
    assert professional['recommend_explanation']['required'] is True
    assert 'show_if' not in professional['recommend_explanation']


def test_the_section_a_facts_are_read_only():
    assert schema.readonly_keys(schema.EMPLOYER) == {
        'candidate_full_name', 'verifier_organisation', 'verification_reference_id'}
    assert schema.readonly_keys(schema.PROFESSIONAL) == {
        'candidate_full_name', 'position_applied_for', 'verification_reference_id'}


REMOVED_KEYS = [
    'last_salary', 'had_promotion', 'promotion_details', 'subordinates',
    'employment_period', 'employment_status', 'rehire_explanation',
    'verifier_relationship', 'disciplinary_action', 'disciplinary_details',
    'integrity_concerns', 'integrity_details', 'rating_overall', 'rating_quality',
    'rating_attendance', 'rating_professionalism', 'recommend', 'anything_else',
    'managed_others', 'managed_scope', 'candidate_role', 'worked_together_when',
    'hire_again_explanation', 'rating_teamwork', 'rating_communication',
]


@pytest.mark.parametrize('kind', [schema.EMPLOYER, schema.PROFESSIONAL])
def test_nothing_outside_the_pdf_is_asked(kind):
    by_key = schema.questions_by_key(kind)
    assert not set(REMOVED_KEYS) & set(by_key)
    unnumbered = [k for k, q in by_key.items() if 'no' not in q]
    assert sorted(unnumbered) == sorted(
        other for form, _, other in OTHER_COMPANIONS if form == kind)


@pytest.mark.parametrize('kind', [schema.EMPLOYER, schema.PROFESSIONAL])
def test_salary_is_never_asked(kind):
    for q in schema.questions_by_key(kind).values():
        text = f"{q['key']} {q['label']} {q['help']}".lower()
        assert 'salary' not in text and 'compensation' not in text, q['key']


def test_no_section_is_named_after_a_reserved_url_segment():
    reserved = {'verify', 'done', 'resend-code', 'resend_code'}
    for kind in (schema.EMPLOYER, schema.PROFESSIONAL, schema.ACADEMIC):
        assert not reserved.intersection(schema.step_keys(kind))


@pytest.mark.parametrize('kind', [schema.EMPLOYER, schema.PROFESSIONAL, schema.ACADEMIC])
def test_sections_chain_and_keys_are_unique(kind):
    keys = schema.step_keys(kind)
    for index, key in enumerate(keys):
        expected = keys[index + 1] if index + 1 < len(keys) else None
        assert schema.get_step(kind, key)['next'] == expected
    question_keys = [q['key'] for step in schema.steps(kind) for q in step['questions']]
    assert len(question_keys) == len(set(question_keys))


# ── Who can be asked ─────────────────────────────────────────────────────
def test_contacts_come_from_the_declared_employers_and_references(candidate):
    rows = {r['source_key']: r for r in services.candidate_contacts(candidate)}
    assert set(rows) == {'employer_1', 'employer_2', 'reference_1', 'reference_2'}
    assert rows['employer_1']['recipient_email'] == 'hr@acme.com'
    assert rows['employer_1']['recipient_name'] == 'Acme Ltd — HR'
    assert rows['employer_1']['recipient_phone'] == '+8801711000000'
    assert rows['employer_1']['permitted'] is True
    assert rows['reference_1']['recipient_organisation'] == 'CTO, Acme Ltd'


def test_an_employer_past_the_candidates_last_another_is_not_offered(candidate):
    form = candidate.employee_form
    form.answers = {**form.answers, 'employer_3_name': 'Stale Co',
                    'employer_3_hr_email': 'x@stale.com',
                    'employer_3_contact_permission': 'yes'}
    form.save()
    keys = {r['source_key'] for r in services.candidate_contacts(candidate)}
    assert 'employer_3' not in keys


def test_legacy_answers_without_the_employment_gate_still_list_employers(candidate):
    form = candidate.employee_form
    form.answers = {k: v for k, v in form.answers.items()
                    if k not in ('has_employment', 'employer_1_another')}
    form.save()
    keys = {r['source_key'] for r in services.candidate_contacts(candidate)}
    assert {'employer_1', 'employer_2'} <= keys


def test_a_freshers_referees_get_the_professional_form(fresher):
    assert services.is_fresher(fresher) is True
    assert services.contact_for(fresher, 'reference_1')['default_kind'] == \
        schema.PROFESSIONAL


def test_the_academic_form_can_no_longer_be_sent(hr_client, fresher):
    _send(hr_client, fresher, 'reference_1', kind=schema.ACADEMIC)
    assert not ReferenceCheck.objects.exists()
    assert len(mail.outbox) == 0
    with pytest.raises(services.SendError):
        services.issue_request(fresher, 'reference_1', kind=schema.ACADEMIC,
                               recipient_name='Prof', recipient_email='p@u.edu')


def test_hr_is_only_offered_the_final_forms(hr_client, candidate):
    body = hr_client.get(_manage_url(candidate)).content.decode()
    assert 'value="academic"' not in body
    assert 'value="employer"' in body and 'value="professional"' in body


# ── Consent ──────────────────────────────────────────────────────────────
def test_a_refused_contact_cannot_be_sent(hr_client, candidate):
    _send(hr_client, candidate, 'employer_2')
    assert not ReferenceCheck.objects.filter(source_key='employer_2').exists()
    assert len(mail.outbox) == 0


def test_a_blanket_refusal_beats_a_yes_further_down_the_form(hr_client, candidate):
    form = candidate.employee_form
    form.answers = {**form.answers, 'verification_consent': 'no'}
    form.save()
    _send(hr_client, candidate, 'employer_1')
    assert not ReferenceCheck.objects.filter(source_key='employer_1').exists()
    body = hr_client.get(_manage_url(candidate)).content.decode()
    assert 'did not consent to background verification' in body


def test_a_missing_consent_answer_is_not_read_as_a_refusal(candidate):
    form = candidate.employee_form
    form.answers = {k: v for k, v in form.answers.items() if k != 'verification_consent'}
    form.save()
    assert services.verification_refused(candidate) is False


def test_a_blank_permission_is_not_consent(hr_client, candidate):
    form = candidate.employee_form
    form.answers = {**form.answers, 'employer_1_contact_permission': ''}
    form.save()
    _send(hr_client, candidate, 'employer_1')
    assert not ReferenceCheck.objects.filter(source_key='employer_1').exists()


def test_the_refused_row_says_why(hr_client, candidate):
    assert 'Candidate did not permit contact' in \
        hr_client.get(_manage_url(candidate)).content.decode()


# ── Sending ──────────────────────────────────────────────────────────────
def test_sending_emails_a_link_a_code_and_the_reference_id(hr_client, candidate):
    _send(hr_client, candidate, 'employer_1')

    check = ReferenceCheck.objects.get(source_key='employer_1')
    assert check.kind == schema.EMPLOYER
    email = mail.outbox[0]
    assert email.to == ['hr@acme.com']
    assert str(check.token) in email.body
    assert re.search(r'code is:\s*\d{6}', email.body)
    assert check.verification_reference_id in email.body
    assert check.verification_reference_id in email.alternatives[0][0]
    assert 'Ayesha Siddiqua Rahman' in email.body


def test_the_reference_id_is_stable_readable_and_not_the_token(candidate):
    check = ReferenceCheck.objects.create(
        resume=candidate, kind=schema.EMPLOYER, source_key='employer_1',
        recipient_name='Acme HR', recipient_email='hr@acme.com')
    assert check.verification_reference_id == f'SSLW-VR-{check.pk:06d}'
    assert str(check.token) not in check.verification_reference_id
    assert ReferenceCheck.objects.get(pk=check.pk).verification_reference_id == \
        check.verification_reference_id


def test_hr_sees_the_reference_id_on_the_manage_page(hr_client, candidate):
    _send(hr_client, candidate, 'employer_1')
    check = ReferenceCheck.objects.get(source_key='employer_1')
    assert check.verification_reference_id in \
        hr_client.get(_manage_url(candidate)).content.decode()


def test_the_code_is_never_stored_in_plaintext(hr_client, candidate):
    _send(hr_client, candidate, 'employer_1')
    check = ReferenceCheck.objects.get(source_key='employer_1')
    otp = _otp_from_outbox()
    assert otp not in check.otp_hash
    assert check.check_otp(otp) is True


def test_hr_can_correct_a_stale_address(hr_client, candidate):
    _send(hr_client, candidate, 'employer_1', recipient_email='newhr@acme.com')
    assert ReferenceCheck.objects.get(source_key='employer_1').recipient_email == \
        'newhr@acme.com'
    assert mail.outbox[0].to == ['newhr@acme.com']


def test_sending_twice_resends_to_the_same_row(hr_client, candidate):
    _send(hr_client, candidate, 'employer_1')
    first = _otp_from_outbox()
    _send(hr_client, candidate, 'employer_1')
    check = ReferenceCheck.objects.get(source_key='employer_1')
    assert check.invite_count == 2
    assert check.check_otp(first) is False


def test_nothing_is_sent_before_interviewing(hr_client, candidate):
    candidate.recruiter_status = 'shortlisted'
    candidate.save()
    _send(hr_client, candidate, 'employer_1')
    assert not ReferenceCheck.objects.exists()


def test_a_completed_check_is_not_resent(hr_client, candidate):
    _send(hr_client, candidate, 'employer_1')
    ReferenceCheck.objects.filter(source_key='employer_1').update(is_submitted=True)
    mail.outbox.clear()
    _send(hr_client, candidate, 'employer_1')
    assert len(mail.outbox) == 0


# ── HR access ────────────────────────────────────────────────────────────
def test_an_ordinary_recruiter_cannot_manage_checks(authenticated_client, candidate):
    response = authenticated_client.get(_manage_url(candidate))
    assert response.status_code == 302
    assert reverse('core:dashboard') in response.url


def test_an_ordinary_recruiter_does_not_see_the_card(authenticated_client, candidate):
    url = reverse('core:resume_detail', kwargs={'uuid': candidate.uuid})
    assert 'Reference &amp; Employment Checks' not in \
        authenticated_client.get(url).content.decode()


def test_hr_sees_the_card(hr_client, candidate):
    url = reverse('core:resume_detail', kwargs={'uuid': candidate.uuid})
    assert 'Reference &amp; Employment Checks' in hr_client.get(url).content.decode()


# ── The respondent's side ────────────────────────────────────────────────
@pytest.fixture
def sent_check(hr_client, candidate):
    _send(hr_client, candidate, 'employer_1')
    return ReferenceCheck.objects.get(source_key='employer_1')


@pytest.fixture
def referee_check(hr_client, candidate):
    _send(hr_client, candidate, 'reference_1')
    return ReferenceCheck.objects.get(source_key='reference_1')


def test_the_link_alone_never_reveals_who_applied(client, sent_check):
    names = ['Ayesha', 'Rahman', 'Siddiqua']
    pages = [client.get(_verify(sent_check), follow=True)]
    ReferenceCheck.objects.filter(pk=sent_check.pk).update(
        is_submitted=True, submitted_at=timezone.now())
    pages.append(client.get(_entry(sent_check), follow=True))
    pages.append(client.get(reverse('reference_checks:done',
                                    kwargs={'token': sent_check.token}), follow=True))
    ReferenceCheck.objects.filter(pk=sent_check.pk).update(
        is_submitted=False, token_expires_at=timezone.now() - timedelta(days=1))
    pages.append(client.get(_entry(sent_check), follow=True))
    for page in pages:
        body = page.content.decode()
        for name in names:
            assert name not in body, f'{page.request["PATH_INFO"]} leaks {name}'


def test_the_link_alone_does_not_open_the_form(client, sent_check):
    response = client.get(_step(sent_check, 'candidate'))
    assert response.status_code == 302
    assert 'verify' in response.url


def test_the_right_code_opens_section_a(client, sent_check):
    response = client.post(_verify(sent_check), {'code': _otp_from_outbox()})
    assert response.url == _step(sent_check, 'candidate')


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


@pytest.mark.parametrize('fixture,kind', [('sent_check', schema.EMPLOYER),
                                          ('referee_check', schema.PROFESSIONAL)])
def test_every_page_carries_the_pdf_header_and_intro(client, request, fixture, kind):
    check = request.getfixturevalue(fixture)
    _verified(client, check)
    check.current_step = schema.final_step(kind)
    check.save(update_fields=['current_step'])
    for step_key in schema.step_keys(kind):
        body = client.get(_step(check, step_key)).content.decode()
        assert schema.HEADERS[kind] in body, step_key
        assert schema.INTROS[kind].replace("'", '&#x27;') in body, step_key
        assert 'form-logic-rules' in body
        assert 'data-logic-group' in body


def test_section_a_shows_the_fixed_facts_read_only(client, sent_check):
    _verified(client, sent_check)
    page = client.get(_step(sent_check, 'candidate')).content.decode()
    for key, value in (('candidate_full_name', 'Ayesha Siddiqua Rahman'),
                       ('verifier_organisation', 'Acme Ltd'),
                       ('verification_reference_id',
                        sent_check.verification_reference_id)):
        markup = re.search(rf'<input[^>]*name="{key}"[^>]*>', page).group(0)
        assert 'readonly' in markup, key
        assert f'value="{value}"' in markup, key
    assert 'Nadia Haque' not in page


def test_a_tampered_read_only_value_is_ignored(client, sent_check):
    _verified(client, sent_check)
    client.post(_step(sent_check, 'candidate'), {
        'candidate_full_name': 'Someone Else',
        'verifier_organisation': 'Fake Corp',
        'verification_reference_id': 'SSLW-VR-999999',
    })
    sent_check.refresh_from_db()
    assert sent_check.current_step == 'respondent'
    assert sent_check.answers['candidate_full_name'] == 'Ayesha Siddiqua Rahman'
    assert sent_check.answers['verifier_organisation'] == 'Acme Ltd'
    assert sent_check.answers['verification_reference_id'] == \
        sent_check.verification_reference_id


def test_the_professional_section_a_fixes_the_position(client, referee_check):
    _verified(client, referee_check)
    client.post(_step(referee_check, 'candidate'), {
        **REFEREE, 'position_applied_for': 'CEO'})
    referee_check.refresh_from_db()
    assert referee_check.answers['position_applied_for'] == 'Senior Python Developer'
    assert referee_check.current_step == 'relationship'


def test_candidate_name_falls_back_to_the_cv(candidate):
    assert services.candidate_name(candidate) == 'Ayesha Siddiqua Rahman'
    form = candidate.employee_form
    form.answers = {**form.answers, 'candidate_full_name': ''}
    form.save()
    assert services.candidate_name(candidate) == 'Ayesha Rahman'


# ── Prefill ──────────────────────────────────────────────────────────────
def test_every_prefilled_and_fixed_key_is_a_real_question():
    for mapping in (services.SELF_DETAILS, services.FIXED_DETAILS):
        for kind, keys in mapping.items():
            real = schema.questions_by_key(kind)
            for question_key in keys.values():
                assert question_key in real, f'{kind} has no question {question_key!r}'


def test_employer_prefill_keys(sent_check):
    prefill = services.prefill_answers(sent_check)
    assert prefill == {'verifier_email': 'hr@acme.com',
                       'verifier_contact': '+8801711000000'}
    assert services.fixed_answers(sent_check) == {
        'candidate_full_name': 'Ayesha Siddiqua Rahman',
        'verifier_organisation': 'Acme Ltd',
        'verification_reference_id': sent_check.verification_reference_id,
    }


def test_a_named_employer_contact_is_prefilled(hr_client, candidate):
    _send(hr_client, candidate, 'employer_1', recipient_name='Rehana Karim')
    check = ReferenceCheck.objects.get(source_key='employer_1')
    assert services.prefill_answers(check)['verifier_name'] == 'Rehana Karim'


def test_referee_prefill_keys(referee_check):
    assert services.prefill_answers(referee_check) == {
        'referee_name': 'Karim Uddin',
        'referee_email': 'karim@acme.com',
        'referee_designation': 'CTO',
        'referee_organisation': 'Acme Ltd',
        'referee_contact': '+8801811000000',
        'referee_relationship': 'direct_manager',
    }
    assert services.fixed_answers(referee_check) == {
        'candidate_full_name': 'Ayesha Siddiqua Rahman',
        'position_applied_for': 'Senior Python Developer',
        'verification_reference_id': referee_check.verification_reference_id,
    }


@pytest.mark.parametrize('text,expected', [
    ('CTO, Acme Ltd', ('CTO', 'Acme Ltd')),
    ('Head of HR at Globex', ('Head of HR', 'Globex')),
    ('Lecturer - Dhaka University', ('Lecturer', 'Dhaka University')),
    ('Head of HR, Operations, Acme', ('Head of HR, Operations', 'Acme')),
    ('Chief Technology Officer', ('Chief Technology Officer', '')),
    ('', ('', '')),
])
def test_the_combined_designation_is_split_only_when_clear(text, expected):
    assert services.split_designation(text) == expected


def test_an_unsplittable_designation_is_not_duplicated(hr_client, candidate):
    _send(hr_client, candidate, 'reference_2')
    check = ReferenceCheck.objects.get(source_key='reference_2')
    prefill = services.prefill_answers(check)
    assert prefill['referee_designation'] == 'Professor'
    assert 'referee_organisation' not in prefill
    assert prefill['referee_relationship'] == 'academic'


@pytest.mark.parametrize('declared,expected', [
    ('direct_manager', 'direct_manager'), ('skip_level_manager', 'skip_level_manager'),
    ('peer', 'peer'), ('direct_report', 'direct_report'), ('hr', 'hr'),
    ('academic', 'academic'), ('other', None), ('hr_other', None),
])
def test_relationship_prefill_follows_the_eif_contract(hr_client, candidate, declared,
                                                       expected):
    form = candidate.employee_form
    form.answers = {**form.answers, 'reference_1_relationship': declared}
    form.save()
    _send(hr_client, candidate, 'reference_1')
    check = ReferenceCheck.objects.get(source_key='reference_1')
    assert services.prefill_answers(check).get('referee_relationship') == expected


def test_prefilled_relationship_values_exist_on_both_forms():
    offered_to_candidate = {v for v, _ in employee_schema.RELATIONSHIP_CHOICES}
    offered_to_referee = set(dict(schema.REFEREE_RELATIONSHIP_CHOICES))
    for theirs, ours in services.RELATIONSHIP_EQUIVALENTS.items():
        assert theirs in offered_to_candidate
        assert ours in offered_to_referee


def test_prefilled_respondent_details_are_editable(client, referee_check):
    _verified(client, referee_check)
    page = client.get(_step(referee_check, 'candidate')).content.decode()
    assert 'filled in your details' in page
    for field, value in (('referee_name', 'Karim Uddin'), ('referee_designation', 'CTO'),
                         ('referee_organisation', 'Acme Ltd'),
                         ('referee_email', 'karim@acme.com')):
        markup = re.search(rf'<input[^>]*name="{field}"[^>]*>', page).group(0)
        assert f'value="{value}"' in markup
        assert 'readonly' not in markup and 'disabled' not in markup


def test_a_correction_survives_the_prefill(client, referee_check):
    _verified(client, referee_check)
    client.post(_step(referee_check, 'candidate'), {
        **REFEREE, 'referee_designation': 'Chief Technology Officer'})
    referee_check.refresh_from_db()
    assert referee_check.answers['referee_designation'] == 'Chief Technology Officer'
    page = client.get(_step(referee_check, 'candidate')).content.decode()
    assert 'value="Chief Technology Officer"' in page


# ── Filling in the employer form ─────────────────────────────────────────
RESPONDENT = {
    'verifier_name': 'Rehana Karim',
    'verifier_designation': 'Head of HR',
    'verifier_email': 'rehana@acme.com',
    'verifier_contact': '+8801711000001',
    'verifier_authorised': 'yes',
}
EMPLOYMENT = {
    'was_employed': 'yes',
    'employment_type': 'full_time',
    'last_designation': 'Senior Engineer',
    'employment_start_date': '2020-01-05',
    'currently_employed': 'no',
    'employment_end_date': '2024-03-31',
    'separation_reason': 'Moved abroad',
    'separation_nature': 'voluntary_resignation',
}


def _through(client, check, *pages):
    for step_key, data in pages:
        client.post(_step(check, step_key), data)
    check.refresh_from_db()
    return check


def _to_employment(client, check):
    _verified(client, check)
    return _through(client, check, ('candidate', {}), ('respondent', RESPONDENT))


def test_sections_save_and_advance(client, sent_check):
    check = _to_employment(client, sent_check)
    assert check.current_step == 'employment'
    assert check.answers['verifier_name'] == 'Rehana Karim'


@pytest.mark.parametrize('missing', sorted(RESPONDENT))
def test_every_required_respondent_field_is_enforced(client, sent_check, missing):
    _verified(client, sent_check)
    check = _through(client, sent_check, ('candidate', {}),
                     ('respondent', {k: v for k, v in RESPONDENT.items() if k != missing}))
    assert check.current_step == 'respondent'


def test_department_is_optional(client, sent_check):
    assert 'verifier_department' not in RESPONDENT
    assert _to_employment(client, sent_check).current_step == 'employment'


def test_a_respondent_cannot_skip_ahead(client, sent_check):
    _verified(client, sent_check)
    response = client.get(_step(sent_check, 'confirmation'))
    assert response.url == _step(sent_check, 'candidate')


def test_the_end_date_is_hidden_and_cleared_while_still_employed(client, sent_check):
    check = _to_employment(client, sent_check)
    check = _through(client, check, ('employment', {
        **EMPLOYMENT, 'currently_employed': 'yes', 'employment_end_date': '2024-03-31',
        'separation_nature': ''}))
    assert check.current_step == 'conduct'
    assert check.answers['employment_end_date'] == ''
    assert check.answers['separation_nature'] == ''


def test_the_end_date_is_required_once_they_have_left(client, sent_check):
    check = _to_employment(client, sent_check)
    check = _through(client, check, ('employment', {
        k: v for k, v in EMPLOYMENT.items() if k != 'employment_end_date'}))
    assert check.current_step == 'employment'


def test_nature_of_separation_is_required_once_they_have_left(client, sent_check):
    check = _to_employment(client, sent_check)
    check = _through(client, check, ('employment', {
        k: v for k, v in EMPLOYMENT.items() if k != 'separation_nature'}))
    assert check.current_step == 'employment'


def test_the_reason_for_leaving_is_required_once_they_have_left(client, sent_check):
    check = _through(client, _to_employment(client, sent_check), ('employment', {
        k: v for k, v in EMPLOYMENT.items() if k != 'separation_reason'}))
    assert check.current_step == 'employment'


def test_a_current_employee_needs_no_end_date_reason_or_separation(client, sent_check):
    check = _through(client, _to_employment(client, sent_check), ('employment', {
        k: v for k, v in EMPLOYMENT.items()
        if k not in ('employment_end_date', 'separation_reason', 'separation_nature')
    } | {'currently_employed': 'yes'}))
    assert check.current_step == 'conduct'


def test_an_end_before_the_start_is_rejected(client, sent_check):
    check = _through(client, _to_employment(client, sent_check), ('employment', {
        **EMPLOYMENT, 'employment_end_date': '2019-01-01'}))
    assert check.current_step == 'employment'


def test_a_future_start_date_is_rejected(client, sent_check):
    future = (date.today() + timedelta(days=30)).isoformat()
    check = _through(client, _to_employment(client, sent_check), ('employment', {
        **EMPLOYMENT, 'employment_start_date': future, 'currently_employed': 'yes'}))
    assert check.current_step == 'employment'


@pytest.mark.parametrize('choice_key,other_key', [
    ('employment_type', 'employment_type_other'),
    ('separation_nature', 'separation_nature_other'),
])
def test_other_needs_its_free_text(client, sent_check, choice_key, other_key):
    check = _to_employment(client, sent_check)
    check = _through(client, check, ('employment', {**EMPLOYMENT, choice_key: 'other'}))
    assert check.current_step == 'employment'
    check = _through(client, check, ('employment', {
        **EMPLOYMENT, choice_key: 'other', other_key: 'Secondment'}))
    assert check.current_step == 'conduct'
    assert check.answers[other_key] == 'Secondment'


def test_other_text_is_cleared_when_other_is_not_chosen(client, sent_check):
    check = _through(client, _to_employment(client, sent_check), ('employment', {
        **EMPLOYMENT, 'employment_type_other': 'stray'}))
    assert check.answers['employment_type_other'] == ''


def test_a_concern_needs_its_details(client, sent_check):
    check = _through(client, _to_employment(client, sent_check),
                     ('employment', EMPLOYMENT), ('conduct', {'conduct_concerns': 'yes'}))
    assert check.current_step == 'conduct'
    check = _through(client, check, ('conduct', {
        'conduct_concerns': 'yes', 'conduct_details': 'Formal warning, 2023'}))
    assert check.current_step == 'confirmation'


def test_no_concern_needs_no_details_and_clears_them(client, sent_check):
    check = _through(client, _to_employment(client, sent_check),
                     ('employment', EMPLOYMENT),
                     ('conduct', {'conduct_concerns': 'no', 'conduct_details': 'x'}))
    assert check.current_step == 'confirmation'
    assert check.answers['conduct_details'] == ''


def _to_confirmation(client, check):
    return _through(client, _to_employment(client, check), ('employment', EMPLOYMENT),
                    ('conduct', {'conduct_concerns': 'unable'}))


def test_the_declaration_must_be_ticked(client, sent_check):
    check = _to_confirmation(client, sent_check)
    check = _through(client, check, ('confirmation', {'clarification_contact': 'yes'}))
    assert not check.is_submitted


def test_the_clarification_question_is_required(client, sent_check):
    check = _to_confirmation(client, sent_check)
    check = _through(client, check, ('confirmation', {'declaration': 'on'}))
    assert not check.is_submitted


def test_a_ticked_declaration_completes_the_request(client, sent_check):
    check = _to_confirmation(client, sent_check)
    response = client.post(_step(check, 'confirmation'),
                           {'clarification_contact': 'no', 'declaration': 'on'})
    check.refresh_from_db()
    assert check.is_submitted and check.submitted_at
    assert check.answers['declaration'] == 'yes'
    assert response.url == reverse('reference_checks:done', kwargs={'token': check.token})


def test_the_declaration_text_is_shown_beside_the_tick_box(client, sent_check):
    check = _to_confirmation(client, sent_check)
    page = client.get(_step(check, 'confirmation')).content.decode()
    assert 'By submitting this form, I provide my confirmation.' in page
    assert re.search(r'<input type="checkbox" data-boolean[^>]*name="declaration"', page)


def test_the_last_section_cannot_complete_over_a_gap(client, sent_check):
    """An older row may sit on a later section with earlier ones unanswered."""
    _verified(client, sent_check)
    ReferenceCheck.objects.filter(pk=sent_check.pk).update(current_step='confirmation')
    client.post(_step(sent_check, 'confirmation'),
                {'clarification_contact': 'yes', 'declaration': 'on'})
    sent_check.refresh_from_db()
    assert not sent_check.is_submitted
    assert sent_check.current_step == 'respondent', 'Section A is fixed, B is the gap'


def test_a_completed_request_cannot_be_reopened(client, sent_check):
    _verified(client, sent_check)
    ReferenceCheck.objects.filter(pk=sent_check.pk).update(is_submitted=True)
    for url in (_entry(sent_check), _step(sent_check, 'candidate')):
        assert b'already have your response' in client.get(url).content


def test_an_expired_link_says_so(client, sent_check):
    ReferenceCheck.objects.filter(pk=sent_check.pk).update(
        token_expires_at=timezone.now() - timedelta(days=1))
    assert b'has expired' in client.get(_entry(sent_check)).content


def test_a_respondents_save_cannot_undo_a_code_hr_issued_meanwhile(
        client, sent_check, monkeypatch):
    from apps.reference_checks.forms import StepForm

    _verified(client, sent_check)
    original = StepForm.storable_answers

    def storable_while_hr_resends(self):
        hr_copy = ReferenceCheck.objects.get(pk=sent_check.pk)
        hr_copy.issue_otp()
        hr_copy.save(update_fields=[*ReferenceCheck.OTP_FIELDS, 'updated_at'])
        return original(self)

    monkeypatch.setattr(StepForm, 'storable_answers', storable_while_hr_resends)
    before = ReferenceCheck.objects.get(pk=sent_check.pk).otp_hash
    client.post(_step(sent_check, 'candidate'), {})
    after = ReferenceCheck.objects.get(pk=sent_check.pk)
    assert after.otp_hash != before
    assert after.current_step == 'respondent'


def test_a_resend_cannot_revert_answers_saved_while_it_was_running(
        sent_check, monkeypatch):
    from apps.reference_checks.tasks import send_reference_check_request

    original = ReferenceCheck.issue_otp

    def issue_otp_while_the_respondent_saves(self):
        ReferenceCheck.objects.filter(pk=self.pk).update(
            answers={'was_employed': 'yes'}, current_step='conduct')
        return original(self)

    monkeypatch.setattr(ReferenceCheck, 'issue_otp', issue_otp_while_the_respondent_saves)
    send_reference_check_request(sent_check.pk)
    fresh = ReferenceCheck.objects.get(pk=sent_check.pk)
    assert fresh.answers == {'was_employed': 'yes'}
    assert fresh.current_step == 'conduct'
    assert fresh.invited_at is not None


# ── Filling in the professional form ─────────────────────────────────────
REFEREE = {
    'referee_name': 'Karim Uddin',
    'referee_designation': 'CTO',
    'referee_organisation': 'Acme Ltd',
    'referee_email': 'karim@acme.com',
    'referee_contact': '+8801811000000',
    'referee_relationship': 'direct_manager',
    'known_duration': 'About three years',
}
RELATIONSHIP = {
    'work_context': 'Platform team at Acme',
    'main_responsibilities': 'Backend services',
    'working_closeness': 'daily',
}
PERFORMANCE = {
    'strongest_qualities': 'Thorough',
    'rating_reliability': 'excellent',
    'rating_communication_teamwork': 'very_good',
    'rating_stakeholders': 'unable',
    'response_to_pressure': 'Calmly',
}
CONDUCT = {
    'conduct_concerns': 'no',
    'hire_again': 'yes',
    'recommend_explanation': 'Would hire again',
}


def test_the_professional_form_completes_end_to_end(client, referee_check):
    _verified(client, referee_check)
    check = _through(client, referee_check, ('candidate', REFEREE),
                     ('relationship', RELATIONSHIP), ('performance', PERFORMANCE),
                     ('conduct', CONDUCT),
                     ('confirmation', {'clarification_contact': 'yes',
                                       'declaration': 'on'}))
    assert check.is_submitted
    assert check.answers['rating_leadership'] == ''
    assert check.answers['declaration'] == 'yes'


@pytest.mark.parametrize('step_key,data,missing', [
    *[('candidate', REFEREE, k) for k in sorted(REFEREE)],
    *[('relationship', RELATIONSHIP, k) for k in sorted(RELATIONSHIP)],
    *[('performance', PERFORMANCE, k) for k in sorted(PERFORMANCE)],
    *[('conduct', CONDUCT, k) for k in sorted(CONDUCT)],
])
def test_every_required_professional_answer_is_enforced(client, referee_check, step_key,
                                                        data, missing):
    _verified(client, referee_check)
    ReferenceCheck.objects.filter(pk=referee_check.pk).update(current_step=step_key)
    posted = {k: v for k, v in data.items() if k != missing}
    if step_key == 'candidate' and missing in services.prefill_answers(referee_check):
        posted[missing] = ''
    check = _through(client, referee_check, (step_key, posted))
    assert check.current_step == step_key


@pytest.mark.parametrize('choice_key,other_key,step_key,data', [
    ('referee_relationship', 'referee_relationship_other', 'candidate', REFEREE),
    ('working_closeness', 'working_closeness_other', 'relationship', RELATIONSHIP),
])
def test_professional_other_needs_its_free_text(client, referee_check, choice_key,
                                                other_key, step_key, data):
    _verified(client, referee_check)
    ReferenceCheck.objects.filter(pk=referee_check.pk).update(current_step=step_key)
    check = _through(client, referee_check, (step_key, {**data, choice_key: 'other'}))
    assert check.current_step == step_key
    check = _through(client, check, (step_key, {**data, choice_key: 'other',
                                                other_key: 'Mentor'}))
    assert check.current_step != step_key


def test_a_professional_concern_needs_its_details(client, referee_check):
    _verified(client, referee_check)
    ReferenceCheck.objects.filter(pk=referee_check.pk).update(current_step='conduct')
    check = _through(client, referee_check, ('conduct', {**CONDUCT,
                                                         'conduct_concerns': 'yes'}))
    assert check.current_step == 'conduct'
    check = _through(client, check, ('conduct', {**CONDUCT, 'conduct_concerns': 'yes',
                                                 'conduct_details': 'Documented'}))
    assert check.current_step == 'confirmation'


# ── Older data ───────────────────────────────────────────────────────────
OLD_EMPLOYER_ANSWERS = {
    'verifier_name': 'Old HR', 'verifier_organisation': 'Acme Ltd',
    'verifier_relationship': 'hr', 'was_employed': 'yes',
    'employment_period': '2020-2024', 'last_salary': '50000',
    'separation_nature': 'involuntary', 'rehire_eligible': 'no',
    'disciplinary_action': 'no', 'integrity_concerns': 'no', 'rating_overall': 'good',
}


def test_an_old_employer_reply_still_renders(hr_client, candidate):
    check = ReferenceCheck.objects.create(
        resume=candidate, kind=schema.EMPLOYER, source_key='employer_1',
        recipient_name='Acme HR', recipient_email='hr@acme.com', is_submitted=True,
        submitted_at=timezone.now(), current_step='conduct',
        answers=OLD_EMPLOYER_ANSWERS)
    body = hr_client.get(reverse('reference_checks:response', kwargs={
        'uuid': candidate.uuid, 'pk': check.pk})).content.decode()
    assert 'Old HR' in body
    assert 'Involuntary separation' in body
    assert '50000' not in body
    assert check.flagged is True


def test_an_old_in_progress_row_resumes_at_section_a(client, sent_check):
    ReferenceCheck.objects.filter(pk=sent_check.pk).update(current_step='verifier')
    response = client.post(_verify(sent_check), {'code': _otp_from_outbox()})
    assert response.url == _step(sent_check, 'candidate')
    assert client.get(_step(sent_check, 'candidate')).status_code == 200


def test_an_old_academic_request_still_opens_and_reads(client, hr_client, fresher):
    check = ReferenceCheck.objects.create(
        resume=fresher, kind=schema.ACADEMIC, source_key='reference_1',
        recipient_name='Prof. Rahman', recipient_email='rahman@university.edu')
    otp = check.issue_otp()
    check.save()
    client.post(_verify(check), {'code': otp})
    assert client.get(_step(check, 'referee')).status_code == 200

    check.answers = {'referee_name': 'Prof. Rahman', 'recommend': 'reservations',
                     'integrity_concerns': 'no'}
    check.is_submitted = True
    check.save()
    body = hr_client.get(reverse('reference_checks:response', kwargs={
        'uuid': fresher.uuid, 'pk': check.pk})).content.decode()
    assert 'Recommend with Reservations' in body
    assert check.flagged is True
    assert 'value="academic"' not in hr_client.get(_manage_url(fresher)).content.decode()


# ── What HR gets back ────────────────────────────────────────────────────
VERDICTS = [
    (schema.EMPLOYER, 'conduct_concerns', 'yes', True),
    (schema.EMPLOYER, 'conduct_concerns', 'no', False),
    (schema.EMPLOYER, 'conduct_concerns', 'unable', False),
    (schema.EMPLOYER, 'was_employed', 'no', True),
    (schema.EMPLOYER, 'was_employed', 'unable', False),
    (schema.EMPLOYER, 'separation_nature', 'termination', True),
    (schema.EMPLOYER, 'separation_nature', 'asked_to_resign', True),
    (schema.EMPLOYER, 'separation_nature', 'voluntary_resignation', False),
    (schema.EMPLOYER, 'rehire_eligible', 'yes', False),
    (schema.EMPLOYER, 'rehire_eligible', 'no', True),
    (schema.EMPLOYER, 'rehire_eligible', 'conditional', True),
    (schema.EMPLOYER, 'rehire_eligible', 'not_applicable', False),
    (schema.PROFESSIONAL, 'conduct_concerns', 'yes', True),
    (schema.PROFESSIONAL, 'conduct_concerns', 'unable', False),
    (schema.PROFESSIONAL, 'hire_again', 'yes', False),
    (schema.PROFESSIONAL, 'hire_again', 'no', True),
    (schema.PROFESSIONAL, 'hire_again', 'conditional', True),
    (schema.PROFESSIONAL, 'hire_again', 'unable', False),
]


@pytest.mark.parametrize('kind,question,value,expected', VERDICTS)
def test_every_verdict_flags_or_does_not(candidate, kind, question, value, expected):
    assert value in dict(schema.questions_by_key(kind)[question]['choices'])
    check = ReferenceCheck.objects.create(
        resume=candidate, kind=kind, source_key='employer_1',
        recipient_name='Referee', recipient_email='referee@example.com',
        is_submitted=True, answers={question: value})
    assert check.flagged is expected


def test_hr_reads_a_completed_response_by_section(hr_client, candidate):
    check = ReferenceCheck.objects.create(
        resume=candidate, kind=schema.PROFESSIONAL, source_key='reference_1',
        recipient_name='Karim Uddin', recipient_email='karim@acme.com',
        is_submitted=True, submitted_at=timezone.now(),
        answers={'referee_name': 'Karim Uddin', 'hire_again': 'conditional',
                 'strongest_qualities': 'Very thorough', 'declaration': 'yes',
                 'rating_reliability': 'very_good'})
    body = hr_client.get(reverse('reference_checks:response', kwargs={
        'uuid': candidate.uuid, 'pk': check.pk})).content.decode()
    assert 'Very thorough' in body
    assert 'Conditional / With Reservations' in body
    assert 'Very Good' in body
    assert 'Confirmed' in body
    assert 'Section A — Candidate &amp; Reference Details' in body
    assert 'left this section blank' in body
    assert check.verification_reference_id in body


def test_the_summary_counts_only_contactable_people(candidate):
    summary = services.summarise(candidate)
    assert summary['contactable'] == 3
    assert summary['completed'] == 0


def test_no_template_carries_comments():
    from pathlib import Path

    root = Path(__file__).resolve().parents[3] / 'templates' / 'reference_checks'
    for path in root.rglob('*.html'):
        text = path.read_text()
        for marker in ('{#', '<!--', '{% comment'):
            assert marker not in text, f'{path.name} has {marker}'


# ── Found in review ──────────────────────────────────────────────────────
def test_an_old_employer_reply_keeps_its_concern_details(candidate):
    check = ReferenceCheck.objects.create(
        resume=candidate, kind=schema.EMPLOYER, source_key='employer_1',
        recipient_email='hr@acme.com', is_submitted=True,
        answers={'disciplinary_action': 'yes', 'disciplinary_details': 'Written warning 2023',
                 'last_salary': 'BDT 90,000'})

    sections = {s['key']: s for s in check.answered_sections()}
    legacy = {r['key']: r['value'] for r in sections['legacy']['rows']}

    assert check.flagged
    assert legacy['disciplinary_details'] == 'Written warning 2023'
    assert 'last_salary' not in legacy


def test_an_old_professional_reply_keeps_its_recommendation_headline(candidate):
    check = ReferenceCheck.objects.create(
        resume=candidate, kind=schema.PROFESSIONAL, source_key='reference_1',
        recipient_email='k@acme.com', is_submitted=True,
        answers={'recommend': 'yes_reservations'})

    assert check.flagged
    assert 'reservation' in check.headline.lower()


def test_read_only_fields_are_disabled_so_posted_values_never_win(client, sent_check):
    _verified(client, sent_check)
    client.post(_step(sent_check, 'candidate'), {
        'candidate_full_name': 'Someone Else', 'verification_reference_id': 'FORGED'})

    sent_check.refresh_from_db()
    assert sent_check.answers['verification_reference_id'] == sent_check.verification_reference_id
    assert sent_check.answers['candidate_full_name'] != 'Someone Else'
    body = client.get(_step(sent_check, 'candidate')).content.decode()
    assert 'disabled' in re.search(r'<input[^>]*name="candidate_full_name"[^>]*>', body).group(0)


def test_sending_to_a_different_person_starts_them_on_a_clean_form(hr_client, candidate, sent_check):
    ReferenceCheck.objects.filter(pk=sent_check.pk).update(
        answers={'verifier_name': 'Previous Respondent'}, current_step='employment')
    old_token = sent_check.token

    _send(hr_client, candidate, 'employer_1', recipient_email='someone.else@acme.com')

    sent_check.refresh_from_db()
    assert sent_check.answers == {}
    assert sent_check.current_step == schema.first_step(schema.EMPLOYER)
    assert sent_check.token != old_token


def test_a_request_whose_person_left_the_form_still_shows_on_the_manage_page(candidate, sent_check):
    form = candidate.employee_form
    form.answers = {**form.answers, 'has_employment': 'no'}
    form.save(update_fields=['answers'])

    rows = {r['source_key']: r for r in services.candidate_contacts(candidate)}

    assert rows['employer_1']['check'].pk == sent_check.pk
    assert rows['employer_1']['permitted'] is False
