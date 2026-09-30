"""Regression guards for defects found reviewing this app.

Each test here failed once: orphaned uploads on replace, out-of-order
employment dates, future dates of birth, a RIFF container passing as WEBP,
and the secret form token leaking into media paths.
"""
import os
import re

import pytest
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.core.models import Resume
from apps.employee_form import schema
from apps.employee_form.models import EmployeeForm, EmployeeFormFile
from apps.employee_form.services import issue_invite

PDF = b'%PDF-1.4 test'


def _pdf(name):
    return SimpleUploadedFile(name, PDF, content_type='application/pdf')


@pytest.fixture
def candidate(db, sample_job):
    return Resume.objects.create(
        job=sample_job, candidate_name='Probe Candidate',
        email='probe@example.com', final_score=70,
    )


@pytest.fixture
def verified(client, candidate):
    form = issue_invite(candidate)
    otp = re.search(r'code is:\s*(\d{6})', mail.outbox[-1].body).group(1)
    client.post(reverse('employee_form:verify', kwargs={'token': form.token}),
                {'code': otp})
    return client, form


SECTION_A = {
    'candidate_full_name': 'Probe Candidate',
    'mobile_number': '+8801711123456',
    'personal_email': 'probe@example.com',
    'position_applied_for': 'KAM',
    'nid_number': '123',
    'date_of_birth': '1996-04-12',
    'present_address': 'A', 'permanent_address': 'B',
    'address_same': 'no', 'verification_consent': 'yes',
}

SECTION_B = {
    'highest_degree': 'bachelors',
    'bachelors_institution': 'X', 'bachelors_degree_name': 'BBA',
    'bachelors_major': 'M', 'bachelors_completion_date': '2019-01-31',
    'hsc_institution': 'H', 'hsc_board': 'D', 'hsc_passing_year': '2014',
    'hsc_result': '5', 'ssc_institution': 'S', 'ssc_board': 'D',
    'ssc_passing_year': '2012', 'ssc_result': '5',
}


EMPLOYER_1 = {
    'has_employment': 'yes',
    'employer_1_name': 'Acme Ltd',
    'employer_1_employment_type': 'full_time',
    'employer_1_hr_contact': '+8801711000000',
    'employer_1_hr_email': 'hr@acme.com',
    'employer_1_position': 'Manager',
    'employer_1_start_date': '2021-01-01',
    'employer_1_end_date': '2024-01-01',
    'employer_1_reason_leaving': 'Growth',
    'employer_1_separation': 'voluntary_resignation',
    'employer_1_contact_permission': 'yes',
    'employer_1_another': 'no',
}


def _post(client, form, step, data):
    return client.post(
        reverse('employee_form:step',
                kwargs={'token': form.token, 'step_key': step}), data)


# ── PROBE 1: multiple files on one question ──────────────────────────────
def test_multiple_uploads_are_all_stored(verified):
    client, form = verified
    _post(client, form, 'section_a', {**SECTION_A, 'nid_copy': _pdf('nid.pdf')})

    data = dict(SECTION_B)
    data['bachelors_certificate'] = _pdf('bsc.pdf')
    data['hsc_certificate'] = _pdf('hsc.pdf')
    data['ssc_certificate'] = _pdf('ssc.pdf')
    data['training_certificates'] = [_pdf('t1.pdf'), _pdf('t2.pdf'), _pdf('t3.pdf')]
    resp = _post(client, form, 'section_b', data)

    assert resp.status_code == 302, 'section_b did not advance'
    stored = form.files.filter(question_key='training_certificates')
    assert stored.count() == 3, f'expected 3 training certs, got {stored.count()}'
    assert {f.original_name for f in stored} == {'t1.pdf', 't2.pdf', 't3.pdf'}


# ── PROBE 2: the per-question file cap is enforced ───────────────────────
def test_too_many_files_is_rejected(verified):
    client, form = verified
    _post(client, form, 'section_a', {**SECTION_A, 'nid_copy': _pdf('nid.pdf')})

    data = dict(SECTION_B)
    data['bachelors_certificate'] = _pdf('bsc.pdf')
    data['hsc_certificate'] = _pdf('hsc.pdf')
    data['ssc_certificate'] = _pdf('ssc.pdf')
    data['training_certificates'] = [
        _pdf(f't{i}.pdf') for i in range(schema.MAX_FILES_PER_QUESTION + 2)
    ]
    _post(client, form, 'section_b', data)

    form.refresh_from_db()
    assert form.current_step == 'section_b', 'over-cap upload was accepted'
    assert not form.files.filter(question_key='training_certificates').exists()


