"""HR Background Verification & Joining Form (PDF Q1-Q99): access, branching,
prefill from the Employee Information Form, sign-off validation and review."""
import re

import pytest
from django.contrib.messages import get_messages
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.core.form_logic import is_visible
from apps.core.models import Resume
from apps.employee_form import schema as eif
from apps.employee_form.models import EmployeeForm
from apps.hr_verification import schema
from apps.hr_verification.forms import StepForm
from apps.hr_verification.models import HRVerification, HRVerificationFile
from apps.hr_verification.prefill import pending_prefill, prefill_answers

PDF = b'%PDF-1.4 agency report'


def _pdf(name='report.pdf'):
    return SimpleUploadedFile(name, PDF, content_type='application/pdf')


@pytest.fixture
def candidate(db, sample_job):
    return Resume.objects.create(
        job=sample_job,
        candidate_name='Ayesha Rahman',
        email='ayesha@example.com',
        phone='+8801711123456',
        recruiter_status='interviewing',
    )


@pytest.fixture
def hr_user(db, django_user_model):
    return django_user_model.objects.create_user(
        username='hradmin', password='hrpass123', email='hr@example.com',
        first_name='Hasan', last_name='Rahman', is_staff=True,
    )


@pytest.fixture
def hr_client(client, hr_user):
    client.login(username='hradmin', password='hrpass123')
    return client


def _url(name, resume, **kwargs):
    return reverse(f'hr_verification:{name}', kwargs={'uuid': resume.uuid, **kwargs})


def _start(hr_client, candidate):
    hr_client.post(_url('start', candidate))
    return HRVerification.objects.get(resume=candidate)


def _form(step_key, data, context=None, files=None, uploaded=()):
    form = StepForm(data, files or {}, step_key=step_key, context=context or {},
                    already_uploaded=uploaded)
    form.is_valid()
    return form


# ── Minimal valid answers per section ────────────────────────────────────
HR_REVIEW = {
    'candidate_full_name': 'Ayesha Rahman',
    'position_applied_for': 'Senior Python Developer',
    'department': 'engineering',
    'hr_reviewer_name': 'Hasan Rahman',
    'hr_reviewer_designation': 'HR Manager',
    'verification_start_date': '2026-08-01',
    'verification_route': 'internal_hr',
}
IDENTITY = {
    'candidate_nid_number': '[PLACEHOLDER-NID]',
    'candidate_date_of_birth': '1996-04-12',
    'candidate_present_address': '12 Road 5, Dhanmondi, Dhaka',
    'nid_verified': 'yes',
    'birth_certificate_verified': 'na',
    'dob_verified': 'yes',
    'present_address_verified': 'yes',
    'permanent_address_verified': 'yes',
    'police_verification_required': 'no',
}
EDUCATION = {
    'highest_degree': 'ssc',
    'highest_degree_consistent': 'yes',
    'ssc_verification_status': 'verified',
}
EMPLOYMENT = {'has_employment': 'no'}
REFERENCES = {
    'reference_1_name': 'Karim Uddin',
    'reference_1_designation': 'CTO, Acme',
    'reference_1_verification_status': 'verified',
    'reference_1_verification_method': 'direct_call',
    'reference_2_name': 'Nadia Islam',
    'reference_2_designation': 'Lead, Globex',
    'reference_2_verification_status': 'unable',
    'reference_2_verification_method': 'official_email',
    'role_profile_reviewed': 'yes',
}
FINDINGS = {
    'adverse_concern_raised': 'no',
    'risk_rating': 'green',
    'verification_recommendation': 'cleared',
    'hr_verification_summary': 'All checks clear.',
    'verification_completion_date': '2026-08-20',
}
CLEARANCE = {
    'final_verification_status': 'cleared',
    'offer_letter_issued': 'no',
    'offer_accepted': 'pending',
    'confirmed_joining_date': '2026-10-01',
    'joining_certificates_status': 'complete',
    'joining_nid_status': 'complete',
    'joining_employment_documents_status': 'not_required',
    'joining_police_report_status': 'not_required',
    'exception_required': 'no',
    'final_joining_clearance': 'cleared_to_join',
    'hr_approver_name': 'Hasan Rahman',
    'hr_approver_designation': 'HR Manager',
    'final_signoff_date': '2026-08-25',
}
VALID = {
    'hr_review': HR_REVIEW, 'identity': IDENTITY, 'education': EDUCATION,
    'employment': EMPLOYMENT, 'references': REFERENCES, 'findings': FINDINGS,
    'clearance': CLEARANCE,
}
EMPLOYER_1 = {
    'has_employment': 'yes',
    'employer_1_name': 'Acme Ltd',
    'employer_1_hr_contact': '[PLACEHOLDER-PHONE]\nhr@acme.example',
    'employer_1_position': 'Engineer',
    'employer_1_claimed_start_date': '2020-01-01',
    'employer_1_claimed_end_date': '2023-01-01',
    'employer_1_verification_status': 'verified',
    'employer_1_verification_method': 'direct_call',
    'employer_1_tenure_discrepancy': 'no',
    'employer_1_another': 'no',
}


def _all_answers():
    out = {}
    for data in VALID.values():
        out.update(data)
    return out


@pytest.mark.parametrize('step_key', schema.STEP_KEYS)
def test_each_minimal_section_is_valid(step_key):
    context = _all_answers()
    form = _form(step_key, VALID[step_key], context=context)
    assert form.is_valid(), form.errors


# ── Structure matches the PDF ────────────────────────────────────────────
def test_seven_sections_in_pdf_order():
    assert schema.STEP_KEYS == [
        'hr_review', 'identity', 'education', 'employment', 'references',
        'findings', 'clearance',
    ]
    assert [s['section'] for s in schema.STEPS] == [
        'Candidate Link, HR Review & Verification Route',
        'Identity, Address & Police Verification',
        'Educational Qualification & Training Verification',
        'Employment Verification',
        'Professional Reference Verification & Role Profile Review',
        'Adverse Findings, Discrepancy & BGV Outcome',
        'Offer Acceptance & Position Joining Clearance',
    ]


def test_every_pdf_question_1_to_99_is_present():
    numbers = {q['no'] for q in schema.ALL_QUESTIONS}
    assert numbers == set(range(2, 100))
    keys = [q['key'] for q in schema.ALL_QUESTIONS]
    assert len(keys) == len(set(keys))


def test_requisition_id_is_not_asked():
    assert 'requisition_id' not in schema.QUESTIONS_BY_KEY


REMOVED_KEYS = [
    'agency_required', 'employer_1_reference_check_verified',
    'involuntary_separation_wording', 'pending_document_at_joining',
    'training_discrepancy', 'masters_discrepancy', 'bachelors_discrepancy',
    'hsc_discrepancy', 'ssc_discrepancy', 'masters_verified', 'training_verified',
    'identity_verification_method', 'identity_police_remarks',
    'additional_employer_notes', 'employer_1_hr_email', 'employer_1_position_verified',
    'reference_1_email', 'reference_1_check_verified', 'original_nid_checked',
    'original_certificates_checked', 'employment_documents_received',
    'police_report_received', 'masters_institution', 'hsc_passing_year',
]


@pytest.mark.parametrize('key', REMOVED_KEYS)
def test_questions_not_in_the_pdf_are_gone(key):
    assert key not in schema.QUESTIONS_BY_KEY


