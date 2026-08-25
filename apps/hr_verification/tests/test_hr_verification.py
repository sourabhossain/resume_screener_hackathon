"""The HR-only Background Verification & Joining Clearance form.

Covers who may open it, when it opens, that sections save independently, that
sign-off cannot skip a section, and that the candidate's own answers are carried
across rather than retyped.
"""
import re

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.core.models import Resume
from apps.employee_form.models import EmployeeForm
from apps.hr_verification import schema
from apps.hr_verification.models import HRVerification, HRVerificationFile

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
    return reverse(f'hr_verification:{name}',
                   kwargs={'uuid': resume.uuid, **kwargs})


def _start(hr_client, candidate):
    hr_client.post(_url('start', candidate))
    return HRVerification.objects.get(resume=candidate)


# A complete Section A, so tests about other things do not fail on this one.
SECTION_A = {
    'candidate_full_name': 'Ayesha Rahman',
    'position_applied_for': 'Senior Python Developer',
    'department': 'engineering',
    'hr_reviewer_name': 'Hasan Rahman',
    'hr_reviewer_designation': 'HR Manager',
    'verification_start_date': '2026-08-01',
    'verification_route': 'internal_hr',
    'agency_required': 'no',
}


# ── Access control ───────────────────────────────────────────────────────
def test_anonymous_is_sent_to_login(client, candidate):
    HRVerification.objects.create(resume=candidate)
    response = client.get(_url('detail', candidate))
    assert response.status_code == 302
    assert '/login/' in response.url


def test_an_ordinary_recruiter_cannot_open_it(authenticated_client, candidate):
    """A recruiter is not HR: this record holds police and adverse findings."""
    HRVerification.objects.create(resume=candidate)
    response = authenticated_client.get(_url('detail', candidate))
    assert response.status_code == 302
    assert reverse('core:dashboard') in response.url


def test_hr_staff_can_open_it(hr_client, candidate):
    HRVerification.objects.create(resume=candidate)
    assert hr_client.get(_url('detail', candidate)).status_code == 200


def test_a_superuser_counts_as_hr(client, django_user_model, candidate):
    django_user_model.objects.create_superuser(
        username='boss', password='bosspass123', email='boss@example.com')
    client.login(username='boss', password='bosspass123')
    HRVerification.objects.create(resume=candidate)
    assert client.get(_url('detail', candidate)).status_code == 200


def test_an_ordinary_recruiter_does_not_see_the_hr_card(authenticated_client, candidate):
    body = authenticated_client.get(
        reverse('core:resume_detail', kwargs={'uuid': candidate.uuid})
    ).content.decode()
    assert 'HR Background Verification' not in body


def test_hr_sees_the_card(hr_client, candidate):
    body = hr_client.get(
        reverse('core:resume_detail', kwargs={'uuid': candidate.uuid})
    ).content.decode()
    assert 'HR Background Verification' in body


def test_agency_evidence_is_not_served_to_a_recruiter(authenticated_client):
    """The uploads live under a path only HR may read."""
    response = authenticated_client.get('/media/hr_verifications/1/abc/report.pdf')
    assert response.status_code == 404


# ── When it opens ────────────────────────────────────────────────────────
@pytest.mark.parametrize('status', ['interviewing', 'offer_extended', 'hired'])
def test_can_start_from_interviewing_onwards(hr_client, candidate, status):
    """Section F is about offer and joining, so the gate stays open past
    interviewing -- otherwise moving the candidate on would lock HR out of it."""
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
    assert HRVerification.objects.filter(resume=candidate).count() == 1
    assert HRVerification.objects.get(resume=candidate).pk == first.pk


def test_an_existing_record_survives_a_later_status_change(hr_client, candidate):
    """Findings already collected must not become unreachable because someone
    moved the candidate to Rejected -- that is the record the decision rests on."""
    _start(hr_client, candidate)
    candidate.recruiter_status = 'rejected'
    candidate.save()

    assert hr_client.get(_url('detail', candidate)).status_code == 200
    assert hr_client.get(
        _url('step', candidate, step_key='hr_review')).status_code == 200


def test_an_unstarted_record_is_a_404_not_a_blank_form(hr_client, candidate):
    assert hr_client.get(_url('detail', candidate)).status_code == 404
    assert hr_client.get(
        _url('step', candidate, step_key='hr_review')).status_code == 404


