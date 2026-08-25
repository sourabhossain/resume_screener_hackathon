"""The HR-only Candidate Mapping & Assessment Document.

Covers who may open it, when it opens, that sections save independently, that
"Yes (describe below)" actually demands the description, and that the assessor
declaration is signed and dated by the server.
"""
import re

import pytest
from django.urls import reverse

from apps.core.models import Resume
from apps.candidate_mapping import schema
from apps.candidate_mapping.models import CandidateMapping
from apps.employee_form.models import EmployeeForm
from apps.employee_form.tests.helpers import SIGNATURE_DATA_URL, signature_upload


@pytest.fixture
def candidate(db, sample_job):
    return Resume.objects.create(
        job=sample_job,
        candidate_name='Ayesha Rahman',
        email='ayesha@example.com',
        recruiter_status='interviewing',
    )


@pytest.fixture
def hr_user(db, django_user_model):
    return django_user_model.objects.create_user(
        username='assessor', password='hrpass123', email='hr@example.com',
        first_name='Hasan', last_name='Rahman', is_staff=True,
    )


@pytest.fixture
def hr_client(client, hr_user):
    client.login(username='assessor', password='hrpass123')
    return client


def _url(name, resume, **kwargs):
    return reverse(f'candidate_mapping:{name}',
                   kwargs={'uuid': resume.uuid, **kwargs})


def _start(hr_client, candidate):
    hr_client.post(_url('start', candidate))
    return CandidateMapping.objects.get(resume=candidate)


CANDIDATE_SECTION = {
    'candidate_full_name': 'Ayesha Rahman',
    'position_applied_for': 'Senior Python Developer',
    'entity': 'ssl_wireless',
    'department': 'engineering',
    'assessed_by': 'Hasan Rahman, HR Manager',
    'date_of_assessment': '2026-08-01',
}

RISK_SECTION = {
    'reasons_for_leaving': 'Career growth',
    'adverse_record': 'none_known',
    'performance_concerns': 'none_known',
    'integrity_issues': 'none_known',
    'separation_type': 'resigned',
    'short_tenure_pattern': 'no',
    'serving_notice': 'no',
}

SUMMARY_SECTION = {
    'suitability_summary': 'Strong fit; some gaps in cloud exposure.',
    'mapping_outcome': 'recommended',
    'assessor_name_designation': 'Hasan Rahman, HR Manager',
    'assessor_signature_drawn': SIGNATURE_DATA_URL,
}


# ── Access control ───────────────────────────────────────────────────────
def test_anonymous_is_sent_to_login(client, candidate):
    CandidateMapping.objects.create(resume=candidate)
    response = client.get(_url('detail', candidate))
    assert response.status_code == 302
    assert '/login/' in response.url


def test_an_ordinary_recruiter_cannot_open_it(authenticated_client, candidate):
    """"Confidential — HR Use Only", and it records adverse findings."""
    CandidateMapping.objects.create(resume=candidate)
    response = authenticated_client.get(_url('detail', candidate))
    assert response.status_code == 302
    assert reverse('core:dashboard') in response.url


def test_hr_staff_can_open_it(hr_client, candidate):
    CandidateMapping.objects.create(resume=candidate)
    assert hr_client.get(_url('detail', candidate)).status_code == 200


def test_an_ordinary_recruiter_does_not_see_the_card(authenticated_client, candidate):
    body = authenticated_client.get(
        reverse('core:resume_detail', kwargs={'uuid': candidate.uuid})
    ).content.decode()
    assert 'Candidate Mapping' not in body


def test_hr_sees_the_card_after_the_verification_one(hr_client, candidate):
    body = hr_client.get(
        reverse('core:resume_detail', kwargs={'uuid': candidate.uuid})
    ).content.decode()
    assert 'HR Background Verification' in body
    assert 'Candidate Mapping' in body
    assert body.index('HR Background Verification') < body.index('Candidate Mapping')


def test_the_signature_is_not_served_to_a_recruiter(authenticated_client):
    """Assessor signatures live under the HR-only media directory."""
    response = authenticated_client.get(
        '/media/hr_verifications/candidate_mappings/1/abc/signature.png')
    assert response.status_code == 404