TYPES = {
    'department': schema.SELECT,
    'verification_start_date': schema.DATE,
    'verification_route': schema.SELECT,
    'agency_contact': schema.TEXTAREA,
    'agency_report_file': schema.FILE,
    'candidate_permanent_address': schema.TEXTAREA,
    'identity_remarks': schema.TEXTAREA,
    'police_verification_required': schema.RADIO,
    'police_verification_route': schema.SELECT,
    'police_verification_status': schema.SELECT,
    'highest_degree': schema.SELECT,
    'highest_degree_consistent': schema.RADIO,
    'training_certificates_received': schema.RADIO,
    'training_verification_status': schema.SELECT,
    'training_verification_method': schema.SELECT,
    'has_employment': schema.RADIO,
    'employer_1_hr_contact': schema.TEXTAREA,
    'employer_1_claimed_current': schema.BOOLEAN,
    'employer_1_verification_status': schema.SELECT,
    'employer_1_verification_method': schema.SELECT,
    'employer_1_reason_consistent': schema.RADIO,
    'employer_1_rehire_eligible': schema.RADIO,
    'employer_1_tenure_discrepancy': schema.RADIO,
    'employer_1_another': schema.RADIO,
    'reference_1_relationship': schema.SELECT,
    'reference_1_contact': schema.TEXTAREA,
    'reference_1_verification_status': schema.SELECT,
    'reference_1_verification_method': schema.SELECT,
    'reference_1_recommend': schema.RADIO,
    'role_profile_reviewed': schema.RADIO,
    'role_claims_consistent': schema.RADIO,
    'adverse_concern_raised': schema.RADIO,
    'finding_categories': schema.CHECKBOX,
    'finding_source': schema.SELECT,
    'source_reliability': schema.SELECT,
    'candidate_clarification_opportunity': schema.RADIO,
    'risk_rating': schema.SELECT,
    'verification_recommendation': schema.SELECT,
    'final_verification_status': schema.SELECT,
    'offer_letter_issued': schema.RADIO,
    'offer_accepted': schema.RADIO,
    'exception_required': schema.RADIO,
    'final_joining_clearance': schema.SELECT,
    'hr_legal_review_completed': schema.RADIO,
}


@pytest.mark.parametrize('key,qtype', TYPES.items())
def test_question_type_follows_the_pdf(key, qtype):
    assert schema.QUESTIONS_BY_KEY[key]['type'] == qtype


def test_the_agency_report_upload_is_pdf_or_image():
    assert schema.QUESTIONS_BY_KEY['agency_report_file']['formats'] == 'pdf_image'


def test_department_list_is_the_25_approved_departments_in_pdf_order():
    choices = schema.QUESTIONS_BY_KEY['department']['choices']
    assert len(choices) == 25
    assert set(choices) == set(eif.DEPARTMENT_CHOICES)
    labels = [label for _, label in choices]
    assert labels[:3] == ['Banking and Financial Services', 'Business Development', 'Data']
    assert labels[-1] == 'Service Assurance-Technical Operations'


def test_relationship_list_is_the_seven_pdf_options():
    for index in (1, 2):
        labels = [label for _, label in
                  schema.QUESTIONS_BY_KEY[f'reference_{index}_relationship']['choices']]
        assert labels == ['Direct Manager', 'Skip-level Manager', 'Peer', 'Direct Report',
                          'HR', 'Academic Supervisor / Faculty', 'Other']


def test_option_lists_keep_pdf_order():
    def labels(key):
        return [label for _, label in schema.QUESTIONS_BY_KEY[key]['choices']]

    assert labels('verification_route') == [
        'Internal HR', 'Background Check Agency',
        'Both Internal HR and Background Check Agency']
    assert labels('police_verification_status') == [
        'Not Started', 'In Progress', 'Clear / Satisfactory', 'Concern / Adverse Finding']
    assert labels('highest_degree') == [
        "Master's / Postgraduate Degree", "Undergraduate / Bachelor's Degree",
        'HSC / A Level / Equivalent', 'SSC / O Level / Equivalent', 'Other']
    assert labels('finding_categories') == [
        'Performance', 'Disciplinary', 'Integrity / Conduct', 'Legal / Police',
        'Involuntary Separation', 'Employment Discrepancy',
        'Education / Document Discrepancy', 'Reference Concern', 'Other']
    assert labels('reference_1_verification_status') == [
        'Verified', 'Unable to Verify', 'Not Yet Attempted']
    assert labels('reference_1_verification_method') == [
        'Direct Call', 'Official Email', 'Agency', 'Other']
    assert labels('has_employment') == [
        'Yes', 'No — Fresher / no applicable employment history']


def test_grid_rows_have_their_own_method_options():
    def labels(key):
        return [label for _, label in schema.QUESTIONS_BY_KEY[key]['choices']]

    for row in ('nid', 'birth_certificate', 'dob'):
        assert labels(f'{row}_method') == ['Document', 'Official Source', 'Agency', 'Other']
    for row in ('present_address', 'permanent_address'):
        assert labels(f'{row}_method') == ['Document', 'Field', 'Agency', 'Other']
    for row in ('masters', 'bachelors', 'other'):
        assert labels(f'{row}_verification_method') == [
            'Document', 'Institution', 'Online', 'Agency', 'Other']
    for row in ('hsc', 'ssc'):
        assert labels(f'{row}_verification_method') == [
            'Document', 'Board', 'Online', 'Agency', 'Other']
    assert labels('nid_verified') == ['Verified', 'Not Verified', 'N/A']
    assert labels('masters_verification_status') == ['Verified', 'Partially', 'Unable', 'N/A']
    assert labels('masters_certificate_received') == ['Yes', 'No', 'N/A']


def test_every_question_renders_in_a_titled_block():
    for step_key in schema.STEP_KEYS:
        blocks = schema.question_groups(step_key)
        grouped = {q['key'] for b in blocks for q in b['questions']}
        assert grouped == {q['key'] for q in schema.questions(step_key)}
        assert all(b['title'] for b in blocks), step_key


def test_no_section_letters_are_shown():
    texts = []
    for step in schema.STEPS:
        texts += [step['section'], step['title'], step['description']]
        for q in step['questions']:
            texts += [q['label'], q['help']] + [c for _, c in q.get('choices', [])]
    assert not [t for t in texts if re.search(r'\bSection [A-F]\b', t)]


# ── Section 1 branching ──────────────────────────────────────────────────
def test_internal_hr_route_hides_and_clears_agency_questions():
    form = _form('hr_review', {**HR_REVIEW, 'agency_name': 'Stale Agency'})
    assert form.is_valid(), form.errors
    assert form.cleaned_data['agency_name'] == ''
    for key in ('agency_name', 'agency_contact', 'agency_report_reference',
                'agency_report_date', 'agency_report_file'):
        assert key in form.hidden_keys


@pytest.mark.parametrize('route', ['agency', 'both'])
def test_agency_route_requires_q9_q10_only(route):
    form = _form('hr_review', {**HR_REVIEW, 'verification_route': route})
    assert set(form.errors) == {'agency_name', 'agency_contact'}

    form = _form('hr_review', {**HR_REVIEW, 'verification_route': route,
                               'agency_name': 'Verify BD', 'agency_contact': 'Rafi'})
    assert form.is_valid(), form.errors


