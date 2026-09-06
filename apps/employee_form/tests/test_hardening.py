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
    _post(client, form, 'section_a', {**SECTION_A, 'nid_copy': _pdf('n.pdf')})
    _post(client, form, 'section_b', {
        **SECTION_B,
        'bachelors_certificate': _pdf('b.pdf'),
        'hsc_certificate': _pdf('h.pdf'),
        'ssc_certificate': _pdf('s.pdf'),
    })
    _post(client, form, 'employer_1', {
        'employer_1_name': 'Acme',
        'employer_1_hr_contact': '+8801711000000',
        'employer_1_hr_email': 'hr@acme.com',
        'employer_1_position': 'Manager',
        'employer_1_start_date': '2024-01-01',
        'employer_1_end_date': '2020-01-01',
        'employer_1_reason_leaving': 'x',
        'employer_1_contact_permission': 'yes',
    })

    form.refresh_from_db()
    assert form.current_step == 'employer_1', (
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

    _post(client, form, 'employer_1', {})
    form.refresh_from_db(); totals.append(form.total_steps)

    assert totals == sorted(totals), f'displayed step total went backwards: {totals}'


# ── PROBE 8: a stale current_step off the new branch must not dead-end ───
def _reference(index):
    return {
        f'reference_{index}_name': 'Karim Uddin',
        f'reference_{index}_designation': 'CTO, Acme',
        f'reference_{index}_relationship': 'direct_manager',
        f'reference_{index}_contact': '+8801711000000',
        f'reference_{index}_email': 'karim@acme.com',
        f'reference_{index}_contact_permission': 'yes',
    }


def _walk_to_department(client, form):
    """Section C is linear: four employers then two references, then Department."""
    _post(client, form, 'section_a', {**SECTION_A, 'nid_copy': _pdf('n.pdf')})
    _post(client, form, 'section_b', {
        **SECTION_B, 'bachelors_certificate': _pdf('b.pdf'),
        'hsc_certificate': _pdf('h.pdf'), 'ssc_certificate': _pdf('s.pdf'),
    })
    for i in range(1, 5):
        _post(client, form, f'employer_{i}', {})       # no employer: all optional
    for i in range(1, 3):
        _post(client, form, f'reference_{i}', _reference(i))
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
        'sales_target_achievement': '112',
        'sales_key_accounts': 'Two banks',
    })
    form.refresh_from_db()
    assert 'd1_sales' in form.review_path, form.review_path
    assert form.answers['sales_target_achievement'] == 112.0

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
    assert 'sales_key_accounts' not in form.answers, form.answers
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


# ── Employers are all-or-nothing ─────────────────────────────────────────
def _reach_employer_1(client, form):
    _post(client, form, 'section_a', {**SECTION_A, 'nid_copy': _pdf('n.pdf')})
    _post(client, form, 'section_b', {
        **SECTION_B,
        'bachelors_certificate': _pdf('b.pdf'),
        'hsc_certificate': _pdf('h.pdf'),
        'ssc_certificate': _pdf('s.pdf'),
    })
    form.refresh_from_db()
    assert form.current_step == 'employer_1'


def test_fresher_can_pass_every_employer_step_blank(verified):
    """The PDF marks Employer 1 required; that would block freshers outright."""
    client, form = verified
    _reach_employer_1(client, form)

    for index in (1, 2, 3, 4):
        response = _post(client, form, f'employer_{index}', {})
        assert response.status_code == 302, f'employer_{index} blocked a fresher'
        form.refresh_from_db()

    assert form.current_step == 'reference_1'


def test_naming_an_employer_requires_the_rest_of_that_block(verified):
    client, form = verified
    _reach_employer_1(client, form)

    _post(client, form, 'employer_1', {'employer_1_name': 'Acme Ltd'})

    form.refresh_from_db()
    assert form.current_step == 'employer_1', 'a half-filled employer was accepted'
    assert not form.answers.get('employer_1_name')


def test_a_fully_named_employer_is_accepted(verified):
    client, form = verified
    _reach_employer_1(client, form)

    response = _post(client, form, 'employer_1', {
        'employer_1_name': 'Acme Ltd',
        'employer_1_hr_contact': '+8801711000000',
        'employer_1_hr_email': 'hr@acme.com',
        'employer_1_position': 'Manager',
        'employer_1_start_date': '2021-01-01',
        'employer_1_end_date': '2024-01-01',
        'employer_1_contact_permission': 'yes',
    })

    assert response.status_code == 302
    form.refresh_from_db()
    assert form.answers['employer_1_name'] == 'Acme Ltd'
    assert form.current_step == 'employer_2'