# ── When it opens ────────────────────────────────────────────────────────
@pytest.mark.parametrize('status', ['interviewing', 'offer_extended', 'hired'])
def test_can_start_from_interviewing_onwards(hr_client, candidate, status):
    candidate.recruiter_status = status
    candidate.save()

    hr_client.post(_url('start', candidate))

    assert CandidateMapping.objects.filter(resume=candidate).exists()


@pytest.mark.parametrize('status', ['new', 'shortlisted', 'phone_screen'])
def test_cannot_start_before_interviewing(hr_client, candidate, status):
    candidate.recruiter_status = status
    candidate.save()

    hr_client.post(_url('start', candidate))

    assert not CandidateMapping.objects.filter(resume=candidate).exists()


def test_it_does_not_wait_for_the_hr_verification(hr_client, candidate):
    """The mapping comes off the CV and interview, so it does not queue behind
    the background check -- either can be in progress while the other is not."""
    assert not hasattr(candidate, 'hr_verification')

    _start(hr_client, candidate)

    assert CandidateMapping.objects.filter(resume=candidate).exists()


def test_starting_twice_reuses_the_record(hr_client, candidate):
    first = _start(hr_client, candidate)
    hr_client.post(_url('start', candidate))
    assert CandidateMapping.objects.filter(resume=candidate).count() == 1
    assert CandidateMapping.objects.get(resume=candidate).pk == first.pk


def test_an_unstarted_record_is_a_404(hr_client, candidate):
    assert hr_client.get(_url('detail', candidate)).status_code == 404
    assert hr_client.get(
        _url('step', candidate, step_key='candidate')).status_code == 404


def test_an_unknown_section_is_a_404(hr_client, candidate):
    _start(hr_client, candidate)
    assert hr_client.get(
        _url('step', candidate, step_key='nope')).status_code == 404


# ── Saving sections ──────────────────────────────────────────────────────
def test_a_section_saves_on_its_own(hr_client, candidate):
    mapping = _start(hr_client, candidate)

    hr_client.post(_url('step', candidate, step_key='candidate'), CANDIDATE_SECTION)

    mapping.refresh_from_db()
    assert mapping.is_step_complete('candidate')
    assert mapping.answers['entity'] == 'ssl_wireless'
    assert mapping.last_saved_by.username == 'assessor'


def test_sections_can_be_filled_in_any_order(hr_client, candidate):
    mapping = _start(hr_client, candidate)

    hr_client.post(_url('step', candidate, step_key='risk'), RISK_SECTION)

    mapping.refresh_from_db()
    assert mapping.completed_steps == ['risk']


def test_every_section_renders(hr_client, candidate):
    _start(hr_client, candidate)
    for step_key in schema.STEP_KEYS:
        assert hr_client.get(
            _url('step', candidate, step_key=step_key)).status_code == 200, step_key


def test_a_future_assessment_date_is_rejected(hr_client, candidate):
    mapping = _start(hr_client, candidate)

    hr_client.post(_url('step', candidate, step_key='candidate'),
                   {**CANDIDATE_SECTION, 'date_of_assessment': '2099-01-01'})

    mapping.refresh_from_db()
    assert not mapping.is_step_complete('candidate')


def test_a_multi_select_stores_every_choice(hr_client, candidate):
    mapping = _start(hr_client, candidate)

    hr_client.post(_url('step', candidate, step_key='reporting'), {
        'reporting_head': 'Karim Uddin, VP',
        'reporting_head_manager': 'CEO',
        'direct_reportees': 'Four engineers',
        'org_structure': 'Flat, three layers',
        'reporting_types': ['sales', 'operational', 'performance'],
    })

    mapping.refresh_from_db()
    assert mapping.answers['reporting_types'] == ['sales', 'operational', 'performance']


# ── "Yes (describe below)" must come with the description ────────────────
@pytest.mark.parametrize('trigger,detail', [
    ('adverse_record', 'adverse_record_details'),
    ('performance_concerns', 'performance_concerns_details'),
    ('integrity_issues', 'integrity_issues_details'),
])
def test_a_yes_without_the_description_is_rejected(hr_client, candidate,
                                                   trigger, detail):
    """A recorded risk with no detail cannot be acted on by anyone downstream."""
    mapping = _start(hr_client, candidate)

    hr_client.post(_url('step', candidate, step_key='risk'),
                   {**RISK_SECTION, trigger: 'yes'})

    mapping.refresh_from_db()
    assert not mapping.is_step_complete('risk'), f'{trigger}=yes saved with no {detail}'