def test_agency_report_rejects_a_word_document():
    docx = SimpleUploadedFile('report.docx', b'PK\x03\x04rest', content_type='application/zip')
    form = _form('hr_review', {**HR_REVIEW, 'verification_route': 'agency',
                               'agency_name': 'A', 'agency_contact': 'B'},
                 files={'agency_report_file': docx})
    assert 'agency_report_file' in form.errors


def test_an_uploaded_agency_report_is_stored(hr_client, candidate):
    verification = _start(hr_client, candidate)
    hr_client.post(_url('step', candidate, step_key='hr_review'), {
        **HR_REVIEW, 'verification_route': 'agency', 'agency_name': 'A',
        'agency_contact': 'B', 'agency_report_file': _pdf()})

    stored = verification.files.get(question_key='agency_report_file')
    assert stored.original_name == 'report.pdf'
    assert stored.uploaded_by.username == 'hradmin'


def test_switching_to_internal_hr_deletes_the_hidden_agency_report(hr_client, candidate):
    verification = _start(hr_client, candidate)
    hr_client.post(_url('step', candidate, step_key='hr_review'), {
        **HR_REVIEW, 'verification_route': 'agency', 'agency_name': 'A',
        'agency_contact': 'B', 'agency_report_file': _pdf()})
    assert verification.files.filter(question_key='agency_report_file').exists()

    hr_client.post(_url('step', candidate, step_key='hr_review'), HR_REVIEW)

    verification.refresh_from_db()
    assert not verification.files.filter(question_key='agency_report_file').exists()
    assert verification.answers['agency_name'] == ''


def test_a_future_verification_date_is_rejected():
    form = _form('hr_review', {**HR_REVIEW, 'verification_start_date': '2099-01-01'})
    assert 'verification_start_date' in form.errors


# ── Section 2 branching ──────────────────────────────────────────────────
def test_permanent_address_is_optional():
    assert 'candidate_permanent_address' not in _form('identity', IDENTITY).errors


def test_every_identity_row_needs_a_status():
    data = dict(IDENTITY)
    del data['permanent_address_verified']
    assert set(_form('identity', data).errors) == {'permanent_address_verified'}


def test_identity_method_options_depend_on_the_row():
    assert 'present_address_method' not in _form(
        'identity', {**IDENTITY, 'present_address_method': 'field'}).errors
    assert 'nid_method' in _form('identity', {**IDENTITY, 'nid_method': 'field'}).errors


def test_a_not_verified_row_requires_overall_remarks():
    form = _form('identity', {**IDENTITY, 'dob_verified': 'no'})
    assert set(form.errors) == {'identity_remarks'}


def test_police_no_hides_and_clears_q22_to_q26():
    form = _form('identity', {**IDENTITY, 'police_verification_status': 'concern',
                              'police_verification_remarks': 'x'})
    assert form.is_valid(), form.errors
    assert form.cleaned_data['police_verification_status'] == ''
    assert form.cleaned_data['police_verification_remarks'] == ''


def test_police_yes_requires_route_and_status_only():
    form = _form('identity', {**IDENTITY, 'police_verification_required': 'yes'})
    assert set(form.errors) == {'police_verification_route', 'police_verification_status'}

    form = _form('identity', {**IDENTITY, 'police_verification_required': 'yes',
                              'police_verification_route': 'agency',
                              'police_verification_status': 'clear'})
    assert form.is_valid(), form.errors


def test_police_concern_requires_remarks():
    base = {**IDENTITY, 'police_verification_required': 'yes',
            'police_verification_route': 'direct_internal',
            'police_verification_status': 'concern'}
    assert set(_form('identity', base).errors) == {'police_verification_remarks'}
    assert _form('identity', {**base, 'police_verification_remarks': 'Case filed'}).is_valid()


# ── Section 3 branching ──────────────────────────────────────────────────
ROWS = {
    'masters': {'masters', 'bachelors', 'hsc', 'ssc'},
    'bachelors': {'bachelors', 'hsc', 'ssc'},
    'hsc': {'hsc', 'ssc'},
    'ssc': {'ssc'},
    'other': {'other', 'hsc', 'ssc'},
}


@pytest.mark.parametrize('degree,rows', ROWS.items())
def test_highest_degree_decides_the_qualification_rows(degree, rows):
    answers = {'highest_degree': degree}
    for row in ('masters', 'bachelors', 'hsc', 'ssc', 'other'):
        question = schema.QUESTIONS_BY_KEY[f'{row}_verification_status']
        assert is_visible(question, answers) == (row in rows), (degree, row)

    form = _form('education', {'highest_degree': degree, 'highest_degree_consistent': 'yes'})
    assert set(form.errors) == {f'{row}_verification_status' for row in rows}


def test_hidden_qualification_rows_are_cleared():
    form = _form('education', {**EDUCATION, 'masters_details': 'MSc, DU',
                               'masters_verification_status': 'verified'})
    assert form.is_valid(), form.errors
    assert form.cleaned_data['masters_details'] == ''
    assert form.cleaned_data['masters_verification_status'] == ''


@pytest.mark.parametrize('answer', ['no', 'further_review'])
def test_inconsistent_degree_requires_education_remarks(answer):
    form = _form('education', {**EDUCATION, 'highest_degree_consistent': answer})
    assert set(form.errors) == {'education_remarks'}


def test_a_partially_verified_row_requires_education_remarks():
    form = _form('education', {**EDUCATION, 'ssc_verification_status': 'partially'})
    assert set(form.errors) == {'education_remarks'}


def test_no_training_declared_hides_q32_to_q35():
    form = _form('education', {**EDUCATION, 'training_verification_status': 'verified'})
    assert form.is_valid(), form.errors
    assert form.cleaned_data['training_verification_status'] == ''


def test_training_declared_requires_q32_and_q33():
    form = _form('education', {**EDUCATION, 'training_certification_names': 'AWS SA'})
    assert set(form.errors) == {'training_certificates_received',
                                'training_verification_status'}


def test_training_verified_needs_method_but_not_remarks():
    base = {**EDUCATION, 'training_certification_names': 'AWS SA',
            'training_certificates_received': 'yes',
            'training_verification_status': 'verified'}
    assert set(_form('education', base).errors) == {'training_verification_method'}
    assert _form('education', {**base, 'training_verification_method': 'online'}).is_valid()


@pytest.mark.parametrize('status', ['partially_verified', 'unable'])
def test_training_not_verified_needs_method_and_remarks(status):
    base = {**EDUCATION, 'training_certification_names': 'AWS SA',
            'training_certificates_received': 'no', 'training_verification_status': status}
    assert set(_form('education', base).errors) == {
        'training_verification_method', 'training_remarks'}


def test_training_not_applicable_hides_method_but_needs_remarks():
    form = _form('education', {**EDUCATION, 'training_certification_names': 'AWS SA',
                               'training_certificates_received': 'na',
                               'training_verification_status': 'na',
                               'training_verification_method': 'online'})
    assert set(form.errors) == {'training_remarks'}
    assert 'training_verification_method' in form.hidden_keys


# ── Section 4: employment gate and employer chain ────────────────────────
def test_fresher_hides_and_clears_every_employer_block():
    form = _form('employment', {'has_employment': 'no', 'employer_1_name': 'Stale'})
    assert form.is_valid(), form.errors
    assert form.cleaned_data['employer_1_name'] == ''


