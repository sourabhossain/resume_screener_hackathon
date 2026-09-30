"""Regressions for the form, referee and email gaps found in the full-system review."""
from datetime import timedelta
from unittest import mock

import pytest
from django.core import mail
from django.core.cache import cache
from django.utils import timezone

from apps.core.models import Resume


@pytest.fixture
def candidate(db, sample_job):
    return Resume.objects.create(job=sample_job, candidate_name='Sadia Karim',
                                 email='sadia@example.com', recruiter_status='shortlisted')


# ── employee form ────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_the_invite_task_never_undoes_a_submission(candidate):
    from apps.employee_form.models import EmployeeForm
    from apps.employee_form.tasks import send_employee_form_invite
    form = EmployeeForm.objects.create(resume=candidate)
    real_issue = EmployeeForm.issue_otp

    def submit_meanwhile(self):
        EmployeeForm.objects.filter(pk=self.pk).update(is_submitted=True, answers={'k': 'v'})
        return real_issue(self)

    with mock.patch.object(EmployeeForm, 'issue_otp', submit_meanwhile):
        send_employee_form_invite(form.pk)

    form.refresh_from_db()
    assert form.is_submitted and form.answers == {'k': 'v'}


@pytest.mark.django_db
def test_a_resend_gives_the_candidate_the_full_window_again(candidate):
    from apps.employee_form.models import EmployeeForm
    from apps.employee_form.services import issue_invite
    form = EmployeeForm.objects.create(resume=candidate)
    EmployeeForm.objects.filter(pk=form.pk).update(token_expires_at=timezone.now() + timedelta(hours=2))

    issue_invite(candidate, resend=True)

    form.refresh_from_db()
    assert form.token_expires_at > timezone.now() + timedelta(days=5)


@pytest.mark.django_db
def test_a_double_clicked_resend_sends_once(candidate):
    from apps.employee_form.models import EmployeeForm
    from apps.employee_form.services import InviteError, issue_invite
    EmployeeForm.objects.create(resume=candidate)

    issue_invite(candidate, resend=True)
    with pytest.raises(InviteError, match='a moment ago'):
        issue_invite(candidate, resend=True)


@pytest.mark.django_db
def test_a_down_queue_is_reported_to_the_recruiter_not_a_crash(candidate):
    from apps.employee_form.services import InviteError, issue_invite
    with mock.patch('apps.employee_form.tasks.send_employee_form_invite.delay',
                    side_effect=ConnectionError('down')):
        with pytest.raises(InviteError, match='background queue'):
            issue_invite(candidate)
    from apps.employee_form.models import EmployeeForm
    assert 'queue' in EmployeeForm.objects.get(resume=candidate).last_error


@pytest.mark.django_db
def test_the_candidates_own_resend_does_not_log_them_out(candidate):
    from apps.employee_form.models import EmployeeForm
    from apps.employee_form.services import issue_otp_only
    form = EmployeeForm.objects.create(resume=candidate, otp_verified_at=timezone.now())

    issue_otp_only(form)

    form.refresh_from_db()
    assert form.otp_verified_at is not None


@pytest.mark.django_db
def test_a_file_for_a_hidden_question_is_removed_at_submission(candidate):
    from django.core.files.uploadedfile import SimpleUploadedFile
    from apps.employee_form.models import EmployeeForm, EmployeeFormFile
    form = EmployeeForm.objects.create(resume=candidate, answers={'verification_consent': 'yes'})
    orphan = EmployeeFormFile.objects.create(form=form, question_key='no_such_question',
                                             file=SimpleUploadedFile('x.pdf', b'%PDF-1'))
    kept = EmployeeFormFile.objects.create(form=form, question_key='nid_copy',
                                           file=SimpleUploadedFile('n.pdf', b'%PDF-1'))

    form.drop_hidden_files()

    remaining = set(form.files.values_list('pk', flat=True))
    assert orphan.pk not in remaining and kept.pk in remaining