def test_an_unknown_section_is_a_404(hr_client, candidate):
    _start(hr_client, candidate)
    assert hr_client.get(
        _url('step', candidate, step_key='section-zz')).status_code == 404


# ── Saving sections ──────────────────────────────────────────────────────
def test_a_section_saves_on_its_own(hr_client, candidate):
    verification = _start(hr_client, candidate)

    hr_client.post(_url('step', candidate, step_key='hr_review'), SECTION_A)

    verification.refresh_from_db()
    assert verification.is_step_complete('hr_review')
    assert verification.completed_count == 1
    assert verification.answers['hr_reviewer_designation'] == 'HR Manager'
    assert verification.last_saved_by.username == 'hradmin'


def test_an_incomplete_section_is_not_marked_complete(hr_client, candidate):
    verification = _start(hr_client, candidate)

    hr_client.post(_url('step', candidate, step_key='hr_review'),
                   {**SECTION_A, 'hr_reviewer_designation': ''})

    verification.refresh_from_db()
    assert not verification.is_step_complete('hr_review')


def test_sections_can_be_filled_in_any_order(hr_client, candidate):
    """HR fills these as the information arrives, not front to back."""
    verification = _start(hr_client, candidate)

    assert hr_client.get(
        _url('step', candidate, step_key='clearance')).status_code == 200
    hr_client.post(_url('step', candidate, step_key='hr_review'), SECTION_A)

    verification.refresh_from_db()
    assert verification.completed_steps == ['hr_review']


def test_an_uploaded_agency_report_is_stored(hr_client, candidate):
    verification = _start(hr_client, candidate)

    hr_client.post(_url('step', candidate, step_key='hr_review'),
                   {**SECTION_A, 'agency_report_file': _pdf()})

    verification.refresh_from_db()
    stored = verification.files.get(question_key='agency_report_file')
    assert stored.original_name == 'report.pdf'
    assert stored.uploaded_by.username == 'hradmin'


def test_a_future_verification_date_is_rejected(hr_client, candidate):
    verification = _start(hr_client, candidate)

    hr_client.post(_url('step', candidate, step_key='hr_review'),
                   {**SECTION_A, 'verification_start_date': '2099-01-01'})

    verification.refresh_from_db()
    assert not verification.is_step_complete('hr_review')


# ── Employer blocks ──────────────────────────────────────────────────────
def test_an_unnamed_employer_block_is_skippable(hr_client, candidate):
    """A candidate with no previous job must not make Section D unsubmittable."""
    verification = _start(hr_client, candidate)

    hr_client.post(_url('step', candidate, step_key='employment'), {})

    verification.refresh_from_db()
    assert verification.is_step_complete('employment')


def test_naming_an_employer_makes_its_block_required(hr_client, candidate):
    verification = _start(hr_client, candidate)

    hr_client.post(_url('step', candidate, step_key='employment'),
                   {'employer_1_name': 'Acme Ltd'})

    verification.refresh_from_db()
    assert not verification.is_step_complete('employment')


def test_a_confirmed_end_before_the_start_is_rejected(hr_client, candidate):
    verification = _start(hr_client, candidate)

    hr_client.post(_url('step', candidate, step_key='employment'), {
        'employer_1_name': 'Acme Ltd',
        'employer_1_hr_contact': '+8801711000000',
        'employer_1_hr_email': 'hr@acme.com',
        'employer_1_position': 'Engineer',
        'employer_1_claimed_start_date': '2020-01-01',
        'employer_1_claimed_end_date': '2023-01-01',
        'employer_1_confirmed_start_date': '2023-01-01',
        'employer_1_confirmed_end_date': '2020-01-01',
        'employer_1_reference_check_verified': 'yes',
        'employer_1_verification_status': 'verified',
        'employer_1_verification_method': 'direct_call',
        'employer_1_tenure_discrepancy': 'no',
    })

    verification.refresh_from_db()
    assert not verification.is_step_complete('employment'), (
        'employment ending before it started went into background verification data'
    )


# ── Sign-off ─────────────────────────────────────────────────────────────
def test_sign_off_needs_every_section(hr_client, candidate):
    verification = _start(hr_client, candidate)
    hr_client.post(_url('step', candidate, step_key='hr_review'), SECTION_A)

    hr_client.post(_url('submit', candidate))

    verification.refresh_from_db()
    assert not verification.is_submitted