def test_has_employment_is_required():
    assert 'has_employment' in _form('employment', {}).errors


def test_employment_yes_requires_employer_one():
    form = _form('employment', {'has_employment': 'yes'})
    assert set(form.errors) == {
        'employer_1_name', 'employer_1_hr_contact', 'employer_1_position',
        'employer_1_claimed_start_date', 'employer_1_claimed_end_date',
        'employer_1_verification_status', 'employer_1_tenure_discrepancy',
        'employer_1_another',
    }


def test_a_complete_employer_block_saves():
    assert _form('employment', EMPLOYER_1).is_valid()


def test_current_tick_hides_the_claimed_end_date():
    data = {**EMPLOYER_1, 'employer_1_claimed_current': 'on'}
    del data['employer_1_claimed_end_date']
    form = _form('employment', data)
    assert form.is_valid(), form.errors
    assert form.cleaned_data['employer_1_claimed_current'] == 'yes'
    assert form.cleaned_data['employer_1_claimed_end_date'] is None or \
        form.cleaned_data['employer_1_claimed_end_date'] == ''


def test_confirmed_period_is_optional():
    form = _form('employment', {**EMPLOYER_1, 'employer_1_confirmed_start_date': '2020-02-01'})
    assert form.is_valid(), form.errors


def test_claimed_end_before_start_is_rejected():
    form = _form('employment', {**EMPLOYER_1, 'employer_1_claimed_end_date': '2019-01-01'})
    assert 'employer_1_claimed_end_date' in form.errors


def test_confirmed_end_before_start_is_rejected():
    form = _form('employment', {**EMPLOYER_1,
                                'employer_1_confirmed_start_date': '2023-01-01',
                                'employer_1_confirmed_end_date': '2020-01-01'})
    assert 'employer_1_confirmed_end_date' in form.errors


def test_method_not_required_when_not_yet_attempted():
    data = {**EMPLOYER_1, 'employer_1_verification_status': 'not_attempted'}
    del data['employer_1_verification_method']
    assert _form('employment', data).is_valid()


@pytest.mark.parametrize('status', ['verified', 'partially_verified', 'unable'])
def test_method_required_once_attempted(status):
    data = {**EMPLOYER_1, 'employer_1_verification_status': status}
    del data['employer_1_verification_method']
    assert set(_form('employment', data).errors) == {'employer_1_verification_method'}


@pytest.mark.parametrize('extra', [
    {'employer_1_tenure_discrepancy': 'yes'},
    {'employer_1_reason_consistent': 'no'},
])
def test_discrepancy_or_inconsistent_reason_requires_remarks(extra):
    assert set(_form('employment', {**EMPLOYER_1, **extra}).errors) == {'employer_1_remarks'}


def test_another_employer_reveals_employer_two():
    form = _form('employment', {**EMPLOYER_1, 'employer_1_another': 'yes'})
    assert 'employer_2_name' in form.errors
    assert 'employer_3_name' not in form.errors


def test_employer_chain_reaches_ten_and_stops():
    answers = {'has_employment': 'yes',
               **{f'employer_{i}_another': 'yes' for i in range(1, 10)}}
    assert is_visible(schema.QUESTIONS_BY_KEY['employer_10_name'], answers)
    assert 'employer_10_another' not in schema.QUESTIONS_BY_KEY
    answers['employer_4_another'] = 'no'
    assert not is_visible(schema.QUESTIONS_BY_KEY['employer_5_name'], answers)


# ── Section 5 ────────────────────────────────────────────────────────────
@pytest.mark.parametrize('index', [1, 2])
def test_reference_status_and_method_are_both_required(index):
    data = dict(REFERENCES)
    del data[f'reference_{index}_verification_status']
    del data[f'reference_{index}_verification_method']
    assert set(_form('references', data).errors) == {
        f'reference_{index}_verification_status', f'reference_{index}_verification_method'}


@pytest.mark.parametrize('answer,needs', [('no', True), ('partially', True),
                                          ('yes', False), ('na', False)])
def test_role_claims_answer_decides_q69(answer, needs):
    form = _form('references', {**REFERENCES, 'role_claims_consistent': answer})
    assert ('role_further_validation' in form.errors) == needs
    if not needs:
        assert 'role_further_validation' in form.hidden_keys


# ── Section 6 ────────────────────────────────────────────────────────────
def test_no_concern_hides_q71_to_q77():
    form = _form('findings', {**FINDINGS, 'finding_details': 'stale'})
    assert form.is_valid(), form.errors
    assert form.cleaned_data['finding_details'] == ''
    assert form.cleaned_data['finding_categories'] == []


def test_a_concern_requires_q71_to_q77_except_clarification():
    form = _form('findings', {**FINDINGS, 'adverse_concern_raised': 'yes'})
    assert set(form.errors) == {
        'finding_categories', 'finding_source', 'source_reliability', 'finding_details',
        'candidate_clarification_opportunity', 'reviewer_assessment'}


def test_clarification_shown_only_when_candidate_was_asked():
    base = {**FINDINGS, 'adverse_concern_raised': 'yes',
            'finding_categories': ['integrity', 'reference_concern'],
            'finding_source': 'professional_reference', 'source_reliability': 'verified',
            'finding_details': 'x', 'reviewer_assessment': 'y'}
    assert _form('findings', {**base, 'candidate_clarification_opportunity': 'no'}).is_valid()
    form = _form('findings', {**base, 'candidate_clarification_opportunity': 'yes'})
    assert set(form.errors) == {'candidate_clarification'}
    form = _form('findings', {**base, 'candidate_clarification_opportunity': 'yes',
                              'candidate_clarification': 'Explained'})
    assert form.is_valid(), form.errors
    assert form.cleaned_data['finding_categories'] == ['integrity', 'reference_concern']


# ── Section 7 ────────────────────────────────────────────────────────────
def test_confirmed_joining_date_is_required():
    data = dict(CLEARANCE)
    del data['confirmed_joining_date']
    assert set(_form('clearance', data).errors) == {'confirmed_joining_date'}


def test_offer_issued_requires_its_date():
    assert set(_form('clearance', {**CLEARANCE, 'offer_letter_issued': 'yes'}).errors) == {
        'offer_letter_issue_date'}


def test_offer_accepted_requires_its_date():
    assert set(_form('clearance', {**CLEARANCE, 'offer_accepted': 'yes'}).errors) == {
        'offer_acceptance_date'}


def test_a_pending_checklist_item_requires_q91():
    form = _form('clearance', {**CLEARANCE, 'joining_nid_status': 'pending'})
    assert set(form.errors) == {'pending_items'}
    form = _form('clearance', {**CLEARANCE, 'pending_items': 'stale'})
    assert form.is_valid()
    assert form.cleaned_data['pending_items'] == ''


def test_every_checklist_row_needs_a_status():
    data = dict(CLEARANCE)
    del data['joining_police_report_status']
    assert set(_form('clearance', data).errors) == {'joining_police_report_status'}


def test_exception_question_is_required_and_yes_requires_details():
    data = dict(CLEARANCE)
    del data['exception_required']
    assert set(_form('clearance', data).errors) == {'exception_required'}
    assert set(_form('clearance', {**CLEARANCE, 'exception_required': 'yes'}).errors) == {
        'exception_details', 'hr_legal_review_completed'}


