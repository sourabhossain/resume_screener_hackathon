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


# Answers per step for a fresher applying to a Banking role (the one
# department-to-section mapping the source form confirms).
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
    },
    'employment_gate': lambda: {'has_employment': 'no'},
    'reference_1': lambda: {
        'reference_1_name': 'Dr Karim Ahmed',
        'reference_1_designation': 'Professor, University of Dhaka',
        'reference_1_relationship': 'hr_other',
        'reference_1_contact': '+8801811111111',
        'reference_1_email': 'karim@du.ac.bd',
    },
    'reference_2': lambda: {
        'reference_2_name': 'Nusrat Jahan',
        'reference_2_designation': 'Manager, ABC Ltd',
        'reference_2_relationship': 'peer',
        'reference_2_contact': '+8801911111111',
        'reference_2_email': 'nusrat@abc.com',
    },
    'team_management': lambda: {
        'team_structure': 'Student project team of six',
        'team_headcount': '0 direct, 5 indirect',
        'team_functions': 'Market research and reporting',
        'team_authority': 'Coordinator, no budget authority',
    },
    'department': lambda: {'department': 'banking_financial_services'},
    'd1_sales': lambda: {
        'sales_target_achievement': '112',
        'sales_key_accounts': 'Retail banking clients',
        'sales_portfolio_value': 'BDT 2 crore',
        'sales_cycle_length': '6 weeks',
        'sales_crm_tools': 'Salesforce, HubSpot',
        'sales_largest_achievement': 'Closed a BDT 40 lakh account',
    },
    'd1_customer_profile': lambda: {
        'customer_types': 'Corporate and SME banking clients',
        'customer_segments': ['b2b', 'corporate', 'sme'],
        'customer_portfolio_scale': 'About 40 active accounts',
        'customer_products': 'Deposit and card products',
    },
    'd1_performance': lambda: {
        'perf_sales_type': 'New client acquisition',
        'perf_key_achievements': 'Top performer FY24',
        'perf_target_vs_achievement': '112% of target',
    },
    'd7_declaration': lambda: {
        'total_experience_years': '0',
        'current_responsibilities': 'Final-year student, internship at ABC Ltd',
        'measurable_achievements': 'Dean\'s list; 2 case competition wins',
        'availability_status': 'immediately_available',
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

    # Freshers skip employers; Banking routes through D1.
    assert not any(k.startswith('employer_') for k in visited)
    assert 'd1_sales' in visited

    # Answers stored under their schema keys, with choices kept as values.
    assert form.answers['candidate_full_name'] == 'Ayesha Rahman'
    assert form.answers['department'] == 'banking_financial_services'
    assert form.answers['customer_segments'] == ['b2b', 'corporate', 'sme']
    assert form.answers['date_of_birth'] == '1996-04-12'

    # Every upload is attached to the question it was given for.
    keys = set(form.files.values_list('question_key', flat=True))
    assert keys == {
        'nid_copy', 'bachelors_certificate', 'hsc_certificate', 'ssc_certificate',
    }


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
    assert 'B2B, Corporate, SME' in body                # multi-select labels
    assert 'nid.png' in body                            # uploaded document listed
    # Sections the candidate never saw must not appear.
    assert 'Employer 1 Information' not in body
    assert 'Technology / Engineering / Data' not in body


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
    assert form.answers['reference_1_name'] == 'Dr Karim Ahmed'
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