def test_sign_off_locks_the_record(hr_client, candidate):
    verification = _start(hr_client, candidate)
    verification.completed_steps = list(schema.STEP_KEYS)
    verification.save()

    hr_client.post(_url('submit', candidate))

    verification.refresh_from_db()
    assert verification.is_submitted
    assert verification.submitted_at
    assert verification.submitted_by.username == 'hradmin'

    # Editing is over: the section page sends them to the read-only record.
    response = hr_client.get(_url('step', candidate, step_key='hr_review'))
    assert response.status_code == 302
    assert _url('detail', candidate) in response.url


def test_a_signed_off_record_ignores_a_posted_section(hr_client, candidate):
    verification = _start(hr_client, candidate)
    verification.completed_steps = list(schema.STEP_KEYS)
    verification.save()
    hr_client.post(_url('submit', candidate))

    hr_client.post(_url('step', candidate, step_key='hr_review'),
                   {**SECTION_A, 'hr_reviewer_designation': 'TAMPERED'})

    verification.refresh_from_db()
    assert verification.answers.get('hr_reviewer_designation') != 'TAMPERED'


# ── Prefill from the candidate's own form ────────────────────────────────
@pytest.fixture
def submitted_employee_form(candidate):
    return EmployeeForm.objects.create(
        resume=candidate,
        is_submitted=True,
        answers={
            'candidate_full_name': 'Ayesha Rahman',
            'nid_number': '1234567890',
            'date_of_birth': '1996-04-12',
            'present_address': '12 Road 5, Dhanmondi, Dhaka',
            'permanent_address': '12 Road 5, Dhanmondi, Dhaka',
            'department': 'engineering',
            'highest_degree': 'bachelors',
            'bachelors_institution': 'University of Dhaka',
            'bachelors_degree_name': 'BSc',
            'bachelors_major': 'CSE',
            'hsc_passing_year': 2014,
            'employer_1_name': 'Acme Ltd',
            'employer_1_hr_email': 'hr@acme.com',
            'employer_1_start_date': '2020-01-01',
            'employer_1_end_date': '2023-01-01',
            'employer_1_reason_leaving': 'Better opportunity',
            'reference_1_name': 'Karim Uddin',
            'reference_1_designation': 'CTO, Acme',
        },
    )


def test_candidate_answers_are_carried_across(hr_client, candidate,
                                              submitted_employee_form):
    from apps.hr_verification.prefill import prefill_answers

    values = prefill_answers(candidate)

    assert values['candidate_nid_number'] == '1234567890'
    assert values['candidate_date_of_birth'] == '1996-04-12'
    assert values['candidate_present_address'] == '12 Road 5, Dhanmondi, Dhaka'
    assert values['hsc_passing_year'] == 2014
    # Degree name and major are one field on this form.
    assert values['bachelors_degree_major'] == 'BSc — CSE'
    # Employer numbers must line up between the two forms.
    assert values['employer_1_name'] == 'Acme Ltd'
    assert values['employer_1_claimed_start_date'] == '2020-01-01'
    assert values['employer_1_claimed_reason_leaving'] == 'Better opportunity'
    assert values['reference_1_name'] == 'Karim Uddin'


def test_hr_findings_are_never_prefilled(hr_client, candidate,
                                         submitted_employee_form):
    """A prefilled judgement is a judgement nobody made."""
    from apps.hr_verification.prefill import prefill_answers

    values = prefill_answers(candidate)

    for key in ('nid_verified', 'employer_1_confirmed_start_date',
                'employer_1_verification_status', 'risk_rating',
                'verification_recommendation', 'final_joining_clearance',
                'hr_approver_name', 'police_verification_status'):
        assert key not in values, f'{key} must be HR\'s own finding'


def test_prefill_reaches_the_rendered_form(hr_client, candidate,
                                           submitted_employee_form):
    _start(hr_client, candidate)

    body = hr_client.get(
        _url('step', candidate, step_key='identity')).content.decode()

    assert '1234567890' in body
    assert 'Dhanmondi' in body


def test_prefill_does_not_overwrite_what_hr_typed(hr_client, candidate,
                                                  submitted_employee_form):
    from apps.hr_verification.prefill import pending_prefill

    verification = _start(hr_client, candidate)
    verification.answers = {'candidate_nid_number': '9999999999'}
    verification.save()

    assert 'candidate_nid_number' not in pending_prefill(verification)