@pytest.mark.parametrize('trigger,detail,value', [
    ('adverse_record', 'adverse_record_details', 'Dismissed for cause in 2021'),
    ('short_tenure_pattern', 'short_tenure_details', 'Three roles in two years'),
    ('serving_notice', 'notice_period_months', '2'),
])
def test_a_yes_with_the_description_saves(hr_client, candidate, trigger, detail, value):
    mapping = _start(hr_client, candidate)

    hr_client.post(_url('step', candidate, step_key='risk'),
                   {**RISK_SECTION, trigger: 'yes', detail: value})

    mapping.refresh_from_db()
    assert mapping.is_step_complete('risk'), mapping.answers


def test_none_known_needs_no_description(hr_client, candidate):
    mapping = _start(hr_client, candidate)

    hr_client.post(_url('step', candidate, step_key='risk'), RISK_SECTION)

    mapping.refresh_from_db()
    assert mapping.is_step_complete('risk')


def test_unable_to_verify_needs_no_description(hr_client, candidate):
    """"Unable to verify" says the check was attempted; there is nothing to describe."""
    mapping = _start(hr_client, candidate)

    hr_client.post(_url('step', candidate, step_key='risk'),
                   {**RISK_SECTION, 'adverse_record': 'unable'})

    mapping.refresh_from_db()
    assert mapping.is_step_complete('risk')


def test_other_customer_segment_needs_specifying(hr_client, candidate):
    mapping = _start(hr_client, candidate)
    base = {
        'customer_types': 'Banks and MFS providers',
        'portfolio_scale': '40 accounts',
        'products_services': 'Payment gateway',
    }

    hr_client.post(_url('step', candidate, step_key='customers'),
                   {**base, 'customer_segments': ['other']})
    mapping.refresh_from_db()
    assert not mapping.is_step_complete('customers')

    hr_client.post(_url('step', candidate, step_key='customers'),
                   {**base, 'customer_segments': ['other'],
                    'customer_segment_other': 'Development partners'})
    mapping.refresh_from_db()
    assert mapping.is_step_complete('customers')


def test_a_named_segment_needs_no_specifying(hr_client, candidate):
    mapping = _start(hr_client, candidate)

    hr_client.post(_url('step', candidate, step_key='customers'), {
        'customer_types': 'Banks', 'portfolio_scale': '40 accounts',
        'products_services': 'Payment gateway', 'customer_segments': ['b2b'],
    })

    mapping.refresh_from_db()
    assert mapping.is_step_complete('customers')


# ── Assessor declaration ─────────────────────────────────────────────────
def test_the_declaration_needs_a_signature(hr_client, candidate):
    mapping = _start(hr_client, candidate)
    unsigned = {k: v for k, v in SUMMARY_SECTION.items()
                if k != 'assessor_signature_drawn'}

    hr_client.post(_url('step', candidate, step_key='summary'), unsigned)

    mapping.refresh_from_db()
    assert not mapping.is_step_complete('summary')


def test_a_drawn_signature_is_stored_as_a_png(hr_client, candidate):
    mapping = _start(hr_client, candidate)

    hr_client.post(_url('step', candidate, step_key='summary'), SUMMARY_SECTION)

    mapping.refresh_from_db()
    stored = mapping.files.get(question_key='assessor_signature')
    assert stored.file.name.endswith('.png')
    assert 'assessor_signature' not in mapping.answers


def test_an_uploaded_signature_is_accepted(hr_client, candidate):
    mapping = _start(hr_client, candidate)
    data = {k: v for k, v in SUMMARY_SECTION.items()
            if k != 'assessor_signature_drawn'}

    hr_client.post(_url('step', candidate, step_key='summary'),
                   {**data, 'assessor_signature': signature_upload()})

    mapping.refresh_from_db()
    assert mapping.is_step_complete('summary')
    assert mapping.files.filter(question_key='assessor_signature').exists()