Q99_CONTEXTS = [
    {'risk_rating': 'red'},
    {'risk_rating': 'critical'},
    {'verification_recommendation': 'further_review'},
    {'verification_recommendation': 'not_cleared'},
    {'adverse_concern_raised': 'yes'},
    {'police_verification_status': 'concern'},
]


@pytest.mark.parametrize('context', Q99_CONTEXTS)
def test_q99_required_by_a_material_flag_from_another_section(context):
    form = _form('clearance', CLEARANCE, context=context)
    assert set(form.errors) == {'hr_legal_review_completed'}


def test_q99_required_by_an_exception_on_the_same_page():
    form = _form('clearance', {**CLEARANCE, 'exception_required': 'yes',
                               'exception_details': 'CEO approved'})
    assert set(form.errors) == {'hr_legal_review_completed'}


def test_q99_hidden_and_cleared_without_a_flag():
    context = {'risk_rating': 'amber', 'verification_recommendation': 'cleared_conditions',
               'adverse_concern_raised': 'no', 'police_verification_status': 'clear'}
    form = _form('clearance', {**CLEARANCE, 'hr_legal_review_completed': 'yes'},
                 context=context)
    assert form.is_valid(), form.errors
    assert form.cleaned_data['hr_legal_review_completed'] == ''


def test_q99_uses_stored_answers_from_other_sections(hr_client, candidate):
    verification = _start(hr_client, candidate)
    hr_client.post(_url('step', candidate, step_key='findings'),
                   {**FINDINGS, 'risk_rating': 'red'})

    response = hr_client.post(_url('step', candidate, step_key='clearance'), CLEARANCE)

    assert 'hr_legal_review_completed' in response.context['form'].errors
    assert response.context['logic_context']['risk_rating'] == 'red'
    hr_client.post(_url('step', candidate, step_key='clearance'),
                   {**CLEARANCE, 'hr_legal_review_completed': 'yes'})
    verification.refresh_from_db()
    assert verification.is_step_complete('clearance')


def test_step_page_ships_the_rules_to_the_browser(hr_client, candidate):
    _start(hr_client, candidate)
    body = hr_client.get(_url('step', candidate, step_key='clearance')).content.decode()
    assert 'form-logic-rules' in body
    assert 'data-logic-group' in body
    assert 'hr_legal_review_completed' in body
    assert 'hrv-conditional' not in body


# ── Prefill from the Employee Information Form ───────────────────────────
EIF_ANSWERS = {
    'candidate_full_name': 'Ayesha Rahman',
    'position_applied_for': 'Senior Python Developer',
    'department': 'engineering',
    'nid_number': '[PLACEHOLDER-NID]',
    'birth_certificate_number': '[PLACEHOLDER-BC]',
    'date_of_birth': '1996-04-12',
    'present_address': '12 Road 5, Dhanmondi, Dhaka',
    'address_same': 'no',
    'permanent_address': 'Village Kalia, Narail',
    'highest_degree': 'bachelors',
    'bachelors_institution': 'University of Dhaka',
    'bachelors_degree_name': 'BSc',
    'bachelors_major': 'CSE',
    'bachelors_completion_date': '2018-06-30',
    'hsc_institution': 'Notre Dame College',
    'hsc_board': 'Dhaka',
    'hsc_passing_year': 2014,
    'hsc_result': '5.00',
    'ssc_institution': 'Motijheel Ideal',
    'ssc_board': 'Dhaka',
    'ssc_passing_year': 2012,
    'ssc_result': '5.00',
    'training_certification_names': 'AWS Solutions Architect',
    'has_employment': 'yes',
    'employer_1_name': 'Acme Ltd',
    'employer_1_hr_contact': '[PLACEHOLDER-PHONE]',
    'employer_1_hr_email': 'hr@acme.example',
    'employer_1_position': 'Senior Engineer',
    'employer_1_start_date': '2022-02-01',
    'employer_1_separation': 'currently_employed',
    'employer_1_another': 'yes',
    'employer_2_name': 'Globex',
    'employer_2_hr_contact': '[PLACEHOLDER-PHONE-2]',
    'employer_2_hr_email': 'hr@globex.example',
    'employer_2_position': 'Engineer',
    'employer_2_start_date': '2018-07-01',
    'employer_2_end_date': '2022-01-31',
    'employer_2_reason_leaving': 'Better opportunity',
    'employer_2_separation': 'voluntary_resignation',
    'employer_2_another': 'no',
    'reference_1_name': 'Karim Uddin',
    'reference_1_designation': 'CTO, Acme',
    'reference_1_relationship': 'direct_manager',
    'reference_1_contact': '[PLACEHOLDER-PHONE-3]',
    'reference_1_email': 'karim@acme.example',
    'reference_2_name': 'Nadia Islam',
    'reference_2_designation': 'HR Lead, Globex',
    'reference_2_relationship': 'hr_other',
}


@pytest.fixture
def employee_form(candidate):
    return EmployeeForm.objects.create(resume=candidate, is_submitted=True,
                                       answers=dict(EIF_ANSWERS))


def test_prefill_maps_every_eif_key(employee_form, candidate):
    values = prefill_answers(candidate)

    assert values['candidate_full_name'] == 'Ayesha Rahman'
    assert values['position_applied_for'] == 'Senior Python Developer'
    assert values['department'] == 'engineering'
    assert values['candidate_nid_number'] == '[PLACEHOLDER-NID]'
    assert values['candidate_birth_certificate_number'] == '[PLACEHOLDER-BC]'
    assert values['candidate_date_of_birth'] == '1996-04-12'
    assert values['candidate_present_address'] == '12 Road 5, Dhanmondi, Dhaka'
    assert values['candidate_permanent_address'] == 'Village Kalia, Narail'

    assert values['nid_submitted_value'] == '[PLACEHOLDER-NID]'
    assert values['birth_certificate_submitted_value'] == '[PLACEHOLDER-BC]'
    assert values['dob_submitted_value'] == '12 Apr 1996'
    assert values['present_address_submitted_value'] == '12 Road 5, Dhanmondi, Dhaka'
    assert values['permanent_address_submitted_value'] == 'Village Kalia, Narail'

    assert values['highest_degree'] == 'bachelors'
    assert values['bachelors_details'] == 'University of Dhaka — BSc — CSE — Completed 30 Jun 2018'
    assert values['hsc_details'] == (
        'Notre Dame College — Board: Dhaka — Passing year: 2014 — Result: 5.00')
    assert values['ssc_details'] == (
        'Motijheel Ideal — Board: Dhaka — Passing year: 2012 — Result: 5.00')
    assert 'masters_details' not in values
    assert values['training_certification_names'] == 'AWS Solutions Architect'

    assert values['has_employment'] == 'yes'
    assert values['employer_1_name'] == 'Acme Ltd'
    assert values['employer_1_hr_contact'] == '[PLACEHOLDER-PHONE]\nhr@acme.example'
    assert values['employer_1_position'] == 'Senior Engineer'
    assert values['employer_1_claimed_start_date'] == '2022-02-01'
    assert values['employer_1_claimed_current'] == 'yes'
    assert 'employer_1_claimed_end_date' not in values
    assert values['employer_1_another'] == 'yes'
    assert values['employer_2_name'] == 'Globex'
    assert values['employer_2_claimed_end_date'] == '2022-01-31'
    assert 'employer_2_claimed_current' not in values
    assert values['employer_2_claimed_reason_leaving'] == 'Better opportunity'
    assert values['employer_2_another'] == 'no'
    assert 'employer_3_name' not in values

    assert values['reference_1_name'] == 'Karim Uddin'
    assert values['reference_1_designation'] == 'CTO, Acme'
    assert values['reference_1_relationship'] == 'direct_manager'
    assert values['reference_1_contact'] == '[PLACEHOLDER-PHONE-3]\nkarim@acme.example'
    assert values['reference_2_relationship'] == 'hr'

    for key in values:
        assert key in schema.QUESTIONS_BY_KEY, f'prefill writes unknown key {key}'