# ── PROBE 3: replacing an upload must not orphan the old file on disk ────
def test_replacing_an_upload_removes_the_old_file(verified):
    client, form = verified
    _post(client, form, 'section_a', {**SECTION_A, 'nid_copy': _pdf('first.pdf')})

    old = form.files.get(question_key='nid_copy')
    old_path = old.file.path
    assert os.path.exists(old_path)

    _post(client, form, 'section_a', {**SECTION_A, 'nid_copy': _pdf('second.pdf')})

    assert form.files.filter(question_key='nid_copy').count() == 1
    assert not os.path.exists(old_path), (
        'replaced upload still on disk — candidate PII leaks and storage grows'
    )


# ── PROBE 4: uploaded documents must not be publicly readable ────────────
def test_uploaded_document_requires_login(client, verified):
    inner, form = verified
    _post(inner, form, 'section_a', {**SECTION_A, 'nid_copy': _pdf('nid.pdf')})
    url = form.files.get(question_key='nid_copy').file.url

    anon = client.__class__()
    response = anon.get(url)
    assert response.status_code in (302, 403), (
        f'NID scan reachable without login (status {response.status_code})'
    )


# ── PROBE 5: employer end date must not precede the start date ───────────
def test_employer_end_before_start_is_rejected(verified):
    client, form = verified
    _reach_employment(client, form)
    _post(client, form, 'employment', {
        **EMPLOYER_1, 'employer_1_start_date': '2024-01-01',
        'employer_1_end_date': '2020-01-01',
    })

    form.refresh_from_db()
    assert form.current_step == 'employment', (
        'employment ending before it started was accepted into background verification data'
    )


# ── PROBE 6: date of birth must not be in the future ────────────────────
def test_future_date_of_birth_is_rejected(verified):
    client, form = verified
    _post(client, form, 'section_a',
          {**SECTION_A, 'date_of_birth': '2035-01-01', 'nid_copy': _pdf('n.pdf')})

    form.refresh_from_db()
    assert form.current_step == 'section_a', 'future date of birth was accepted'


# ── PROBE 7: total step count must not shrink/grow misleadingly ──────────
def test_step_total_is_stable_once_branching_is_known(verified):
    """The header says "Step N of T"; T must not decrease as the form is filled."""
    client, form = verified
    totals = [form.total_steps]

    _post(client, form, 'section_a', {**SECTION_A, 'nid_copy': _pdf('n.pdf')})
    form.refresh_from_db(); totals.append(form.total_steps)

    _post(client, form, 'section_b', {
        **SECTION_B, 'bachelors_certificate': _pdf('b.pdf'),
        'hsc_certificate': _pdf('h.pdf'), 'ssc_certificate': _pdf('s.pdf'),
    })
    form.refresh_from_db(); totals.append(form.total_steps)

    _post(client, form, 'employment', {'has_employment': 'no'})
    form.refresh_from_db(); totals.append(form.total_steps)

    assert totals == sorted(totals), f'displayed step total went backwards: {totals}'


# ── PROBE 8: a stale current_step off the new branch must not dead-end ───
def _reference(index):
    return {
        f'reference_{index}_name': 'Karim Uddin',
        f'reference_{index}_designation': 'CTO, Acme',
        f'reference_{index}_relationship': 'direct_manager',
        f'reference_{index}_contact': '+8801711000000',
        f'reference_{index}_email': f'referee{index}@acme.com',
        f'reference_{index}_contact_permission': 'yes',
    }


def _walk_to_department(client, form):
    _reach_employment(client, form)
    _post(client, form, 'employment', {'has_employment': 'no'})
    for i in range(1, 3):
        _post(client, form, f'reference_{i}', _reference(i))
    _post(client, form, 'team_reporting', {'manages_team': 'no'})
    form.refresh_from_db()
    assert form.current_step == 'department', form.current_step


