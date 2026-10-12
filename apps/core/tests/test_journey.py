"""End to end through the real views: a candidate from the careers page to Onboarded.

Every step goes through the page or link a person would use. Only the AI
screening result is set directly, since that step calls an outside service.
"""
import json
import re
from datetime import timedelta

import pytest
from django.core import mail
from django.core.files.base import ContentFile
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.core.models import Resume, StatusChange
from apps.sei_assessment import instruments
from apps.sei_assessment.models import AssessmentInvitation, SEIAssessment


@pytest.fixture(autouse=True)
def _commit_now(monkeypatch):
    monkeypatch.setattr('django.db.transaction.on_commit', lambda fn, *a, **k: fn())


@pytest.fixture
def people(db, django_user_model, sample_job):
    django_user_model.objects.create_user('recruiter', 'rec@sslwireless.com', 'pw12345!')
    django_user_model.objects.create_user('hradmin', 'hr@sslwireless.com', 'hrpass123', is_staff=True,
                                          first_name='Hasan', last_name='Rahman')
    panel = django_user_model.objects.create_user('panel', 'panel@sslwireless.com', 'x',
                                                  first_name='Panel', last_name='One')
    recruiter, hr = Client(), Client()
    recruiter.login(username='recruiter', password='pw12345!')
    hr.login(username='hradmin', password='hrpass123')
    sample_job.assessments = [instruments.PE, instruments.SEI]
    sample_job.save(update_fields=['assessments'])
    return {'recruiter': recruiter, 'hr': hr, 'panel': panel, 'job': sample_job}


def _status(client, resume, value):
    client.post(reverse('core:resume_status_update', kwargs={'uuid': resume.uuid}), {'recruiter_status': value})
    resume.refresh_from_db()
    return resume.recruiter_status


def _apply(job, email='nadia@example.com'):
    from apps.core.tests.test_careers import _post_apply
    response = _post_apply(Client(), job, {'email': email, 'candidate_name': 'Nadia Islam'})
    assert response.status_code == 302
    resume = Resume.objects.get(email=email)
    Resume.objects.filter(pk=resume.pk).update(screening_status='completed', verification_status='completed',
                                               final_score=82, raw_text='cv text')
    resume.refresh_from_db()
    return resume


def _subjects(address):
    return [m.subject for m in mail.outbox if address in m.to]