def test_prefill_reads_only_keys_the_eif_schema_defines():
    from apps.hr_verification import prefill

    eif_keys = set(eif.QUESTIONS_BY_KEY)
    for source in prefill.DIRECT_MAP.values():
        assert source in eif_keys, source
    for key in ('address_same', 'permanent_address', 'highest_degree', 'has_employment',
                'employer_1_separation', 'employer_1_hr_email', 'employer_1_another',
                'reference_1_email', 'reference_2_relationship', 'hsc_board',
                'hsc_result', 'ssc_passing_year', 'masters_degree_name'):
        assert key in eif_keys, key


def test_same_address_is_not_prefilled_into_q18(employee_form, candidate):
    employee_form.answers = {**EIF_ANSWERS, 'address_same': 'yes',
                             'permanent_address': EIF_ANSWERS['present_address']}
    employee_form.save()
    assert 'candidate_permanent_address' not in prefill_answers(candidate)


def test_fresher_prefills_no_employment(employee_form, candidate):
    employee_form.answers = {'has_employment': 'no'}
    employee_form.save()
    values = prefill_answers(candidate)
    assert values['has_employment'] == 'no'
    assert not any(k.startswith('employer_') for k in values)


def test_legacy_hsc_highest_degree_maps_across(employee_form, candidate):
    employee_form.answers = {'highest_degree': 'hsc'}
    employee_form.save()
    assert prefill_answers(candidate)['highest_degree'] == 'hsc'


def test_hr_judgements_are_never_prefilled(employee_form, candidate):
    values = prefill_answers(candidate)
    for key in ('nid_verified', 'nid_method', 'masters_verification_status',
                'employer_1_verification_status', 'employer_1_confirmed_start_date',
                'employer_1_tenure_discrepancy', 'reference_1_verification_status',
                'risk_rating', 'verification_recommendation', 'final_joining_clearance',
                'hr_approver_name', 'police_verification_status',
                'hr_legal_review_completed', 'adverse_concern_raised'):
        assert key not in values, key


def test_name_and_position_fall_back_to_the_application(candidate):
    values = prefill_answers(candidate)
    assert 'requisition_id' not in values
    assert values['candidate_full_name'] == 'Ayesha Rahman'
    assert values['position_applied_for'] == 'Senior Python Developer'


def test_prefill_does_not_overwrite_what_hr_typed(hr_client, candidate, employee_form):
    verification = _start(hr_client, candidate)
    verification.answers = {'candidate_nid_number': '[PLACEHOLDER-HR]'}
    verification.save()
    assert 'candidate_nid_number' not in pending_prefill(verification)


def test_prefill_reaches_the_rendered_form(hr_client, candidate, employee_form):
    _start(hr_client, candidate)
    body = hr_client.get(_url('step', candidate, step_key='identity')).content.decode()
    assert '[PLACEHOLDER-NID]' in body
    assert 'Dhanmondi' in body
    assert 'matches your documents' not in body


def test_prefilled_current_employer_renders_ticked(hr_client, candidate, employee_form):
    _start(hr_client, candidate)
    body = hr_client.get(_url('step', candidate, step_key='employment')).content.decode()
    tick = re.search(r'<input type="checkbox" data-boolean\s+name="employer_1_claimed_current"'
                     r'[^>]*>', body).group(0)
    assert 'checked' in tick
    tick2 = re.search(r'<input type="checkbox" data-boolean\s+name="employer_2_claimed_current"'
                      r'[^>]*>', body).group(0)
    assert 'checked' not in tick2


def test_a_stored_no_tick_renders_unticked(hr_client, candidate):
    verification = _start(hr_client, candidate)
    verification.answers = {'employer_1_claimed_current': 'no'}
    verification.save()
    body = hr_client.get(_url('step', candidate, step_key='employment')).content.decode()
    tick = re.search(r'<input type="checkbox" data-boolean\s+name="employer_1_claimed_current"'
                     r'[^>]*>', body).group(0)
    assert 'checked' not in tick


# ── Sign-off ─────────────────────────────────────────────────────────────
def _fill_everything(hr_client, candidate):
    verification = _start(hr_client, candidate)
    for step_key in schema.STEP_KEYS:
        hr_client.post(_url('step', candidate, step_key=step_key), VALID[step_key])
    verification.refresh_from_db()
    assert verification.completed_count == schema.TOTAL_STEPS
    return verification


def test_sign_off_needs_every_section(hr_client, candidate):
    verification = _start(hr_client, candidate)
    hr_client.post(_url('step', candidate, step_key='hr_review'), HR_REVIEW)
    hr_client.post(_url('submit', candidate))
    verification.refresh_from_db()
    assert not verification.is_submitted


def test_sign_off_succeeds_when_everything_required_is_answered(hr_client, candidate):
    verification = _fill_everything(hr_client, candidate)
    assert verification.missing_required() == []

    hr_client.post(_url('submit', candidate))

    verification.refresh_from_db()
    assert verification.is_submitted
    assert verification.submitted_by.username == 'hradmin'
    response = hr_client.get(_url('step', candidate, step_key='hr_review'))
    assert response.status_code == 302
    assert _url('detail', candidate) in response.url


def test_sign_off_refuses_and_lists_what_is_missing(hr_client, candidate):
    verification = _fill_everything(hr_client, candidate)
    answers = dict(verification.answers)
    answers.pop('confirmed_joining_date')
    HRVerification.objects.filter(pk=verification.pk).update(answers=answers)

    response = hr_client.post(_url('submit', candidate))

    verification.refresh_from_db()
    assert not verification.is_submitted
    assert _url('step', candidate, step_key='clearance') in response.url
    text = ' '.join(str(m) for m in get_messages(response.wsgi_request))
    assert 'Confirmed Joining Date' in text


def test_sign_off_revalidates_cross_section_flags(hr_client, candidate):
    """Q79 changed to Red after Section 7 was saved: Q99 is now required."""
    verification = _fill_everything(hr_client, candidate)
    HRVerification.objects.filter(pk=verification.pk).update(
        answers={**verification.answers, 'risk_rating': 'red'})

    hr_client.post(_url('submit', candidate))

    verification.refresh_from_db()
    assert not verification.is_submitted
    assert [q['key'] for _, q in verification.missing_required()] == [
        'hr_legal_review_completed']


def test_sign_off_ignores_hidden_required_questions(hr_client, candidate):
    verification = _fill_everything(hr_client, candidate)
    keys = [q['key'] for _, q in verification.missing_required()]
    assert 'agency_name' not in keys
    assert 'employer_1_name' not in keys