def test_prefill_copes_with_no_candidate_form(hr_client, candidate):
    from apps.hr_verification.prefill import prefill_answers

    values = prefill_answers(candidate)

    assert values['candidate_full_name'] == 'Ayesha Rahman'
    assert values['position_applied_for'] == 'Senior Python Developer'


# ── Schema integrity ─────────────────────────────────────────────────────
def test_the_form_matches_the_source_document():
    """Sections A-F, and the PDF's 201 questions less its dropped Requisition ID."""
    assert schema.TOTAL_STEPS == 6
    assert len(schema.QUESTIONS_BY_KEY) == 200
    assert 'requisition_id' not in schema.QUESTIONS_BY_KEY
    keys = [q['key'] for step in schema.STEPS for q in step['questions']]
    assert len(keys) == len(set(keys)), 'duplicate question key'


def test_every_question_renders_in_a_titled_block():
    """An ungrouped question falls into a trailing untitled block; none should."""
    for step_key in schema.STEP_KEYS:
        blocks = schema.question_groups(step_key)
        grouped = {q['key'] for b in blocks for q in b['questions']}
        assert grouped == {q['key'] for q in schema.questions(step_key)}
        assert all(b['title'] for b in blocks), f'{step_key} has an untitled block'


def test_item_numbers_are_not_shown(hr_client, candidate):
    """They read as a broken sequence once blank rows are hidden: 8, then 14."""
    _start(hr_client, candidate)
    hr_client.post(_url('step', candidate, step_key='hr_review'), SECTION_A)

    body = hr_client.get(_url('detail', candidate)).content.decode()

    assert 'HR Reviewer Designation' in body
    assert not re.search(r'>\s*\d+\.\s*</span>', body)
    assert not hasattr(schema, 'QUESTION_NUMBERS')


def test_every_section_renders_for_hr(hr_client, candidate):
    _start(hr_client, candidate)
    for step_key in schema.STEP_KEYS:
        response = hr_client.get(_url('step', candidate, step_key=step_key))
        assert response.status_code == 200, step_key


# ── Regressions found reviewing this app ─────────────────────────────────
@pytest.fixture
def stored_agency_report(db, candidate, settings, tmp_path):
    """A real file on disk under the HR-only media directory.

    `resumes/` is created too: without it a /media/resumes/../hr_verifications/
    request 404s on the missing directory rather than on the gate, which would
    make the traversal test below pass for the wrong reason.
    """
    settings.MEDIA_ROOT = str(tmp_path)
    (tmp_path / 'resumes').mkdir()
    (tmp_path / 'a' / 'b').mkdir(parents=True)
    verification = HRVerification.objects.create(resume=candidate)
    upload = HRVerificationFile.objects.create(
        verification=verification, question_key='agency_report_file',
        file=SimpleUploadedFile('report.pdf', PDF, content_type='application/pdf'),
        original_name='report.pdf',
    )
    return upload


@pytest.mark.parametrize('shape', [
    '/media/{p}',
    '/media/resumes/../{p}',
    '/media/./{p}',
    '/media/a/b/../../{p}',
])
def test_agency_evidence_resists_a_traversal_dodge(authenticated_client,
                                                   stored_agency_report, shape):
    """The gate has to test the resolved path.

    /media/resumes/../hr_verifications/... names the same file, so a check
    against the requested URL alone would hand every recruiter the police and
    agency paperwork.
    """
    url = shape.format(p=stored_agency_report.file.name)

    assert authenticated_client.get(url).status_code == 404, url


@pytest.mark.parametrize('shape', ['/media/{p}', '/media/resumes/../{p}'])
def test_hr_can_still_read_the_evidence(hr_client, stored_agency_report, shape):
    response = hr_client.get(shape.format(p=stored_agency_report.file.name))
    assert response.status_code == 200


def test_candidate_documents_stay_readable_by_recruiters(authenticated_client,
                                                         settings, tmp_path):
    """Only the HR directory is gated; the rest of media is unchanged."""
    settings.MEDIA_ROOT = str(tmp_path)
    (tmp_path / 'resumes').mkdir()
    (tmp_path / 'resumes' / 'cv.pdf').write_bytes(PDF)

    assert authenticated_client.get('/media/resumes/cv.pdf').status_code == 200


def _named_employer(**overrides):
    return {
        'employer_1_name': 'Acme Ltd',
        'employer_1_hr_contact': '+8801711000000',
        'employer_1_hr_email': 'hr@acme.com',
        'employer_1_position': 'Engineer',
        'employer_1_claimed_start_date': '2020-01-01',
        'employer_1_claimed_end_date': '2023-01-01',
        'employer_1_reference_check_verified': 'no',
        'employer_1_verification_status': 'unable',
        'employer_1_verification_method': 'direct_call',
        'employer_1_tenure_discrepancy': 'no',
        **overrides,
    }