# ── "Same as present address" tick box ───────────────────────────────────
def test_ticking_same_address_copies_present_to_permanent(verified):
    """Server-side copy: the browser mirror is convenience, this is the truth."""
    client, form = verified
    data = dict(SECTION_A)
    data['address_same'] = 'on'
    data['present_address'] = 'House 42, Banani, Dhaka'
    data['permanent_address'] = 'SOMETHING COMPLETELY DIFFERENT'
    data['nid_copy'] = _pdf('n.pdf')

    response = _post(client, form, 'section_a', data)

    assert response.status_code == 302
    form.refresh_from_db()
    assert form.answers['address_same'] == 'yes'
    assert form.answers['permanent_address'] == 'House 42, Banani, Dhaka'
    assert 'DIFFERENT' not in form.answers['permanent_address']


def test_ticking_same_address_does_not_need_the_permanent_field(verified):
    """With the field mirrored and locked, the browser may post it empty."""
    client, form = verified
    data = dict(SECTION_A)
    data['address_same'] = 'on'
    data['present_address'] = 'House 42, Banani, Dhaka'
    data['permanent_address'] = ''
    data['nid_copy'] = _pdf('n.pdf')

    response = _post(client, form, 'section_a', data)

    assert response.status_code == 302, 'a mirrored permanent address was rejected'
    form.refresh_from_db()
    assert form.answers['permanent_address'] == 'House 42, Banani, Dhaka'


def test_unticked_keeps_two_separate_addresses(verified):
    client, form = verified
    data = dict(SECTION_A)
    data.pop('address_same', None)
    data['present_address'] = 'House 42, Banani, Dhaka'
    data['permanent_address'] = 'Village Shibpur, Narsingdi'
    data['nid_copy'] = _pdf('n.pdf')

    response = _post(client, form, 'section_a', data)

    assert response.status_code == 302
    form.refresh_from_db()
    assert form.answers['address_same'] == 'no'
    assert form.answers['permanent_address'] == 'Village Shibpur, Narsingdi'


def test_permanent_address_is_still_required_when_not_ticked(verified):
    client, form = verified
    data = dict(SECTION_A)
    data.pop('address_same', None)
    data['permanent_address'] = ''
    data['nid_copy'] = _pdf('n.pdf')

    _post(client, form, 'section_a', data)

    form.refresh_from_db()
    assert form.current_step == 'section_a'


def test_recruiter_view_still_reads_the_pdf_question(verified):
    """The stored answer stays yes/no, so Q11 is answered for the review page."""
    client, form = verified
    data = dict(SECTION_A)
    data['address_same'] = 'on'
    data['nid_copy'] = _pdf('n.pdf')
    _post(client, form, 'section_a', data)

    form.refresh_from_db()
    rows = {r['key']: r for s in form.answered_sections() for r in s['rows']}
    row = rows['address_same']
    assert row['label'] == 'Is your Present Address the same as your Permanent Address?'
    assert row['value'] == 'Yes'


# ── The Master's tick box actually gates its fields ──────────────────────
def _masters_payload():
    return {
        **SECTION_B,
        'bachelors_certificate': _pdf('b.pdf'),
        'hsc_certificate': _pdf('h.pdf'),
        'ssc_certificate': _pdf('s.pdf'),
        'masters_institution': 'BUET',
        'masters_degree_name': 'MSc',
        'masters_major': 'CSE',
        'masters_completion_date': '2021-06-30',
        'masters_certificate': _pdf('msc.pdf'),
    }


def test_unticked_masters_clears_its_details(verified):
    """"No Master's" must not be stored alongside a university name."""
    client, form = verified
    _post(client, form, 'section_a', {**SECTION_A, 'nid_copy': _pdf('n.pdf')})

    data = _masters_payload()
    data.pop('has_masters', None)                 # tick box left unticked
    response = _post(client, form, 'section_b', data)

    assert response.status_code == 302
    form.refresh_from_db()
    assert form.answers['has_masters'] == 'no'
    assert not form.answers.get('masters_institution')
    assert not form.answers.get('masters_degree_name')
    assert not form.files.filter(question_key='masters_certificate').exists()


def test_ticked_masters_keeps_its_details(verified):
    client, form = verified
    _post(client, form, 'section_a', {**SECTION_A, 'nid_copy': _pdf('n.pdf')})

    data = _masters_payload()
    data['has_masters'] = 'on'
    response = _post(client, form, 'section_b', data)

    assert response.status_code == 302
    form.refresh_from_db()
    assert form.answers['has_masters'] == 'yes'
    assert form.answers['masters_institution'] == 'BUET'
    assert form.files.filter(question_key='masters_certificate').exists()