def test_changing_a_branch_answer_keeps_navigation_sane(verified):
    """Department is the only branch this form has: it decides which role
    section (D1-D6) the candidate is asked. Changing it must not strand them,
    and must not leave the previous role section attached."""
    client, form = verified
    _walk_to_department(client, form)

    # Sales role questions render inline on the Department step, so they post
    # together with it.
    _post(client, form, 'department', {
        'department': 'banking_financial_services',
        'customer_facing': 'no',
        'sales_business_type': 'Dealer sales',
        'sales_target_achievement': '112%',
        'sales_largest_achievement': 'Closed two banks',
    })
    form.refresh_from_db()
    assert 'd1_sales' in form.review_path, form.review_path
    assert form.answers['sales_target_achievement'] == '112%'

    # Candidate goes back and picks a different department.
    _post(client, form, 'department', {
        'department': 'engineering',
        'tech_stack': 'Django, Postgres',
    })
    form.refresh_from_db()

    assert 'd4_technology' in form.review_path, form.review_path
    assert 'd1_sales' not in form.review_path, 'the old role section is still attached'
    # The abandoned branch's answers must go too, or a Finance candidate's form
    # would still carry what they typed while it said Sales.
    assert 'sales_target_achievement' not in form.answers, form.answers
    assert 'sales_business_type' not in form.answers, form.answers
    assert form.answers['tech_stack'] == 'Django, Postgres'
    assert form.current_step in form.path, 'current_step left off the active branch'
    response = client.get(reverse('employee_form:step', kwargs={
        'token': form.token, 'step_key': form.current_step}))
    assert response.status_code == 200, 'candidate cannot reach their own current step'



# ── PROBE 9: webp magic check should not accept any RIFF container ───────
def test_riff_that_is_not_webp_is_rejected(verified):
    client, form = verified
    fake = SimpleUploadedFile(
        'nid.webp', b'RIFF' + b'\x00' * 4 + b'AVI ' + b'0' * 32,
        content_type='image/webp',
    )
    _post(client, form, 'section_a', {**SECTION_A, 'nid_copy': fake})

    form.refresh_from_db()
    assert not form.files.filter(question_key='nid_copy').exists(), (
        'a non-WEBP RIFF container was stored as an image'
    )


# ── PROBE 10: OTP lockout must not be permanent ──────────────────────────
def test_otp_lockout_is_recoverable_by_the_candidate(client, candidate):
    form = issue_invite(candidate)
    url = reverse('employee_form:verify', kwargs={'token': form.token})
    for _ in range(EmployeeForm.OTP_MAX_ATTEMPTS):
        client.post(url, {'code': '000000'})
    form.refresh_from_db()
    assert form.otp_is_locked

    resp = client.post(
        reverse('employee_form:resend_code', kwargs={'token': form.token}))
    assert resp.status_code == 302
    form.refresh_from_db()
    assert not form.otp_is_locked, 'candidate is permanently locked out'

    new_otp = re.search(r'code is:\s*(\d{6})', mail.outbox[-1].body).group(1)
    assert form.check_otp(new_otp) is True


# ── PROBE 11: the form token must not leak into stored file paths ────────
def test_token_is_not_embedded_in_the_media_path(verified):
    client, form = verified
    _post(client, form, 'section_a', {**SECTION_A, 'nid_copy': _pdf('nid.pdf')})
    stored = form.files.get(question_key='nid_copy')
    assert str(form.token) not in stored.file.name, (
        'the secret form token is embedded in the media URL'
    )


# ── Uploads must survive a validation error elsewhere on the step ────────
def test_valid_upload_survives_an_error_on_another_field(verified):
    """A browser cannot refill a file input, so a typo must not cost the files."""
    client, form = verified
    bad = dict(SECTION_A)
    bad['date_of_birth'] = '2035-01-01'          # rejected
    bad['nid_copy'] = _pdf('nid.pdf')            # valid

    _post(client, form, 'section_a', bad)

    form.refresh_from_db()
    assert form.current_step == 'section_a', 'the bad date was accepted'
    assert form.files.filter(question_key='nid_copy').exists(), (
        'a valid document was discarded because another field failed'
    )


def test_retry_after_the_error_does_not_need_the_file_again(verified):
    client, form = verified
    bad = dict(SECTION_A)
    bad['date_of_birth'] = '2035-01-01'
    bad['nid_copy'] = _pdf('nid.pdf')
    _post(client, form, 'section_a', bad)

    # Second attempt fixes the date and attaches nothing.
    resp = _post(client, form, 'section_a', dict(SECTION_A))

    assert resp.status_code == 302, 'step still blocked without re-attaching the file'
    assert form.files.filter(question_key='nid_copy').count() == 1


def test_an_invalid_upload_is_not_stored_even_if_the_rest_is_fine(verified):
    client, form = verified
    data = dict(SECTION_A)
    data['nid_copy'] = SimpleUploadedFile(
        'nid.pdf', b'MZ\x90\x00 not a pdf', content_type='application/pdf')

    _post(client, form, 'section_a', data)

    form.refresh_from_db()
    assert form.current_step == 'section_a'
    assert not form.files.filter(question_key='nid_copy').exists()


