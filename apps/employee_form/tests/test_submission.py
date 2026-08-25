"""Fills the form end to end, the way a candidate actually would."""
import re

import pytest
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.core.models import Resume
from apps.employee_form import schema
from apps.employee_form.models import EmployeeForm
from apps.employee_form.services import issue_invite

PDF = b'%PDF-1.4 minimal test document'
PNG = b'\x89PNG\r\n\x1a\n' + b'0' * 40


def _pdf(name='doc.pdf'):
    return SimpleUploadedFile(name, PDF, content_type='application/pdf')


def _png(name='scan.png'):
    return SimpleUploadedFile(name, PNG, content_type='image/png')


# Answers per step for a Banking candidate with one previous employer -- the one
# department-to-section mapping the source PDF confirms.
STEP_DATA = {
    'section_a': lambda: {
        'candidate_full_name': 'Ayesha Rahman',
        'mobile_number': '+8801711123456',
        'personal_email': 'ayesha@example.com',
        'position_applied_for': 'Key Account Manager',
        'nid_number': '1234567890',
        'date_of_birth': '1996-04-12',
        'present_address': 'House 12, Road 3, Dhanmondi, Dhaka',
        'permanent_address': 'Village Kachua, Comilla',
        'address_same': 'no',
        'nid_copy': _png('nid.png'),
        'verification_consent': 'yes',
    },
    'section_b': lambda: {
        'highest_degree': 'bachelors',
            'bachelors_institution': 'University of Dhaka',
        'bachelors_degree_name': 'BBA',
        'bachelors_major': 'Marketing',
        'bachelors_completion_date': '2019-01-31',
        'bachelors_certificate': _pdf('bsc.pdf'),
        'hsc_institution': 'Notre Dame College',
        'hsc_board': 'Dhaka',
        'hsc_passing_year': '2014',
        'hsc_result': '5.00',
        'hsc_certificate': _pdf('hsc.pdf'),
        'ssc_institution': 'Ideal School',
        'ssc_board': 'Dhaka',
        'ssc_passing_year': '2012',
        'ssc_result': '5.00',
        'ssc_certificate': _pdf('ssc.pdf'),
        'training_certification_names': 'Consultative Selling (2022)',
        'training_certificates': [_pdf('t1.pdf'), _pdf('t2.pdf')],
    },
    'employer_1': lambda: {
        'employer_1_name': 'Berger Paints Bangladesh Ltd',
        'employer_1_hr_contact': '+8802 9887301',
        'employer_1_hr_email': 'hr@bergerbd.com',
        'employer_1_position': 'Senior Territory Officer',
        'employer_1_start_date': '2021-03-01',
        'employer_1_end_date': '2026-07-15',
        'employer_1_reason_leaving': 'Seeking a broader enterprise portfolio.',
        'employer_1_contact_permission': 'yes',
    },
    # Employers 2-4 are optional; submitted empty to prove they can be skipped.
    'employer_2': lambda: {},
    'employer_3': lambda: {},
    'employer_4': lambda: {},
    'reference_1': lambda: {
        'reference_1_name': 'Kamrul Hasan',
        'reference_1_designation': 'Head of Sales, Berger Paints',
        'reference_1_relationship': 'direct_manager',
        'reference_1_contact': '+8801811111111',
        'reference_1_email': 'kamrul@bergerbd.com',
        'reference_1_contact_permission': 'yes',
    },
    'reference_2': lambda: {
        'reference_2_name': 'Nusrat Jahan',
        'reference_2_designation': 'Regional Manager, Berger Paints',
        'reference_2_relationship': 'skip_level_manager',
        'reference_2_contact': '+8801911111111',
        'reference_2_email': 'nusrat@bergerbd.com',
        'reference_2_contact_permission': 'no',
    },
    # Section D and its role block share a page, so they post together.
    'department': lambda: {
        'department': 'banking_financial_services',
        'sales_target_achievement': '112',
        'sales_key_accounts': 'Retail banking clients',
        'sales_portfolio_value': 'BDT 2 crore',
        'sales_cycle_length': '6 weeks',
        'sales_crm_tools': 'Salesforce, HubSpot',
        'sales_new_business': 'Owned new dealer acquisition for three districts',
        'sales_largest_achievement': 'Closed a BDT 40 lakh account',
    },
    'd7_declaration': lambda: {
        'total_experience_years': '5',
        'notice_period_days': '30',
        'earliest_joining_date': '2026-09-20',
        'current_responsibilities': 'Own enterprise dealer relationships.',
        'measurable_achievements': '112% of target FY24; Best Employee Award.',
        'availability_status': 'serving_notice',
        'declaration_agreement': 'agree',
        'typed_signature': 'Ayesha Rahman',
        'declaration_date': '2026-08-20',
    },
}