@pytest.mark.django_db
def test_a_candidate_goes_from_the_careers_page_to_onboarded(people):
    from apps.sei_assessment.tests.test_portal import _url as portal
    recruiter, hr, panel, job = people['recruiter'], people['hr'], people['panel'], people['job']
    resume = _apply(job)
    assert resume.recruiter_status == 'new'

    assert _status(recruiter, resume, 'shortlisted') == 'shortlisted'
    assert _status(recruiter, resume, 'phone_screen') == 'phone_screen'
    assert _subjects('nadia@example.com') == []

    # Assessment: one link, both parts taken, both reports open.
    _status(recruiter, resume, 'assessment')
    invite = [m for m in mail.outbox if 'nadia@example.com' in m.to]
    assert len(invite) == 1
    invitation = AssessmentInvitation.objects.get(resume=resume)
    candidate = Client()
    candidate.post(portal('verify', invitation), {'code': re.search(r'\b(\d{6})\b', invite[0].body).group(1)})
    for key, total, value in ((instruments.PE, 15, 2), (instruments.SEI, 48, 1)):
        part = SEIAssessment.objects.get(invitation=invitation, instrument=key)
        candidate.post(portal('begin_part', invitation, part=part.token), {'consent': '1'})
        candidate.post(portal('save_part', invitation, part=part.token), content_type='application/json',
                       data=json.dumps({'answers': {str(i): value for i in range(1, total + 1)}, 'finish': True}))
        part.refresh_from_db()
        assert part.is_submitted, key
        assert hr.get(reverse('sei_assessment:report', kwargs={'uuid': resume.uuid, 'instrument': key})).status_code == 200

    # Interview: scheduled, CV opened by the panel, moved, evaluated.
    from apps.interviews.models import CRITERIA_KEYS, Interview, InterviewEvaluation
    recruiter.post(reverse('interviews:create', kwargs={'resume_uuid': resume.uuid}), {
        'phase': '1', 'scheduled_date': (timezone.localdate() + timedelta(days=2)).isoformat(),
        'scheduled_time': '11:00', 'duration_minutes': '60', 'mode': 'in_person', 'location': 'Room 3',
        'notify_candidate': 'on', 'evaluators': [panel.pk]})
    resume.refresh_from_db()
    assert resume.recruiter_status == 'interviewing'
    evaluation = InterviewEvaluation.objects.get(interview__resume=resume)
    resume.file.save('cv.pdf', ContentFile(b'%PDF-1.4 cv'), save=True)
    assert Client().get(reverse('interviews:evaluation_cv', kwargs={'token': evaluation.token})).status_code == 200
    before = len(mail.outbox)
    recruiter.post(reverse('interviews:reschedule', kwargs={'pk': evaluation.interview_id}), {
        'scheduled_date': (timezone.localdate() + timedelta(days=4)).isoformat(), 'scheduled_time': '14:00',
        'duration_minutes': '60', 'mode': 'online', 'location': 'https://meet.google.com/abc', 'notify': 'on'})
    assert len(mail.outbox) - before == 2
    scores = {f'score_{key}': '4' for key in CRITERIA_KEYS}
    Client().post(reverse('interviews:evaluate', kwargs={'token': evaluation.token}), {**scores, 'recommendation': 'yes'})
    assert Interview.objects.get(pk=evaluation.interview_id).status == 'completed'

    # Selected: the information form goes once, and submitting it moves the status on.
    _status(recruiter, resume, 'selected')
    form_mail = [m for m in mail.outbox if 'nadia@example.com' in m.to and 'information form' in m.subject]
    assert len(form_mail) == 1
    from apps.employee_form.models import EmployeeForm
    from apps.employee_form.tests.test_submission import _walk
    form = EmployeeForm.objects.get(resume=resume)
    filler = Client()
    filler.post(reverse('employee_form:verify', kwargs={'token': form.token}),
                {'code': re.search(r'code is:\s*(\d{6})', form_mail[0].body).group(1)})
    _walk(filler, form)
    resume.refresh_from_db()
    assert resume.recruiter_status == 'info_received'

    # HR: verification with the offer recorded, signed off; mapping; references.
    from apps.hr_verification.models import HRVerification
    from apps.hr_verification.tests.test_hr_verification import CLEARANCE, VALID, _url as hr_url
    hr.post(hr_url('start', resume))
    for step_key, payload in VALID.items():
        if step_key == 'clearance':
            payload = {**CLEARANCE, 'offer_letter_issued': 'yes',
                       'offer_letter_issue_date': timezone.localdate().isoformat()}
        hr.post(hr_url('step', resume, step_key=step_key), payload)
    resume.refresh_from_db()
    assert resume.recruiter_status == 'info_received'
    hr.post(hr_url('submit', resume))
    assert HRVerification.objects.get(resume=resume).is_submitted
    resume.refresh_from_db()
    assert resume.recruiter_status == 'offer_extended'

    from apps.candidate_mapping.models import CandidateMapping
    from apps.candidate_mapping.tests.test_candidate_mapping import _complete
    hr.post(reverse('candidate_mapping:start', kwargs={'uuid': resume.uuid}))
    _complete(CandidateMapping.objects.get(resume=resume))
    hr.post(reverse('candidate_mapping:submit', kwargs={'uuid': resume.uuid}))
    assert CandidateMapping.objects.get(resume=resume).is_submitted

    from apps.reference_checks import services as references
    from apps.reference_checks.models import ReferenceCheck
    for key in ('employer_1', 'reference_1'):
        row = references.contact_for(resume, key)
        hr.post(reverse('reference_checks:send', kwargs={'uuid': resume.uuid, 'source_key': key}), {
            'kind': row['default_kind'], 'recipient_name': row['recipient_name'] or 'Ref',
            'recipient_email': row['recipient_email'], 'recipient_organisation': row['recipient_organisation']})
    assert ReferenceCheck.objects.filter(resume=resume).count() == 2

    # Pre-Onboarding: Onboarded waits for the checklist.
    assert _status(recruiter, resume, 'pre_onboarding') == 'pre_onboarding'
    assert _status(recruiter, resume, 'hired') == 'pre_onboarding'
    for key, _ in Resume.ONBOARDING_CHECKLIST:
        recruiter.post(reverse('core:resume_onboarding_toggle', kwargs={'uuid': resume.uuid}), {'item': key},
                       HTTP_HX_REQUEST='true')
    assert _status(recruiter, resume, 'hired') == 'hired'

    assert list(StatusChange.objects.filter(resume=resume).order_by('created_at', 'id')
                .values_list('to_status', flat=True)) == [
        'shortlisted', 'phone_screen', 'assessment', 'interviewing', 'selected', 'info_received',
        'bgv_completed', 'offer_extended', 'pre_onboarding', 'hired']
    assert len(_subjects('nadia@example.com')) == 4
    assert len(_subjects('panel@sslwireless.com')) == 2
    for url in (reverse('core:resume_detail', kwargs={'uuid': resume.uuid}), reverse('core:dashboard')):
        assert hr.get(url).status_code == 200


@pytest.mark.django_db
def test_a_rejected_candidate_gets_one_letter_and_nothing_else(people):
    recruiter, job = people['recruiter'], people['job']
    resume = _apply(job)
    for value in ('shortlisted', 'phone_screen', 'rejected'):
        _status(recruiter, resume, value)
    for _ in range(2):
        recruiter.post(reverse('core:resume_rejection_send', kwargs={'uuid': resume.uuid}))
    recruiter.post(reverse('employee_form:send', kwargs={'uuid': resume.uuid}))
    recruiter.post(reverse('interviews:create', kwargs={'resume_uuid': resume.uuid}), {'phase': '1'})

    assert len(_subjects('nadia@example.com')) == 1


@pytest.mark.django_db
def test_a_jump_to_selected_sends_the_form_once_and_withdrawing_sends_nothing(people):
    recruiter, job = people['recruiter'], people['job']
    resume = Resume.objects.create(job=job, candidate_name='Jump', email='jump@example.com',
                                   screening_status='completed', verification_status='completed')
    for value in ('selected', 'info_received', 'selected'):
        _status(recruiter, resume, value)
    assert len(_subjects('jump@example.com')) == 1

    mail.outbox.clear()
    assert _status(recruiter, resume, 'withdrawn') == 'withdrawn'
    assert _subjects('jump@example.com') == []