def test_detail_page_lists_missing_answers(hr_client, candidate):
    verification = _fill_everything(hr_client, candidate)
    HRVerification.objects.filter(pk=verification.pk).update(
        answers={**verification.answers, 'final_signoff_date': ''})
    body = hr_client.get(_url('detail', candidate)).content.decode()
    assert 'Still required before sign-off' in body
    assert 'Final Sign-off Date' in body


def test_a_signed_off_record_ignores_a_posted_section(hr_client, candidate):
    verification = _fill_everything(hr_client, candidate)
    hr_client.post(_url('submit', candidate))
    hr_client.post(_url('step', candidate, step_key='hr_review'),
                   {**HR_REVIEW, 'hr_reviewer_designation': 'TAMPERED'})
    verification.refresh_from_db()
    assert verification.answers['hr_reviewer_designation'] != 'TAMPERED'


def test_sign_off_does_not_clobber_a_concurrent_section_save(hr_client, candidate):
    verification = _fill_everything(hr_client, candidate)
    HRVerification.objects.filter(pk=verification.pk).update(
        answers={**verification.answers, 'discrepancy_summary': 'Other reviewer'})
    hr_client.post(_url('submit', candidate))
    verification.refresh_from_db()
    assert verification.is_submitted
    assert verification.answers['discrepancy_summary'] == 'Other reviewer'


# ── Review page ──────────────────────────────────────────────────────────
def test_review_hides_questions_not_visible_for_the_answers(hr_client, candidate):
    verification = _start(hr_client, candidate)
    verification.answers = {**HR_REVIEW, 'agency_name': 'Ghost Agency Ltd'}
    verification.save()
    body = hr_client.get(_url('detail', candidate)).content.decode()
    assert 'HR Reviewer Designation' in body
    assert 'Ghost Agency Ltd' not in body


def test_review_renders_grids_as_tables(hr_client, candidate):
    verification = _start(hr_client, candidate)
    verification.answers = {**IDENTITY, 'nid_submitted_value': '[PLACEHOLDER-NID]',
                            'nid_method': 'official_source'}
    verification.save()
    body = hr_client.get(_url('detail', candidate)).content.decode()
    assert '<table' in body
    assert 'Identity &amp; Address Verification Record' in body
    assert 'Official Source' in body


def test_review_shows_a_current_employment_period(hr_client, candidate):
    verification = _start(hr_client, candidate)
    verification.answers = {**EMPLOYER_1, 'employer_1_claimed_current': 'yes',
                            'employer_1_claimed_end_date': ''}
    verification.save()
    body = hr_client.get(_url('detail', candidate)).content.decode()
    assert '01 Jan 2020 – Current' in body
    assert 'Candidate-claimed Employment Period' in body


def test_dates_read_as_dates_on_the_review_page(hr_client, candidate):
    _start(hr_client, candidate)
    hr_client.post(_url('step', candidate, step_key='hr_review'), HR_REVIEW)
    body = hr_client.get(_url('detail', candidate)).content.decode()
    assert '01 Aug 2026' in body
    assert '2026-08-01' not in body


def test_an_unparseable_date_still_shows(candidate):
    verification = HRVerification(resume=candidate,
                                  answers={'verification_start_date': 'not a date'})
    question = schema.QUESTIONS_BY_KEY['verification_start_date']
    assert verification.display_value(question) == 'not a date'


LEGACY_ANSWERS = {
    'agency_required': 'yes',
    'nid_verified': 'yes',
    'masters_discrepancy': 'yes',
    'masters_verified': 'no',
    'employer_1_name': 'Acme Ltd',
    'employer_1_hr_email': 'hr@acme.example',
    'employer_1_reference_check_verified': 'yes',
    'police_verification_route': 'not_required',
    'highest_degree': 'masters',
    'hsc_passing_year': 2014,
    'pending_document_at_joining': 'yes',
    'risk_rating': 'green',
}


def test_old_answer_keys_do_not_crash_anything(hr_client, candidate):
    verification = _start(hr_client, candidate)
    verification.answers = dict(LEGACY_ANSWERS)
    verification.completed_steps = ['hr_review', 'identity', 'education', 'employment',
                                    'references', 'clearance']
    verification.save()

    assert hr_client.get(_url('detail', candidate)).status_code == 200
    for step_key in schema.STEP_KEYS:
        assert hr_client.get(_url('step', candidate, step_key=step_key)).status_code == 200
    assert not verification.can_submit
    hr_client.post(_url('submit', candidate))
    verification.refresh_from_db()
    assert not verification.is_submitted
    assert verification.missing_required()


# ── Access control and lifecycle ─────────────────────────────────────────
def test_anonymous_is_sent_to_login(client, candidate):
    HRVerification.objects.create(resume=candidate)
    response = client.get(_url('detail', candidate))
    assert response.status_code == 302
    assert '/login/' in response.url


def test_an_ordinary_recruiter_cannot_open_it(authenticated_client, candidate):
    HRVerification.objects.create(resume=candidate)
    response = authenticated_client.get(_url('detail', candidate))
    assert response.status_code == 302
    assert reverse('core:dashboard') in response.url


def test_a_superuser_counts_as_hr(client, django_user_model, candidate):
    django_user_model.objects.create_superuser(
        username='boss', password='bosspass123', email='boss@example.com')
    client.login(username='boss', password='bosspass123')
    HRVerification.objects.create(resume=candidate)
    assert client.get(_url('detail', candidate)).status_code == 200


def test_an_ordinary_recruiter_does_not_see_the_hr_card(authenticated_client, candidate):
    body = authenticated_client.get(
        reverse('core:resume_detail', kwargs={'uuid': candidate.uuid})).content.decode()
    assert 'HR Background Verification' not in body


def test_hr_sees_the_card(hr_client, candidate):
    body = hr_client.get(
        reverse('core:resume_detail', kwargs={'uuid': candidate.uuid})).content.decode()
    assert 'HR Background Verification' in body


@pytest.mark.parametrize('status', ['interviewing', 'offer_extended', 'hired'])
def test_can_start_from_interviewing_onwards(hr_client, candidate, status):
    candidate.recruiter_status = status
    candidate.save()
    hr_client.post(_url('start', candidate))
    assert HRVerification.objects.filter(resume=candidate).exists()


@pytest.mark.parametrize('status', ['new', 'shortlisted', 'phone_screen'])
def test_cannot_start_before_interviewing(hr_client, candidate, status):
    candidate.recruiter_status = status
    candidate.save()
    hr_client.post(_url('start', candidate))
    assert not HRVerification.objects.filter(resume=candidate).exists()


def test_starting_twice_reuses_the_record(hr_client, candidate):
    first = _start(hr_client, candidate)
    hr_client.post(_url('start', candidate))
    assert HRVerification.objects.get(resume=candidate).pk == first.pk


def test_an_existing_record_survives_a_later_status_change(hr_client, candidate):
    _start(hr_client, candidate)
    candidate.recruiter_status = 'rejected'
    candidate.save()
    assert hr_client.get(_url('detail', candidate)).status_code == 200
    assert hr_client.get(_url('step', candidate, step_key='hr_review')).status_code == 200


def test_an_unstarted_record_is_a_404(hr_client, candidate):
    assert hr_client.get(_url('detail', candidate)).status_code == 404
    assert hr_client.get(_url('step', candidate, step_key='hr_review')).status_code == 404