@pytest.fixture
def candidate(db, sample_job):
    return Resume.objects.create(
        job=sample_job, candidate_name='Ayesha Rahman',
        email='ayesha@example.com', final_score=82,
    )


@pytest.fixture
def verified(client, candidate):
    form = issue_invite(candidate)
    otp = re.search(r'code is:\s*(\d{6})', mail.outbox[-1].body).group(1)
    client.post(
        reverse('employee_form:verify', kwargs={'token': form.token}), {'code': otp}
    )
    return client, form


def _walk(client, form, stop_before=None):
    """POST each step in turn, following wherever the branching leads."""
    visited = []
    while True:
        form.refresh_from_db()
        step_key = form.current_step
        if form.is_submitted or step_key == stop_before:
            return visited
        assert step_key in STEP_DATA, f'no test data for step {step_key}'
        response = client.post(
            reverse('employee_form:step',
                    kwargs={'token': form.token, 'step_key': step_key}),
            STEP_DATA[step_key](),
        )
        assert response.status_code == 302, (
            f'step {step_key} did not advance: {response.status_code}'
        )
        visited.append(step_key)
        if len(visited) > len(schema.STEPS) + 2:
            raise AssertionError('wizard did not terminate')


def test_full_submission(verified):
    client, form = verified
    visited = _walk(client, form)

    form.refresh_from_db()
    assert form.is_submitted is True
    assert form.submitted_at is not None
    assert visited[-1] == schema.FINAL_STEP

    # The PDF's Section C is linear: all four employer steps are walked even
    # though only the first is filled in. Banking routes through D1 only.
    for index in (1, 2, 3, 4):
        assert f'employer_{index}' in visited
    # D1 is answered on the department page, so it is never a step of its own.
    assert 'department' in visited
    assert 'd1_sales' not in visited
    # Numeric questions are stored as numbers, not as whatever string was typed.
    assert form.answers['sales_target_achievement'] == 112.0
    assert form.answers['hsc_passing_year'] == 2014
    assert form.answers['ssc_passing_year'] == 2012
    assert form.answers['hsc_result'] == 5.0
    assert form.answers['total_experience_years'] == 5.0
    assert form.answers['notice_period_days'] == 30
    assert form.answers['sales_new_business']

    # Answers stored under their schema keys, with choices kept as values.
    assert form.answers['candidate_full_name'] == 'Ayesha Rahman'
    assert form.answers['department'] == 'banking_financial_services'
    assert form.answers['date_of_birth'] == '1996-04-12'
    assert form.answers['employer_1_contact_permission'] == 'yes'
    assert form.answers['reference_2_contact_permission'] == 'no'
    # Skipped optional employers leave nothing behind.
    assert not form.answers.get('employer_2_name')

    # Every upload is attached to the question it was given for.
    keys = set(form.files.values_list('question_key', flat=True))
    assert keys == {
        'nid_copy', 'bachelors_certificate', 'hsc_certificate',
        'ssc_certificate', 'training_certificates',
    }
    assert form.files.filter(question_key='training_certificates').count() == 2