def test_an_employer_who_would_not_confirm_can_still_be_recorded(hr_client, candidate):
    """"Unable to Verify" is an outcome the form offers, so it must be saveable.

    Requiring the employer's confirmed dates made Section D unsaveable, and
    because sign-off needs every section the whole verification deadlocked.
    """
    verification = _start(hr_client, candidate)

    hr_client.post(_url('step', candidate, step_key='employment'), _named_employer())

    verification.refresh_from_db()
    assert verification.is_step_complete('employment'), (
        'an employer who would not disclose dates blocked the whole verification'
    )


def test_confirmed_dates_are_still_checked_when_given(hr_client, candidate):
    verification = _start(hr_client, candidate)

    hr_client.post(_url('step', candidate, step_key='employment'), _named_employer(
        employer_1_confirmed_start_date='2023-01-01',
        employer_1_confirmed_end_date='2020-01-01',
    ))

    verification.refresh_from_db()
    assert not verification.is_step_complete('employment')


def test_a_badly_formatted_field_is_not_also_called_missing(candidate):
    """One filled field must not collect two contradictory errors."""
    from apps.hr_verification.forms import StepForm

    form = StepForm(_named_employer(employer_1_hr_contact='call me maybe'), {},
                    step_key='employment')
    assert not form.is_valid()

    errors = form.errors['employer_1_hr_contact']
    assert len(errors) == 1, errors
    assert 'Required once' not in ' '.join(errors)


def test_saving_a_section_keeps_another_section_saved_concurrently(hr_client,
                                                                   candidate):
    """Two HR users, two sections, one answers blob -- neither may lose the other."""
    verification = _start(hr_client, candidate)

    # Stand in for the other user's save landing after this request read the row.
    stale = HRVerification.objects.get(pk=verification.pk)
    HRVerification.objects.filter(pk=verification.pk).update(
        answers={'finding_details': 'Recorded by the other reviewer'},
        completed_steps=['references'],
    )
    assert stale.answers == {}

    hr_client.post(_url('step', candidate, step_key='hr_review'), SECTION_A)

    verification.refresh_from_db()
    assert verification.answers['finding_details'] == 'Recorded by the other reviewer'
    assert verification.answers['hr_reviewer_designation'] == 'HR Manager'
    assert set(verification.completed_steps) == {'hr_review', 'references'}


def test_hr_does_not_see_the_candidate_facing_prefill_badge(hr_client, candidate,
                                                            submitted_employee_form):
    _start(hr_client, candidate)

    body = hr_client.get(
        _url('step', candidate, step_key='identity')).content.decode()

    assert 'matches your documents' not in body


# ── Presentation rules ───────────────────────────────────────────────────
def _all_visible_text():
    """Everything on this form a person actually reads."""
    for step in schema.STEPS:
        yield step['section']
        yield step['title']
        yield step.get('description', '')
        for question in step['questions']:
            yield question['label']
            yield question.get('help', '')
            for _, label in question.get('choices', []):
                yield label


def test_no_section_letters_are_shown_to_anyone():
    """"Section A", "Save Section F" and friends mean nothing to a reader."""
    import re
    offenders = [t for t in _all_visible_text()
                 if re.search(r'\bSection [A-F]\b', t)]
    assert not offenders, offenders


def test_step_keys_are_named_not_lettered():
    """The keys show up in the URL, so they read as names too."""
    assert schema.STEP_KEYS == [
        'hr_review', 'identity', 'education', 'employment',
        'references', 'clearance',
    ]


def test_every_single_choice_question_is_a_dropdown():
    """Radio lists for 90 pick-one questions ran to screens of unread options."""
    radios = [q['key'] for step in schema.STEPS for q in step['questions']
              if q['type'] == schema.RADIO]
    assert not radios, radios

    dropdowns = [q for step in schema.STEPS for q in step['questions']
                 if q['type'] == schema.SELECT]
    assert len(dropdowns) > 80, len(dropdowns)
    assert all(q.get('choices') for q in dropdowns)