# ── Employment history: Q39 gate and the repeating employer block ───────
def _reach_employment(client, form):
    _post(client, form, 'section_a', {**SECTION_A, 'nid_copy': _pdf('n.pdf')})
    _post(client, form, 'section_b', {
        **SECTION_B,
        'bachelors_certificate': _pdf('b.pdf'),
        'hsc_certificate': _pdf('h.pdf'),
        'ssc_certificate': _pdf('s.pdf'),
    })
    form.refresh_from_db()
    assert form.current_step == 'employment'


def test_a_fresher_answers_no_and_skips_every_employer(verified):
    client, form = verified
    _reach_employment(client, form)

    response = _post(client, form, 'employment', {'has_employment': 'no'})

    assert response.status_code == 302
    form.refresh_from_db()
    assert form.current_step == 'reference_1'
    assert schema.declared_employer_indices(form.answers) == []


def test_the_employment_gate_itself_is_required(verified):
    client, form = verified
    _reach_employment(client, form)

    _post(client, form, 'employment', {})

    form.refresh_from_db()
    assert form.current_step == 'employment'


def test_yes_requires_the_whole_first_employer(verified):
    client, form = verified
    _reach_employment(client, form)

    _post(client, form, 'employment', {'has_employment': 'yes', 'employer_1_name': 'Acme'})

    form.refresh_from_db()
    assert form.current_step == 'employment', 'a half-filled employer was accepted'


def test_a_complete_employer_is_accepted(verified):
    client, form = verified
    _reach_employment(client, form)

    response = _post(client, form, 'employment', EMPLOYER_1)

    assert response.status_code == 302
    form.refresh_from_db()
    assert form.answers['employer_1_name'] == 'Acme Ltd'
    assert form.answers['employer_1_employment_type'] == 'full_time'
    assert form.current_step == 'reference_1'


def test_a_current_employer_needs_no_end_date_or_reason(verified):
    client, form = verified
    _reach_employment(client, form)
    data = {**EMPLOYER_1, 'employer_1_separation': 'currently_employed'}
    del data['employer_1_end_date']
    del data['employer_1_reason_leaving']

    response = _post(client, form, 'employment', data)

    assert response.status_code == 302


def test_a_past_employer_needs_an_end_date(verified):
    client, form = verified
    _reach_employment(client, form)
    data = dict(EMPLOYER_1)
    del data['employer_1_end_date']

    _post(client, form, 'employment', data)

    form.refresh_from_db()
    assert form.current_step == 'employment'


def test_another_employer_yes_requires_employer_two(verified):
    client, form = verified
    _reach_employment(client, form)

    _post(client, form, 'employment', {**EMPLOYER_1, 'employer_1_another': 'yes'})

    form.refresh_from_db()
    assert form.current_step == 'employment'


def test_employer_two_has_no_currently_employed_option():
    second = dict(schema.QUESTIONS_BY_KEY['employer_2_separation']['choices'])
    first = dict(schema.QUESTIONS_BY_KEY['employer_1_separation']['choices'])
    assert 'currently_employed' not in second
    assert 'currently_employed' in first


def test_a_second_employer_is_stored_in_order(verified):
    client, form = verified
    _reach_employment(client, form)
    second = {
        'employer_2_name': 'Beta Ltd', 'employer_2_employment_type': 'contractual',
        'employer_2_hr_contact': '+8801711000001', 'employer_2_hr_email': 'hr@beta.com',
        'employer_2_position': 'Officer', 'employer_2_start_date': '2018-01-01',
        'employer_2_end_date': '2020-12-31', 'employer_2_separation': 'contract_completion',
        'employer_2_contact_permission': 'no', 'employer_2_another': 'no',
    }

    response = _post(client, form, 'employment',
                     {**EMPLOYER_1, 'employer_1_another': 'yes', **second})

    assert response.status_code == 302
    form.refresh_from_db()
    assert schema.declared_employer_indices(form.answers) == [1, 2]


def test_answering_no_clears_the_hidden_employers(verified):
    client, form = verified
    _reach_employment(client, form)
    _post(client, form, 'employment', {**EMPLOYER_1, 'employer_2_name': 'Stale Ltd'})

    form.refresh_from_db()
    assert not form.answers.get('employer_2_name')


# ── Q10 / Q11: permanent address only when it differs ────────────────────
def test_same_address_yes_stores_present_as_permanent(verified):
    client, form = verified
    data = dict(SECTION_A, address_same='yes', present_address='House 42, Banani, Dhaka',
                permanent_address='SOMETHING COMPLETELY DIFFERENT', nid_copy=_pdf('n.pdf'))

    response = _post(client, form, 'section_a', data)

    assert response.status_code == 302
    form.refresh_from_db()
    assert form.answers['address_same'] == 'yes'
    assert form.answers['permanent_address'] == 'House 42, Banani, Dhaka'