def test_submitted_form_renders_for_the_recruiter(verified, authenticated_client):
    client, form = verified
    _walk(client, form)

    response = authenticated_client.get(
        reverse('employee_form:detail', kwargs={'uuid': form.resume.uuid})
    )
    assert response.status_code == 200
    body = response.content.decode()

    assert 'Ayesha Rahman' in body
    assert 'Banking and Financial Services' in body     # choice label, not raw value
    assert 'nid.png' in body or 'Upload NID Copy' in body   # document surfaced
    assert 'Berger Paints Bangladesh Ltd' in body            # employer card
    assert 'Do not contact' in body                          # reference 2 said no
    # Role sections for other departments must not appear.
    assert 'Technology / Engineering / Data' not in body
    assert 'Finance / Revenue Assurance' not in body


def test_recruiter_page_requires_login(client, candidate):
    issue_invite(candidate)
    response = client.get(
        reverse('employee_form:detail', kwargs={'uuid': candidate.uuid})
    )
    assert response.status_code == 302
    assert '/login/' in response.url


def test_second_submission_is_refused(verified):
    client, form = verified
    _walk(client, form)

    response = client.post(
        reverse('employee_form:step',
                kwargs={'token': form.token, 'step_key': schema.FINAL_STEP}),
        STEP_DATA['d7_declaration'](),
    )
    assert b'already submitted' in response.content.lower()
    assert EmployeeForm.objects.get(pk=form.pk).is_submitted is True


def test_progress_is_kept_between_visits(verified):
    client, form = verified
    _walk(client, form, stop_before='department')

    form.refresh_from_db()
    assert form.is_submitted is False
    assert form.current_step == 'department'
    # Earlier answers survive so the candidate can resume where they left off.
    assert form.answers['reference_1_name'] == 'Kamrul Hasan'
    assert form.files.filter(question_key='nid_copy').exists()


# ── Upload validation ────────────────────────────────────────────────────
def test_disguised_executable_is_rejected(verified):
    """A renamed binary must not be storable as a certificate."""
    client, form = verified
    data = STEP_DATA['section_a']()
    data['nid_copy'] = SimpleUploadedFile(
        'nid.pdf', b'MZ\x90\x00 not a pdf at all', content_type='application/pdf'
    )

    client.post(
        reverse('employee_form:step',
                kwargs={'token': form.token, 'step_key': 'section_a'}),
        data,
    )

    form.refresh_from_db()
    assert form.current_step == 'section_a'
    assert not form.files.filter(question_key='nid_copy').exists()


def test_oversized_upload_is_rejected(verified):
    client, form = verified
    data = STEP_DATA['section_a']()
    oversized = b'%PDF' + b'0' * (schema.MAX_UPLOAD_MB * 1024 * 1024 + 1)
    data['nid_copy'] = SimpleUploadedFile(
        'nid.pdf', oversized, content_type='application/pdf'
    )

    client.post(
        reverse('employee_form:step',
                kwargs={'token': form.token, 'step_key': 'section_a'}),
        data,
    )

    form.refresh_from_db()
    assert form.current_step == 'section_a'
    assert not form.files.filter(question_key='nid_copy').exists()


def test_missing_required_answer_blocks_the_step(verified):
    client, form = verified
    data = STEP_DATA['section_a']()
    del data['nid_number']

    client.post(
        reverse('employee_form:step',
                kwargs={'token': form.token, 'step_key': 'section_a'}),
        data,
    )

    form.refresh_from_db()
    assert form.current_step == 'section_a'


def test_upload_is_not_required_again_when_revisiting(verified):
    """Back then forward must not force the candidate to re-attach files."""
    client, form = verified
    client.post(
        reverse('employee_form:step',
                kwargs={'token': form.token, 'step_key': 'section_a'}),
        STEP_DATA['section_a'](),
    )

    revisit = STEP_DATA['section_a']()
    del revisit['nid_copy']
    response = client.post(
        reverse('employee_form:step',
                kwargs={'token': form.token, 'step_key': 'section_a'}),
        revisit,
    )

    assert response.status_code == 302
    assert form.files.filter(question_key='nid_copy').count() == 1