@pytest.mark.django_db
def test_the_done_page_does_not_name_the_candidate_without_the_code(client, candidate):
    from django.urls import reverse
    from apps.employee_form.models import EmployeeForm
    form = EmployeeForm.objects.create(resume=candidate, is_submitted=True, submitted_at=timezone.now())

    html = client.get(reverse('employee_form:done', kwargs={'token': form.token})).content.decode()

    assert 'Sadia' not in html


# ── reference checks ─────────────────────────────────────────────────────
def _check(candidate, **extra):
    from apps.reference_checks.models import ReferenceCheck
    fields = dict(resume=candidate, kind='employer', source_key='employer_1', recipient_name='Karim',
                  recipient_email='karim@example.com',
                  token_expires_at=timezone.now() + timedelta(days=5))
    fields.update(extra)
    return ReferenceCheck.objects.create(**fields)


@pytest.mark.django_db
def test_a_newline_in_the_candidates_name_does_not_block_the_request(candidate):
    from apps.reference_checks.services import send_request
    Resume.objects.filter(pk=candidate.pk).update(candidate_name='Sadia\nKarim')
    candidate.refresh_from_db()
    check = _check(candidate)
    mail.outbox = []

    send_request(check, otp='[PLACEHOLDER]')

    assert '\n' not in mail.outbox[0].subject


@pytest.mark.django_db
def test_a_referee_who_resends_the_code_stays_signed_in(candidate):
    from apps.reference_checks.services import resend_code
    check = _check(candidate, otp_verified_at=timezone.now())

    resend_code(check)

    check.refresh_from_db()
    assert check.otp_verified_at is not None


def _post_step(client, check, token, first):
    from django.urls import reverse
    session = client.session
    session[f'reference_check_verified:{token}'] = True
    session.save()
    with mock.patch('apps.reference_checks.views._get_check', return_value=check), \
            mock.patch('apps.reference_checks.views.StepForm.is_valid', return_value=True), \
            mock.patch('apps.reference_checks.views.StepForm.storable_answers',
                       return_value={'probe': 'written'}, create=True):
        client.post(reverse('reference_checks:step', kwargs={'token': token, 'step_key': first}), {})


@pytest.mark.django_db
def test_a_step_posted_after_the_recipient_changed_is_not_written(client, candidate):
    import uuid
    from apps.reference_checks import schema
    from apps.reference_checks.models import ReferenceCheck
    first = schema.first_step('employer')

    control = _check(candidate, otp_verified_at=timezone.now())
    _post_step(client, control, control.token, first)
    control.refresh_from_db()
    assert control.answers.get('probe') == 'written'

    check = _check(candidate, otp_verified_at=timezone.now(), source_key='employer_2')
    old_token = check.token
    ReferenceCheck.objects.filter(pk=check.pk).update(token=uuid.uuid4(), answers={})
    _post_step(client, check, old_token, first)
    check.refresh_from_db()
    assert 'probe' not in check.answers


# ── candidate mapping ────────────────────────────────────────────────────
def test_a_description_is_cleared_when_its_answer_changes_to_none_known():
    from apps.candidate_mapping import schema
    from apps.candidate_mapping.forms import StepForm
    step = next(key for key in schema.STEP_KEYS
                if any(q['key'] == 'adverse_record' for q in schema.questions(key)))
    data = {}
    for question in schema.questions(step):
        if question.get('choices'):
            data[question['key']] = question['choices'][0][0]
        elif question['type'] not in schema.FILE_TYPES:
            data[question['key']] = 'text'
    data['adverse_record'] = 'none_known'
    data['adverse_record_details'] = 'An old allegation'

    form = StepForm(data=data, step_key=step)
    form.is_valid()

    assert form.cleaned_data.get('adverse_record_details') == ''


# ── HR verification ──────────────────────────────────────────────────────
def test_answers_from_an_earlier_hr_form_version_stay_readable():
    from apps.hr_verification.review import build_sections
    sections = build_sections({'agency_required': 'yes', 'reference_1_hr_email': 'a@b.com'},
                              {}, lambda step: False)
    legacy = [s for s in sections if s['key'] == 'legacy']
    assert legacy
    labels = {row['label'] for row in legacy[0]['blocks'][0]['rows']}
    assert 'Agency required' in labels