def test_same_address_yes_does_not_need_the_permanent_field(verified):
    client, form = verified
    data = dict(SECTION_A, address_same='yes', permanent_address='',
                nid_copy=_pdf('n.pdf'))

    response = _post(client, form, 'section_a', data)

    assert response.status_code == 302


def test_same_address_no_keeps_two_separate_addresses(verified):
    client, form = verified
    data = dict(SECTION_A, address_same='no', present_address='House 42, Banani, Dhaka',
                permanent_address='Village Shibpur, Narsingdi', nid_copy=_pdf('n.pdf'))

    response = _post(client, form, 'section_a', data)

    assert response.status_code == 302
    form.refresh_from_db()
    assert form.answers['permanent_address'] == 'Village Shibpur, Narsingdi'


def test_permanent_address_is_required_when_different(verified):
    client, form = verified
    data = dict(SECTION_A, address_same='no', permanent_address='', nid_copy=_pdf('n.pdf'))

    _post(client, form, 'section_a', data)

    form.refresh_from_db()
    assert form.current_step == 'section_a'


def test_the_same_address_question_is_itself_required(verified):
    client, form = verified
    data = dict(SECTION_A, nid_copy=_pdf('n.pdf'))
    data.pop('address_same')

    _post(client, form, 'section_a', data)

    form.refresh_from_db()
    assert form.current_step == 'section_a'


def test_recruiter_view_reads_the_pdf_question(verified):
    client, form = verified
    _post(client, form, 'section_a', dict(SECTION_A, address_same='yes',
                                          nid_copy=_pdf('n.pdf')))

    form.refresh_from_db()
    rows = {r['key']: r for s in form.answered_sections() for r in s['rows']}
    row = rows['address_same']
    assert row['label'] == 'Is your Present Address the same as your Permanent Address?'
    assert row['value'] == 'Yes'
    assert 'permanent_address' not in rows


# ── Q15 decides which education blocks apply ─────────────────────────────
def _masters_payload():
    return {
        **SECTION_B,
        'highest_degree': 'masters',
        'bachelors_certificate': _pdf('b.pdf'),
        'hsc_certificate': _pdf('h.pdf'),
        'ssc_certificate': _pdf('s.pdf'),
        'masters_institution': 'BUET',
        'masters_degree_name': 'MSc',
        'masters_major': 'CSE',
        'masters_completion_date': '2021-06-30',
        'masters_certificate': _pdf('msc.pdf'),
    }


def test_masters_keeps_its_details(verified):
    client, form = verified
    _post(client, form, 'section_a', {**SECTION_A, 'nid_copy': _pdf('n.pdf')})

    response = _post(client, form, 'section_b', _masters_payload())

    assert response.status_code == 302
    form.refresh_from_db()
    assert form.answers['masters_institution'] == 'BUET'
    assert form.files.filter(question_key='masters_certificate').exists()


def test_masters_block_is_required_when_masters_is_chosen(verified):
    client, form = verified
    _post(client, form, 'section_a', {**SECTION_A, 'nid_copy': _pdf('n.pdf')})
    data = _masters_payload()
    del data['masters_institution']

    _post(client, form, 'section_b', data)

    form.refresh_from_db()
    assert form.current_step == 'section_b'


def test_bachelors_clears_any_masters_details(verified):
    client, form = verified
    _post(client, form, 'section_a', {**SECTION_A, 'nid_copy': _pdf('n.pdf')})
    _post(client, form, 'section_b', _masters_payload())
    assert form.files.filter(question_key='masters_certificate').exists()

    again = {**_masters_payload(), 'highest_degree': 'bachelors'}
    again.pop('masters_certificate')
    _post(client, form, 'section_b', again)

    form.refresh_from_db()
    assert not form.answers.get('masters_institution')
    assert not form.files.filter(question_key='masters_certificate').exists()


def test_other_asks_q36_and_skips_the_bachelors_block(verified):
    client, form = verified
    _post(client, form, 'section_a', {**SECTION_A, 'nid_copy': _pdf('n.pdf')})
    data = {
        'highest_degree': 'other',
        'other_qualification_details': 'Diploma in Engineering, DPI, 2016, CGPA 3.6',
        'hsc_institution': 'H', 'hsc_board': 'D', 'hsc_passing_year': '2014',
        'hsc_result': '5', 'hsc_certificate': _pdf('h.pdf'),
        'ssc_institution': 'S', 'ssc_board': 'D', 'ssc_passing_year': '2012',
        'ssc_result': '5', 'ssc_certificate': _pdf('s.pdf'),
    }

    response = _post(client, form, 'section_b', data)

    assert response.status_code == 302
    form.refresh_from_db()
    assert form.answers['other_qualification_details'].startswith('Diploma')