def test_unticking_later_detaches_the_masters_certificate(verified):
    """A certificate must not outlive the qualification it belongs to."""
    client, form = verified
    _post(client, form, 'section_a', {**SECTION_A, 'nid_copy': _pdf('n.pdf')})
    _post(client, form, 'section_b', {**_masters_payload(), 'has_masters': 'on'})
    assert form.files.filter(question_key='masters_certificate').exists()

    again = _masters_payload()
    again.pop('has_masters', None)
    again.pop('masters_certificate', None)
    _post(client, form, 'section_b', again)

    form.refresh_from_db()
    assert not form.files.filter(question_key='masters_certificate').exists()
    assert form.answers['has_masters'] == 'no'


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


# ── PROBE 8: numeric questions must not accept free text ────────────────
def _walk_to_section_b(client, form):
    _post(client, form, 'section_a', {**SECTION_A, 'nid_copy': _pdf('n.pdf')})


def _section_b(**overrides):
    """A section_b post that is complete apart from what the test changes.

    The certificates matter: without them the step fails on the uploads alone,
    and a test asserting "this was rejected" would pass for the wrong reason.
    """
    return {
        **SECTION_B,
        'bachelors_certificate': _pdf('b.pdf'),
        'hsc_certificate': _pdf('h.pdf'),
        'ssc_certificate': _pdf('s.pdf'),
        **overrides,
    }


def test_valid_section_b_advances(verified):
    """Control for the rejection tests below: the baseline post must succeed."""
    client, form = verified
    _walk_to_section_b(client, form)

    _post(client, form, 'section_b', _section_b())

    form.refresh_from_db()
    assert form.current_step != 'section_b'


@pytest.mark.parametrize('key', ['hsc_passing_year', 'hsc_result',
                                 'ssc_passing_year', 'ssc_result'])
def test_education_numbers_reject_text(verified, key):
    """A passing year or GPA is a number; 'asdfasdf' used to be stored verbatim."""
    client, form = verified
    _walk_to_section_b(client, form)

    _post(client, form, 'section_b', _section_b(**{key: 'asdfasdf'}))

    form.refresh_from_db()
    assert form.current_step == 'section_b', f'{key} accepted free text'
    assert (form.answers or {}).get(key) != 'asdfasdf'


def test_passing_year_cannot_be_in_the_future(verified):
    client, form = verified
    _walk_to_section_b(client, form)

    _post(client, form, 'section_b', _section_b(hsc_passing_year='2999'))

    form.refresh_from_db()
    assert form.current_step == 'section_b', 'a future passing year was accepted'


def test_gpa_above_the_scale_is_rejected(verified):
    client, form = verified
    _walk_to_section_b(client, form)

    _post(client, form, 'section_b', _section_b(hsc_result='9.5'))

    form.refresh_from_db()
    assert form.current_step == 'section_b', 'a GPA above the 5.00 scale was accepted'


def test_numeric_answers_are_stored_as_numbers(verified):
    client, form = verified
    _walk_to_section_b(client, form)

    _post(client, form, 'section_b',
          _section_b(hsc_passing_year='2014', hsc_result='4.5'))

    form.refresh_from_db()
    assert form.answers['hsc_passing_year'] == 2014
    assert form.answers['hsc_result'] == 4.5


def test_numeric_inputs_carry_their_bounds_to_the_browser(verified):
    """min/max/step on the input is what stops a bad value before a round trip."""
    client, form = verified
    _post(client, form, 'section_a', {**SECTION_A, 'nid_copy': _pdf('n.pdf')})

    body = client.get(reverse('employee_form:step',
                              kwargs={'token': form.token,
                                      'step_key': 'section_b'})).content.decode()

    year = re.search(r'<input[^>]*name="hsc_passing_year"[^>]*>', body).group(0)
    assert 'type="number"' in year
    assert f'min="{schema.EARLIEST_PASSING_YEAR}"' in year
    assert 'step="1"' in year

    gpa = re.search(r'<input[^>]*name="hsc_result"[^>]*>', body).group(0)
    assert 'type="number"' in gpa
    assert 'max="5"' in gpa


def test_a_zero_answer_counts_as_answered(verified):
    """0 is an answer -- no notice period, a team of none -- not a blank."""
    from apps.employee_form.review import narrative_sections

    client, form = verified
    form.answers = {'notice_period_days': 0}
    form.save()

    rows = [r for section in narrative_sections(form)
            for r in section['answered'] if r['key'] == 'notice_period_days']
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


# ── PROBE 9: nothing shows the candidate a bare section letter ───────────
def test_the_candidate_never_sees_a_section_letter():
    """"Section D7" is our filing, not something a candidate can act on."""
    import re
    visible = []
    for step in schema.STEPS:
        visible += [step['section'], step['title'], step.get('description', '')]
        for question in step['questions']:
            visible += [question['label'], question.get('help', '')]
            visible += [label for _, label in question.get('choices', [])]

    offenders = [t for t in visible if re.search(r'\bSections? [A-D]\d?\b', t)]
    assert not offenders, offenders