def test_an_unknown_section_is_a_404(hr_client, candidate):
    _start(hr_client, candidate)
    assert hr_client.get(_url('step', candidate, step_key='section-zz')).status_code == 404


def test_every_section_renders(hr_client, candidate):
    _start(hr_client, candidate)
    for step_key in schema.STEP_KEYS:
        body = hr_client.get(_url('step', candidate, step_key=step_key)).content.decode()
        assert not re.search(r'\bSection [A-F]\b', body), step_key


def test_a_section_saves_on_its_own(hr_client, candidate):
    verification = _start(hr_client, candidate)
    hr_client.post(_url('step', candidate, step_key='hr_review'), HR_REVIEW)
    verification.refresh_from_db()
    assert verification.completed_steps == ['hr_review']
    assert verification.answers['candidate_full_name']
    assert verification.last_saved_by.username == 'hradmin'


def test_an_incomplete_section_is_not_marked_complete(hr_client, candidate):
    verification = _start(hr_client, candidate)
    hr_client.post(_url('step', candidate, step_key='hr_review'),
                   {**HR_REVIEW, 'candidate_full_name': ''})
    verification.refresh_from_db()
    assert not verification.is_step_complete('hr_review')


def test_saving_a_section_keeps_another_section_saved_concurrently(hr_client, candidate):
    verification = _start(hr_client, candidate)
    HRVerification.objects.filter(pk=verification.pk).update(
        answers={'finding_details': 'Recorded by the other reviewer'},
        completed_steps=['findings'])
    hr_client.post(_url('step', candidate, step_key='hr_review'), HR_REVIEW)
    verification.refresh_from_db()
    assert verification.answers['finding_details'] == 'Recorded by the other reviewer'
    assert set(verification.completed_steps) == {'hr_review', 'findings'}


# ── HR-only media ────────────────────────────────────────────────────────
@pytest.fixture
def stored_agency_report(db, candidate, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    (tmp_path / 'resumes').mkdir()
    (tmp_path / 'a' / 'b').mkdir(parents=True)
    verification = HRVerification.objects.create(resume=candidate)
    return HRVerificationFile.objects.create(
        verification=verification, question_key='agency_report_file',
        file=SimpleUploadedFile('report.pdf', PDF, content_type='application/pdf'),
        original_name='report.pdf',
    )


@pytest.mark.parametrize('shape', ['/media/{p}', '/media/resumes/../{p}', '/media/./{p}',
                                   '/media/a/b/../../{p}'])
def test_agency_evidence_resists_a_traversal_dodge(authenticated_client,
                                                   stored_agency_report, shape):
    url = shape.format(p=stored_agency_report.file.name)
    assert authenticated_client.get(url).status_code == 404, url


@pytest.mark.parametrize('shape', ['/media/{p}', '/media/resumes/../{p}'])
def test_hr_can_still_read_the_evidence(hr_client, stored_agency_report, shape):
    assert hr_client.get(shape.format(p=stored_agency_report.file.name)).status_code == 200


def test_candidate_documents_stay_readable_by_recruiters(authenticated_client, settings,
                                                         tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    (tmp_path / 'resumes').mkdir()
    (tmp_path / 'resumes' / 'cv.pdf').write_bytes(PDF)
    assert authenticated_client.get('/media/resumes/cv.pdf').status_code == 200


# ── Section-key migration ────────────────────────────────────────────────
def test_records_saved_before_the_section_rename_are_carried_across(candidate):
    from importlib import import_module

    from django.apps import apps as app_registry

    module = import_module('apps.hr_verification.migrations.0002_rename_section_keys')
    assert set(module.SECTION_KEYS.values()) <= set(schema.STEP_KEYS)

    verification = HRVerification.objects.create(
        resume=candidate,
        completed_steps=['section_a', 'section_b', 'section_c', 'section_d',
                         'section_e', 'section_f'],
        answers={'section_e_completion_date': '2026-07-01'},
    )
    module.forwards(app_registry, None)

    verification.refresh_from_db()
    assert verification.completed_steps == [
        'hr_review', 'identity', 'education', 'employment', 'references', 'clearance']
    assert verification.completed_count == 6
    assert verification.next_unfinished_step == 'findings'
    assert verification.answers['verification_completion_date'] == '2026-07-01'


def test_the_rename_migration_is_reversible(candidate):
    from importlib import import_module

    from django.apps import apps as app_registry

    module = import_module('apps.hr_verification.migrations.0002_rename_section_keys')
    verification = HRVerification.objects.create(
        resume=candidate, completed_steps=['hr_review', 'clearance'],
        answers={'verification_completion_date': '2026-07-01'})
    module.backwards(app_registry, None)
    verification.refresh_from_db()
    assert verification.completed_steps == ['section_a', 'section_f']
    assert verification.answers['section_e_completion_date'] == '2026-07-01'


# ── Found in review ──────────────────────────────────────────────────────
def test_a_hidden_offer_date_does_not_trip_the_date_order_check():
    form = StepForm({**CLEARANCE, 'offer_letter_issued': 'no',
                     'offer_letter_issue_date': '2026-09-30',
                     'offer_accepted': 'yes', 'offer_acceptance_date': '2026-09-01'},
                    step_key='clearance')
    assert form.is_valid(), form.errors


def test_reference_method_is_not_needed_before_contact_is_attempted():
    data = {**REFERENCES, 'reference_2_verification_status': 'not_attempted'}
    del data['reference_2_verification_method']
    assert StepForm(data, step_key='references').is_valid()

    del data['reference_1_verification_method']
    assert 'reference_1_verification_method' in StepForm(data, step_key='references').errors


def test_the_joining_date_is_only_required_when_proceeding_to_join():
    data = dict(CLEARANCE)
    del data['confirmed_joining_date']
    assert 'confirmed_joining_date' in StepForm(data, step_key='clearance').errors

    data['final_joining_clearance'] = 'do_not_proceed'
    data['final_hr_remarks'] = 'Not cleared'
    assert 'confirmed_joining_date' not in StepForm(data, step_key='clearance').errors


def test_an_old_record_still_shows_its_employers_and_old_choice_labels():
    view = schema.legacy_view({'employer_1_name': 'Acme', 'employer_2_name': 'Beta'})
    assert view['has_employment'] == 'yes'
    assert view['employer_1_another'] == 'yes'
    assert is_visible(schema.QUESTIONS_BY_KEY['employer_2_name'], view)
    assert schema.choice_label('police_verification_status', 'not_required') == 'Not Required'


def test_hr_pages_warn_when_the_candidate_declined_consent(client, django_user_model, sample_job):
    django_user_model.objects.create_user(username='hr-consent', password='p', is_staff=True)
    client.login(username='hr-consent', password='p')
    resume = Resume.objects.create(job=sample_job, candidate_name='No Consent',
                                   email='nc@example.com', recruiter_status='interviewing')
    EmployeeForm.objects.create(resume=resume, is_submitted=True,
                                answers={'verification_consent': 'no'})
    HRVerification.objects.create(resume=resume)

    for url in (reverse('hr_verification:detail', kwargs={'uuid': resume.uuid}),
                reverse('hr_verification:step', kwargs={'uuid': resume.uuid,
                                                        'step_key': 'hr_review'})):
        assert 'did not consent to background verification' in client.get(url).content.decode()