def test_other_requires_q36(verified):
    client, form = verified
    _post(client, form, 'section_a', {**SECTION_A, 'nid_copy': _pdf('n.pdf')})

    _post(client, form, 'section_b', {**_section_b(), 'highest_degree': 'other'})

    form.refresh_from_db()
    assert form.current_step == 'section_b'


# ── Q14 / Q129: the end and HR-review paths ──────────────────────────────
def test_declining_consent_ends_the_form_for_hr_review(verified):
    client, form = verified

    response = _post(client, form, 'section_a', dict(
        SECTION_A, verification_consent='no', nid_copy=_pdf('n.pdf'), confirm_end='1'))

    assert response.status_code == 302
    form.refresh_from_db()
    assert form.is_submitted is True
    assert form.consent_declined is True
    assert form.status_label == 'Consent declined'
    assert form.path == ['section_a']


def _at_declaration(form):
    form.current_step = schema.FINAL_STEP
    form.answers = {'verification_consent': 'yes'}
    form.save(update_fields=['current_step', 'answers'])


def test_not_agreeing_to_the_declaration_needs_no_signature():
    from apps.employee_form.forms import StepForm
    form = StepForm({'total_experience_years': '3',
                     'availability_status': 'immediately_available',
                     'declaration_agreement': 'disagree'}, step_key=schema.FINAL_STEP)

    assert form.is_valid(), form.errors
    assert form.cleaned_data['signature'] is None


def test_the_final_step_cannot_submit_over_incomplete_earlier_steps(verified):
    client, form = verified
    _at_declaration(form)

    response = _post(client, form, schema.FINAL_STEP, {
        'total_experience_years': '3', 'availability_status': 'immediately_available',
        'declaration_agreement': 'disagree',
    })

    form.refresh_from_db()
    assert form.is_submitted is False
    assert response.url.endswith('/step/section_a/')


def test_a_form_parked_on_a_retired_step_is_re_anchored(verified):
    client, form = verified
    EmployeeForm.objects.filter(pk=form.pk).update(current_step='employer_3')

    response = client.get(reverse('employee_form:entry', kwargs={'token': form.token}))

    form.refresh_from_db()
    assert form.current_step == schema.FIRST_STEP
    assert response.url.endswith(f'/step/{schema.FIRST_STEP}/')


def test_declining_consent_later_drops_everything_after_section_a(verified):
    client, form = verified
    _reach_employment(client, form)
    assert form.files.filter(question_key='bachelors_certificate').exists()

    _post(client, form, 'section_a', dict(SECTION_A, verification_consent='no', confirm_end='1'))

    form.refresh_from_db()
    assert form.is_submitted and form.consent_declined
    assert not form.answers.get('bachelors_institution')
    assert not form.files.filter(question_key='bachelors_certificate').exists()
    assert form.files.filter(question_key='nid_copy').exists()


def test_agreeing_requires_the_signature(verified):
    client, form = verified
    _at_declaration(form)

    _post(client, form, schema.FINAL_STEP, {
        'total_experience_years': '3', 'availability_status': 'immediately_available',
        'declaration_agreement': 'agree',
    })

    form.refresh_from_db()
    assert form.is_submitted is False


@pytest.mark.parametrize('status,needed', [
    ('serving_notice', {'notice_period', 'remaining_notice_period', 'last_working_day'}),
    ('not_yet_resigned', {'notice_period'}),
    ('immediately_available', set()),
    ('currently_unemployed', set()),
])
def test_availability_decides_the_notice_questions(status, needed):
    from apps.core.form_logic import is_required
    answers = {'availability_status': status}
    required = {
        key for key in ('notice_period', 'remaining_notice_period', 'last_working_day')
        if is_required(schema.QUESTIONS_BY_KEY[key], answers)
    }
    assert required == needed


# ── Section D renders its role questions on the same page ────────────────
def _reach_department(client, form):
    form.answers = {**(form.answers or {})}
    form.current_step = 'department'
    form.save(update_fields=['answers', 'current_step'])


def test_department_page_asks_the_role_questions_too(verified):
    """One page: pick the department and answer its section without a hop."""
    client, form = verified
    _reach_department(client, form)

    response = _post(client, form, 'department', {
        'department': 'finance_accounts',
        'finance_software': 'Oracle Fusion',
        'finance_audit_exposure': 'External and regulatory',
    })

    assert response.status_code == 302
    form.refresh_from_db()
    assert form.answers['department'] == 'finance_accounts'
    assert form.answers['finance_software'] == 'Oracle Fusion'
    # And the next step is the declaration, not a separate role page.
    assert form.current_step == schema.FINAL_STEP


