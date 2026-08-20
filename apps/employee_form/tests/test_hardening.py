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

    _post(client, form, 'employment_gate', {'has_employment': 'yes'})
    form.refresh_from_db(); totals.append(form.total_steps)

    assert totals == sorted(totals), f'displayed step total went backwards: {totals}'


# ── PROBE 8: a stale current_step off the new branch must not dead-end ───
def test_changing_a_branch_answer_keeps_navigation_sane(verified):
    client, form = verified
    _post(client, form, 'section_a', {**SECTION_A, 'nid_copy': _pdf('n.pdf')})
    _post(client, form, 'section_b', {
        **SECTION_B, 'bachelors_certificate': _pdf('b.pdf'),
        'hsc_certificate': _pdf('h.pdf'), 'ssc_certificate': _pdf('s.pdf'),
    })
    _post(client, form, 'employment_gate', {'has_employment': 'yes'})
    form.refresh_from_db()
    assert form.current_step == 'employer_1'

    # Candidate goes back and says they are a fresher after all.
    _post(client, form, 'employment_gate', {'has_employment': 'no'})
    form.refresh_from_db()

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