def test_a_tampered_drawing_is_rejected(hr_client, candidate):
    mapping = _start(hr_client, candidate)

    hr_client.post(_url('step', candidate, step_key='summary'),
                   {**SUMMARY_SECTION,
                    'assessor_signature_drawn': 'data:text/html;base64,AAAA'})

    mapping.refresh_from_db()
    assert not mapping.is_step_complete('summary')


def test_the_declaration_date_is_not_the_assessors_to_set():
    """Dropped from the form; taken from submitted_at so it cannot be backdated."""
    assert 'declaration_date' not in schema.QUESTIONS_BY_KEY


# ── Sign-off ─────────────────────────────────────────────────────────────
def test_sign_off_needs_every_section(hr_client, candidate):
    mapping = _start(hr_client, candidate)
    hr_client.post(_url('step', candidate, step_key='candidate'), CANDIDATE_SECTION)

    hr_client.post(_url('submit', candidate))

    mapping.refresh_from_db()
    assert not mapping.is_submitted


def test_sign_off_locks_and_dates_the_record(hr_client, candidate):
    mapping = _start(hr_client, candidate)
    mapping.completed_steps = list(schema.STEP_KEYS)
    mapping.save()

    hr_client.post(_url('submit', candidate))

    mapping.refresh_from_db()
    assert mapping.is_submitted
    assert mapping.submitted_at
    assert mapping.submitted_by.username == 'assessor'

    response = hr_client.get(_url('step', candidate, step_key='candidate'))
    assert response.status_code == 302
    assert _url('detail', candidate) in response.url


def test_a_signed_off_record_ignores_a_posted_section(hr_client, candidate):
    mapping = _start(hr_client, candidate)
    mapping.completed_steps = list(schema.STEP_KEYS)
    mapping.save()
    hr_client.post(_url('submit', candidate))

    hr_client.post(_url('step', candidate, step_key='candidate'),
                   {**CANDIDATE_SECTION, 'assessed_by': 'TAMPERED'})

    mapping.refresh_from_db()
    assert mapping.answers.get('assessed_by') != 'TAMPERED'


def test_saving_keeps_another_section_saved_concurrently(hr_client, candidate):
    """Two assessors, two sections, one answers blob."""
    mapping = _start(hr_client, candidate)
    CandidateMapping.objects.filter(pk=mapping.pk).update(
        answers={'suitability_summary': 'Written by the other assessor'},
        completed_steps=['summary'],
    )

    hr_client.post(_url('step', candidate, step_key='candidate'), CANDIDATE_SECTION)

    mapping.refresh_from_db()
    assert mapping.answers['suitability_summary'] == 'Written by the other assessor'
    assert mapping.answers['entity'] == 'ssl_wireless'
    assert set(mapping.completed_steps) == {'candidate', 'summary'}


# ── Prefill ──────────────────────────────────────────────────────────────
def test_identification_is_prefilled_but_findings_are_not(hr_client, candidate,
                                                          hr_user):
    from apps.candidate_mapping.prefill import prefill_answers

    EmployeeForm.objects.create(resume=candidate, answers={
        'candidate_full_name': 'Ayesha Rahman',
        'department': 'engineering',
        'employer_1_reason_leaving': 'Better opportunity',
    })

    values = prefill_answers(candidate, user=hr_user)

    assert values['candidate_full_name'] == 'Ayesha Rahman'
    assert values['department'] == 'engineering'
    assert values['assessed_by'] == 'Hasan Rahman'
    assert values['date_of_assessment']
    # Everything the mapping exists to assess stays the assessor's own finding.
    for key in ('team_structure', 'authority_level', 'revenue_volume',
                'adverse_record', 'reasons_for_leaving', 'mapping_outcome',
                'suitability_summary'):
        assert key not in values, key


def test_prefill_does_not_overwrite_what_the_assessor_typed(hr_client, candidate):
    from apps.candidate_mapping.prefill import pending_prefill

    mapping = _start(hr_client, candidate)
    mapping.answers = {'assessed_by': 'Someone Else'}
    mapping.save()

    assert 'assessed_by' not in pending_prefill(mapping)


def test_prefill_copes_with_no_candidate_form(candidate):
    from apps.candidate_mapping.prefill import prefill_answers

    values = prefill_answers(candidate)

    assert values['candidate_full_name'] == 'Ayesha Rahman'
    assert values['position_applied_for'] == 'Senior Python Developer'