def test_dropdowns_render_as_select_elements(hr_client, candidate):
    _start(hr_client, candidate)

    body = hr_client.get(_url('step', candidate, step_key='identity')).content.decode()

    assert '<select' in body
    assert 'name="nid_verified"' in body
    # The old radio markup for the same question must be gone.
    assert 'type="radio" name="nid_verified"' not in body


def test_no_page_shows_a_section_letter(hr_client, candidate):
    _start(hr_client, candidate)
    import re

    for step_key in schema.STEP_KEYS:
        body = hr_client.get(_url('step', candidate, step_key=step_key)).content.decode()
        assert not re.search(r'\bSection [A-F]\b', body), step_key

    body = hr_client.get(_url('detail', candidate)).content.decode()
    assert not re.search(r'\bSection [A-F]\b', body)


def test_a_numeric_zero_counts_as_answered(hr_client, candidate):
    """The review page used `{% if row.value %}`, which hides a 0.

    No question on this form can legitimately be 0 today, so this guards the
    shared helper rather than a live case -- add one numeric question and the
    row would otherwise vanish silently.
    """
    verification = _start(hr_client, candidate)
    question = schema.QUESTIONS_BY_KEY['hsc_passing_year']
    verification.answers = {'hsc_passing_year': 0}

    assert verification._is_answered(question, {}) is True
    assert verification._is_answered(
        schema.QUESTIONS_BY_KEY['identity_police_remarks'], {}) is False


def test_sign_off_does_not_clobber_a_concurrent_section_save(hr_client, candidate):
    verification = _start(hr_client, candidate)
    verification.completed_steps = list(schema.STEP_KEYS)
    verification.save()
    HRVerification.objects.filter(pk=verification.pk).update(
        answers={'finding_details': 'Recorded by the other reviewer'})

    hr_client.post(_url('submit', candidate))

    verification.refresh_from_db()
    assert verification.is_submitted
    assert verification.answers['finding_details'] == 'Recorded by the other reviewer'


def test_records_saved_before_the_section_rename_are_carried_across(candidate):
    """Without the remap a record saved earlier reads as "Not started"."""
    from importlib import import_module

    from django.apps import apps as app_registry

    module = import_module(
        'apps.hr_verification.migrations.0002_rename_section_keys')
    assert set(module.SECTION_KEYS.values()) == set(schema.STEP_KEYS)

    # A row as it was stored before the rename.
    verification = HRVerification.objects.create(
        resume=candidate,
        completed_steps=['section_a', 'section_b', 'section_c',
                         'section_d', 'section_e', 'section_f'],
        answers={'section_e_completion_date': '2026-07-01',
                 'hr_reviewer_name': 'Hasan Rahman'},
    )
    assert verification.completed_count == 0, 'precondition: old keys do not count'
    assert not verification.can_submit

    module.forwards(app_registry, None)

    verification.refresh_from_db()
    assert verification.completed_steps == schema.STEP_KEYS
    assert verification.completed_count == 6
    assert verification.can_submit
    assert verification.answers['verification_completion_date'] == '2026-07-01'
    assert 'section_e_completion_date' not in verification.answers
    assert verification.answers['hr_reviewer_name'] == 'Hasan Rahman'


def test_the_rename_migration_is_reversible(candidate):
    from importlib import import_module

    from django.apps import apps as app_registry

    module = import_module(
        'apps.hr_verification.migrations.0002_rename_section_keys')
    verification = HRVerification.objects.create(
        resume=candidate, completed_steps=['hr_review', 'clearance'],
        answers={'verification_completion_date': '2026-07-01'},
    )

    module.backwards(app_registry, None)

    verification.refresh_from_db()
    assert verification.completed_steps == ['section_a', 'section_f']
    assert verification.answers['section_e_completion_date'] == '2026-07-01'


def test_dates_read_as_dates_on_the_review_page(hr_client, candidate):
    """Answers are JSON, so a date comes back as '2026-08-25' unless formatted."""
    verification = _start(hr_client, candidate)
    hr_client.post(_url('step', candidate, step_key='hr_review'), SECTION_A)

    body = hr_client.get(_url('detail', candidate)).content.decode()

    assert '01 Aug 2026' in body
    assert '2026-08-01' not in body


def test_an_unparseable_date_still_shows(candidate):
    """A hand-edited or older value must render, not raise."""
    verification = HRVerification(
        resume=candidate, answers={'verification_start_date': 'not a date'})
    question = schema.QUESTIONS_BY_KEY['verification_start_date']

    assert verification.display_value(question) == 'not a date'