def test_changing_department_drops_the_previous_sections_answers(verified):
    """A Finance answer must not survive on a submission that says Engineering."""
    client, form = verified
    _reach_department(client, form)

    _post(client, form, 'department', {
        'department': 'finance_accounts',
        'finance_software': 'Oracle Fusion',
    })
    form.refresh_from_db()
    assert form.answers['finance_software'] == 'Oracle Fusion'

    form.current_step = 'department'
    form.save(update_fields=['current_step'])
    _post(client, form, 'department', {
        'department': 'engineering',
        'tech_stack': 'Django, Postgres',
    })

    form.refresh_from_db()
    assert form.answers['department'] == 'engineering'
    assert form.answers['tech_stack'] == 'Django, Postgres'
    assert not form.answers.get('finance_software'), (
        "the previous department's answers were kept"
    )


def test_role_fields_fragment_serves_only_the_chosen_section(verified):
    client, form = verified
    _reach_department(client, form)
    url = reverse('employee_form:role_fields',
                  kwargs={'token': form.token, 'step_key': 'department'})

    response = client.get(url, {'department': 'engineering'})
    body = response.content.decode()

    assert response.status_code == 200
    assert 'name="tech_stack"' in body
    assert 'name="finance_software"' not in body
    assert 'name="department"' not in body, 'the select must not be duplicated'


def test_role_fields_fragment_needs_a_verified_session(client, candidate):
    form = issue_invite(candidate)
    response = client.get(
        reverse('employee_form:role_fields',
                kwargs={'token': form.token, 'step_key': 'department'}),
        {'department': 'engineering'})
    assert response.status_code == 404


def test_role_fields_fragment_rejects_a_step_with_no_role_section(verified):
    client, form = verified
    response = client.get(
        reverse('employee_form:role_fields',
                kwargs={'token': form.token, 'step_key': 'section_a'}))
    assert response.status_code == 404


# ── Education: passing years are numbers, results are free text ─────────
def _walk_to_section_b(client, form):
    _post(client, form, 'section_a', {**SECTION_A, 'nid_copy': _pdf('n.pdf')})


def _section_b(**overrides):
    return {
        **SECTION_B,
        'bachelors_certificate': _pdf('b.pdf'),
        'hsc_certificate': _pdf('h.pdf'),
        'ssc_certificate': _pdf('s.pdf'),
        **overrides,
    }


def test_valid_section_b_advances(verified):
    client, form = verified
    _walk_to_section_b(client, form)

    _post(client, form, 'section_b', _section_b())

    form.refresh_from_db()
    assert form.current_step != 'section_b'


@pytest.mark.parametrize('key', ['hsc_passing_year', 'ssc_passing_year'])
def test_passing_years_reject_text(verified, key):
    client, form = verified
    _walk_to_section_b(client, form)

    _post(client, form, 'section_b', _section_b(**{key: 'asdfasdf'}))

    form.refresh_from_db()
    assert form.current_step == 'section_b', f'{key} accepted free text'


@pytest.mark.parametrize('key', ['hsc_result', 'ssc_result'])
def test_results_are_required(verified, key):
    client, form = verified
    _walk_to_section_b(client, form)

    _post(client, form, 'section_b', _section_b(**{key: ''}))

    form.refresh_from_db()
    assert form.current_step == 'section_b'


def test_a_letter_grade_result_is_accepted(verified):
    client, form = verified
    _walk_to_section_b(client, form)

    _post(client, form, 'section_b', _section_b(ssc_result='A*A*A', hsc_result='4.50'))

    form.refresh_from_db()
    assert form.answers['ssc_result'] == 'A*A*A'
    assert form.answers['hsc_passing_year'] == 2014


def test_passing_year_cannot_be_in_the_future(verified):
    client, form = verified
    _walk_to_section_b(client, form)

    _post(client, form, 'section_b', _section_b(hsc_passing_year='2999'))

    form.refresh_from_db()
    assert form.current_step == 'section_b', 'a future passing year was accepted'


def test_year_inputs_carry_their_bounds_to_the_browser(verified):
    client, form = verified
    _post(client, form, 'section_a', {**SECTION_A, 'nid_copy': _pdf('n.pdf')})

    body = client.get(reverse('employee_form:step',
                              kwargs={'token': form.token,
                                      'step_key': 'section_b'})).content.decode()

    year = re.search(r'<input[^>]*name="hsc_passing_year"[^>]*>', body).group(0)
    assert 'type="number"' in year
    assert f'min="{schema.EARLIEST_PASSING_YEAR}"' in year
    assert 'step="1"' in year