# ── Presentation rules ───────────────────────────────────────────────────
def _all_visible_text():
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
    offenders = [t for t in _all_visible_text()
                 if re.search(r'\bSection [A-F]\b', t)]
    assert not offenders, offenders


def test_step_keys_are_named_not_lettered():
    assert schema.STEP_KEYS == [
        'candidate', 'team', 'customers', 'reporting',
        'performance', 'risk', 'summary',
    ]


def test_every_single_choice_question_is_a_dropdown():
    radios = [q['key'] for step in schema.STEPS for q in step['questions']
              if q['type'] == schema.RADIO]
    assert not radios, radios


def test_multi_selects_stay_checkboxes():
    """A dropdown cannot express "select all that apply"."""
    multi = {q['key'] for step in schema.STEPS for q in step['questions']
             if q['type'] == schema.CHECKBOX}
    assert multi == {'customer_segments', 'reporting_types'}


def test_no_page_shows_a_section_letter(hr_client, candidate):
    _start(hr_client, candidate)

    for step_key in schema.STEP_KEYS:
        body = hr_client.get(_url('step', candidate, step_key=step_key)).content.decode()
        assert not re.search(r'\bSection [A-F]\b', body), step_key

    body = hr_client.get(_url('detail', candidate)).content.decode()
    assert not re.search(r'\bSection [A-F]\b', body)


def test_the_verification_safeguard_is_shown_on_the_risk_section(hr_client, candidate):
    """The source document carries it as a callout; so does the page."""
    _start(hr_client, candidate)

    body = hr_client.get(_url('step', candidate, step_key='risk')).content.decode()

    assert 'must not be treated as fact merely on the basis of unverified' in body


def test_the_declaration_wording_is_shown_before_signing(hr_client, candidate):
    _start(hr_client, candidate)

    body = hr_client.get(_url('step', candidate, step_key='summary')).content.decode()

    assert 'prepared objectively' in body


# ── Schema integrity ─────────────────────────────────────────────────────
def test_the_form_covers_the_source_document():
    assert schema.TOTAL_STEPS == 7
    keys = [q['key'] for step in schema.STEPS for q in step['questions']]
    assert len(keys) == len(set(keys)), 'duplicate question key'
    assert 'requisition_id' not in schema.QUESTIONS_BY_KEY


def test_every_question_renders_in_a_titled_block():
    for step_key in schema.STEP_KEYS:
        blocks = schema.question_groups(step_key)
        grouped = {q['key'] for b in blocks for q in b['questions']}
        assert grouped == {q['key'] for q in schema.questions(step_key)}
        assert all(b['title'] for b in blocks), f'{step_key} has an untitled block'


def test_conditional_rules_point_at_real_questions():
    for rule in schema.CONDITIONAL_RULES:
        assert rule['trigger'] in schema.QUESTIONS_BY_KEY, rule['trigger']
        question = schema.QUESTIONS_BY_KEY[rule['trigger']]
        allowed = {value for value, _ in question['choices']}
        assert set(rule['when']) <= allowed, rule
        for key in rule['keys']:
            assert key in schema.QUESTIONS_BY_KEY, key
            # A conditionally-required field must not also be required outright,
            # or the condition would never matter.
            assert not schema.QUESTIONS_BY_KEY[key]['required'], key


def test_required_multi_selects_are_marked_for_the_browser(hr_client, candidate):
    """Django omits `required` on a multi-checkbox (it would demand every box),
    so the page carries data-required-group and base.html checks it instead."""
    _start(hr_client, candidate)

    body = hr_client.get(
        _url('step', candidate, step_key='customers')).content.decode()

    assert 'data-required-group="customer_segments"' in body

    body = hr_client.get(
        _url('step', candidate, step_key='reporting')).content.decode()
    assert 'data-required-group="reporting_types"' in body


def test_an_empty_required_multi_select_is_rejected_server_side(hr_client, candidate):
    """The browser check is a courtesy; this is the one that counts."""
    mapping = _start(hr_client, candidate)

    hr_client.post(_url('step', candidate, step_key='reporting'), {
        'reporting_head': 'Karim Uddin, VP',
        'reporting_head_manager': 'CEO',
        'direct_reportees': 'Four engineers',
        'org_structure': 'Flat',
    })

    mapping.refresh_from_db()
    assert not mapping.is_step_complete('reporting')