def test_uploads_are_pdf_or_image_only(verified):
    client, form = verified
    doc = SimpleUploadedFile('nid.docx', b'PK\x03\x04 docx', content_type='application/vnd')

    _post(client, form, 'section_a', {**SECTION_A, 'nid_copy': doc})

    form.refresh_from_db()
    assert form.current_step == 'section_a'
    assert not form.files.filter(question_key='nid_copy').exists()


def test_a_zero_answer_counts_as_answered(verified):
    """0 is an answer -- no notice period, a team of none -- not a blank."""
    from apps.employee_form.review import narrative_sections

    client, form = verified
    form.answers = {'total_experience_years': 0.0}
    form.save()

    rows = [r for section in narrative_sections(form)
            for r in section['answered'] if r['key'] == 'total_experience_years']
    assert rows, '0 was filed as unanswered'


def test_a_fresher_still_shows_experience_in_the_header(verified):
    """0 years is a fresher, not a missing answer -- the header must say so."""
    from apps.employee_form.review import key_facts

    client, form = verified
    form.answers = {'total_experience_years': 0.0}
    form.save()

    facts, shown = key_facts(form)
    labels = [f['label'] for f in facts]
    assert 'Experience (years)' in labels, '0 years vanished from the header strip'
    assert 'total_experience_years' in shown


def test_switching_department_with_an_invalid_role_answer_re_renders_the_new_block(verified):
    client, form = verified
    _reach_department(client, form)
    _post(client, form, 'department', {'department': 'finance_accounts',
                                       'finance_software': 'Oracle'})
    form.current_step = 'department'
    form.save(update_fields=['current_step'])

    response = _post(client, form, 'department', {
        'department': 'banking_financial_services', 'customer_facing': 'no'})

    assert response.status_code == 200
    body = response.content.decode()
    assert 'name="sales_business_type"' in body
    assert 'name="finance_areas"' not in body


def test_a_candidate_serving_notice_may_give_a_future_end_date(verified):
    client, form = verified
    _reach_employment(client, form)

    from datetime import timedelta
    from django.utils import timezone
    notice_ends = (timezone.localdate() + timedelta(days=60)).isoformat()

    response = _post(client, form, 'employment', {**EMPLOYER_1, 'employer_1_end_date': notice_ends})

    assert response.status_code == 302


def test_a_current_end_date_years_ahead_is_taken_for_a_typo(verified):
    client, form = verified
    _reach_employment(client, form)

    response = _post(client, form, 'employment', {**EMPLOYER_1, 'employer_1_end_date': '2099-01-31'})

    assert response.status_code == 200
    assert 'more than a year ahead' in response.content.decode()


def test_a_past_employer_end_date_cannot_be_in_the_future(verified):
    client, form = verified
    _reach_employment(client, form)
    second = {
        'employer_2_name': 'Beta Ltd', 'employer_2_employment_type': 'contractual',
        'employer_2_hr_contact': '+8801711000001', 'employer_2_hr_email': 'hr@beta.com',
        'employer_2_position': 'Officer', 'employer_2_start_date': '2018-01-01',
        'employer_2_end_date': '2099-12-31', 'employer_2_separation': 'contract_completion',
        'employer_2_contact_permission': 'no', 'employer_2_another': 'no',
    }

    _post(client, form, 'employment', {**EMPLOYER_1, 'employer_1_another': 'yes', **second})

    form.refresh_from_db()
    assert form.current_step == 'employment'


def test_old_answers_stay_readable_for_the_recruiter(verified):
    client, form = verified
    form.answers = {
        'department': 'banking_financial_services',
        'sales_key_accounts': 'Two banks', 'notice_period_days': 30,
        'current_responsibilities': 'Dealer network',
    }
    form.save(update_fields=['answers'])

    rows = {r['key']: r for s in form.answered_sections() for r in s['rows']}

    assert rows['sales_key_accounts']['value'] == 'Two banks'
    assert rows['notice_period_days']['value'] == 30
    assert rows['current_responsibilities']['value'] == 'Dealer network'


def test_declining_consent_asks_for_confirmation_before_ending_the_form(verified):
    """One click on "No" saves the answer and asks; nothing is submitted or deleted yet."""
    client, form = verified

    response = _post(client, form, 'section_a', dict(
        SECTION_A, verification_consent='no', nid_copy=_pdf('n.pdf')))

    form.refresh_from_db()
    assert response.status_code == 200
    assert not form.is_submitted
    assert form.answers.get('verification_consent') == 'no'
    assert 'Yes, end and submit my form' in response.content.decode()