def test_item_numbers_are_not_shown(hr_client, candidate):
    """They read as a broken sequence once blank rows are hidden."""
    _start(hr_client, candidate)
    hr_client.post(_url('step', candidate, step_key='candidate'), CANDIDATE_SECTION)

    body = hr_client.get(_url('detail', candidate)).content.decode()

    assert 'Date of Assessment' in body
    assert not re.search(r'>\s*\d+\.\s*</span>', body)
    assert not hasattr(schema, 'QUESTION_NUMBERS')


# ── Regressions found reviewing this app ─────────────────────────────────
def test_a_zero_count_shows_on_the_review_page(hr_client, candidate):
    """An individual contributor has 0 direct reports; that is an answer.

    The review page used `{% if row.value %}`, which dropped the row entirely.
    """
    mapping = _start(hr_client, candidate)
    hr_client.post(_url('step', candidate, step_key='team'), {
        'team_structure': 'Worked inside a squad of six',
        'direct_reports_count': '0',
        'indirect_reports_count': '0',
        'team_functions': 'Payments integration',
        'authority_level': 'Technical decisions within the squad',
    })
    mapping.refresh_from_db()
    assert mapping.answers['direct_reports_count'] == 0

    rows = [r for section in mapping.answered_sections()
            for r in section['rows']
            if r['key'] in ('direct_reports_count', 'indirect_reports_count')]
    assert all(r['answered'] for r in rows), '0 was filed as unanswered'

    body = hr_client.get(_url('detail', candidate)).content.decode()
    assert 'People under direct supervision' in body


def test_the_risk_questions_cannot_be_left_blank(hr_client, candidate):
    """A blank check must not sign off looking like a clean one."""
    mapping = _start(hr_client, candidate)

    hr_client.post(_url('step', candidate, step_key='risk'),
                   {'reasons_for_leaving': 'Career growth'})

    mapping.refresh_from_db()
    assert not mapping.is_step_complete('risk')


def test_an_unassessed_risk_profile_says_so(hr_client, candidate):
    """Before the questions are answered the line must not read "None flagged"."""
    mapping = _start(hr_client, candidate)

    assert mapping.risk_summary == 'Not assessed'
    assert mapping.flagged_findings == []

    hr_client.post(_url('step', candidate, step_key='risk'), RISK_SECTION)
    mapping.refresh_from_db()
    assert mapping.risk_summary == 'None flagged'


def test_involuntary_separation_is_flagged_on_its_own(hr_client, candidate):
    """Every finding clean but "asked to leave" is still a flag."""
    mapping = _start(hr_client, candidate)

    hr_client.post(_url('step', candidate, step_key='risk'),
                   {**RISK_SECTION, 'separation_type': 'terminated'})

    mapping.refresh_from_db()
    assert mapping.flagged_findings == ['Involuntary separation']
    assert mapping.risk_summary == 'Involuntary separation'


def test_sign_off_does_not_clobber_a_concurrent_section_save(hr_client, candidate):
    """submit() used a bare save(), writing back the answers it read earlier."""
    mapping = _start(hr_client, candidate)
    mapping.completed_steps = list(schema.STEP_KEYS)
    mapping.save()
    # Stand in for another assessor's save landing after this request read the row.
    CandidateMapping.objects.filter(pk=mapping.pk).update(
        answers={'suitability_summary': 'Written by the other assessor'})

    hr_client.post(_url('submit', candidate))

    mapping.refresh_from_db()
    assert mapping.is_submitted
    assert mapping.answers['suitability_summary'] == 'Written by the other assessor'


def test_the_sign_off_dialog_names_this_record(hr_client, candidate):
    """Both HR instruments sit on the same resume; the wording said "verification"."""
    mapping = _start(hr_client, candidate)
    mapping.completed_steps = list(schema.STEP_KEYS)
    mapping.save()

    body = hr_client.get(_url('detail', candidate)).content.decode()

    assert 'Sign off this candidate mapping?' in body
    assert 'Sign off this verification?' not in body
