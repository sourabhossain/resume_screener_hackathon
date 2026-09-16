"""Which assessments a job sends, and what a candidate gets when shortlisted.

The rule is that the job decides. Nothing goes out that the job did not ask
for, and a job that asks for nothing sends nothing -- which is what every job
starts as.
"""
import json

import pytest
from django.core import mail
from django.urls import reverse

from apps.core.forms import JobForm
from apps.core.models import Job, Resume
from apps.sei_assessment import instruments
from apps.sei_assessment.models import SEIAssessment


def _shortlist(client, resume):
    return client.post(
        reverse('core:resume_status_update', kwargs={'uuid': resume.uuid}),
        {'recruiter_status': 'shortlisted'})


@pytest.fixture
def candidate_of(db):
    def make(job):
        return Resume.objects.create(
            job=job, candidate_name='Nadia Islam',
            email='nadia@example.com', recruiter_status='new')
    return make


# ── what the job asks for ────────────────────────────────────────────────
@pytest.mark.django_db
def test_a_job_starts_with_no_assessments(sample_job):
    """The default has to be 'none': a job that silently emailed a timed test
    the recruiter never asked for would be worse than one that sends nothing."""
    assert sample_job.assessments == []


@pytest.mark.django_db
def test_shortlisting_on_a_job_with_none_sends_none(
        authenticated_client, sample_job, candidate_of):
    sample_job.assessments = []
    sample_job.save(update_fields=['assessments'])
    resume = candidate_of(sample_job)
    mail.outbox = []

    _shortlist(authenticated_client, resume)

    assert SEIAssessment.objects.filter(resume=resume).count() == 0
    assert not [m for m in mail.outbox if 'assessment' in m.subject.lower()]


@pytest.mark.django_db
@pytest.mark.parametrize('keys', [
    [instruments.SEI],
    [instruments.PE],
    [instruments.SEI, instruments.PE],
])
def test_shortlisting_sends_exactly_what_the_job_asks_for(
        authenticated_client, sample_job, candidate_of, keys):
    sample_job.assessments = keys
    sample_job.save(update_fields=['assessments'])
    resume = candidate_of(sample_job)
    mail.outbox = []

    _shortlist(authenticated_client, resume)

    sat = set(SEIAssessment.objects.filter(resume=resume)
              .values_list('instrument', flat=True))
    assert sat == set(keys)


@pytest.mark.django_db
def test_two_assessments_arrive_as_two_separate_emails(
        authenticated_client, sample_job, candidate_of):
    """One message each: a candidate has to be able to tell which link is
    which, and a failure on one must not swallow the other."""
    sample_job.assessments = [instruments.SEI, instruments.PE]
    sample_job.save(update_fields=['assessments'])
    resume = candidate_of(sample_job)
    mail.outbox = []

    _shortlist(authenticated_client, resume)

    subjects = [m.subject for m in mail.outbox if 'assessment' in m.subject.lower()]
    assert len(subjects) == 2
    for spec in instruments.all_instruments():
        assert any(spec.label in s for s in subjects), spec.key

    tokens = {str(a.token) for a in SEIAssessment.objects.filter(resume=resume)}
    bodies = ' '.join(m.body for m in mail.outbox)
    for token in tokens:
        assert token in bodies


@pytest.mark.django_db
def test_an_unknown_key_in_the_job_does_not_block_shortlisting(
        authenticated_client, sample_job, candidate_of):
    """assessments is a JSONField, so a retired key can survive in an old row.
    It must be ignored rather than stop a candidate moving forward."""
    sample_job.assessments = ['retired_instrument', instruments.PE]
    sample_job.save(update_fields=['assessments'])
    resume = candidate_of(sample_job)

    response = _shortlist(authenticated_client, resume)

    assert response.status_code in (200, 302)
    sat = list(SEIAssessment.objects.filter(resume=resume)
               .values_list('instrument', flat=True))
    assert sat == [instruments.PE]


# ── one sitting per instrument ───────────────────────────────────────────
@pytest.mark.django_db
def test_a_candidate_can_hold_one_sitting_of_each_instrument(
        sample_job, candidate_of):
    resume = candidate_of(sample_job)

    SEIAssessment.objects.create(resume=resume, instrument=instruments.SEI)
    SEIAssessment.objects.create(resume=resume, instrument=instruments.PE)

    assert resume.sittings.count() == 2


@pytest.mark.django_db
def test_a_second_sitting_of_the_same_instrument_is_refused(
        sample_job, candidate_of):
    """Two live links for one questionnaire would mean two clocks and two sets
    of answers for the same result. Resending reuses the row instead."""
    from django.db import IntegrityError, transaction
    resume = candidate_of(sample_job)
    SEIAssessment.objects.create(resume=resume, instrument=instruments.SEI)

    with pytest.raises(IntegrityError), transaction.atomic():
        SEIAssessment.objects.create(resume=resume, instrument=instruments.SEI)


@pytest.mark.django_db
def test_resending_reuses_the_sitting_rather_than_opening_another(
        sample_job, candidate_of):
    from apps.sei_assessment import services
    resume = candidate_of(sample_job)

    first = services.issue_invite(resume, instrument=instruments.PE)
    again = services.issue_invite(resume, instrument=instruments.PE, resend=True)

    assert first.pk == again.pk
    assert SEIAssessment.objects.filter(resume=resume).count() == 1


# ── the job form ─────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_the_form_saves_the_boxes_that_were_ticked(sample_job):
    form = JobForm(instance=sample_job, data={
        'title': 'Head of Data', 'description': 'Lead the data team.',
        'status': 'draft', 'assessments': [instruments.PE, instruments.SEI],
    })

    assert form.is_valid(), form.errors
    job = form.save()

    # Stored in the registry's order, not the order the boxes came back in, so
    # two jobs with the same set email their candidates in the same sequence.
    assert job.assessments == list(instruments.ORDER)


@pytest.mark.django_db
def test_the_form_accepts_no_boxes_at_all(sample_job):
    sample_job.assessments = [instruments.SEI]
    sample_job.save(update_fields=['assessments'])

    form = JobForm(instance=sample_job, data={
        'title': 'Head of Data', 'description': 'Lead the data team.',
        'status': 'draft',
    })

    assert form.is_valid(), form.errors
    assert form.save().assessments == []


@pytest.mark.django_db
def test_the_form_drops_a_key_that_is_not_an_instrument(sample_job):
    form = JobForm(instance=sample_job, data={
        'title': 'Head of Data', 'description': 'Lead the data team.',
        'status': 'draft', 'assessments': ['nonsense'],
    })

    assert not form.is_valid()
    assert 'assessments' in form.errors


@pytest.mark.django_db
def test_editing_a_job_shows_the_boxes_already_ticked(sample_job):
    sample_job.assessments = [instruments.PE]
    sample_job.save(update_fields=['assessments'])

    form = JobForm(instance=sample_job)

    assert form.fields['assessments'].initial == [instruments.PE]


# ── the sitting knows its own instrument ─────────────────────────────────
@pytest.mark.django_db
def test_each_sitting_carries_its_own_clock_and_item_count(
        sample_job, candidate_of):
    resume = candidate_of(sample_job)
    sei = SEIAssessment.objects.create(resume=resume, instrument=instruments.SEI)
    pe = SEIAssessment.objects.create(resume=resume, instrument=instruments.PE)

    assert sei.TIME_LIMIT_MINUTES == 15
    assert pe.TIME_LIMIT_MINUTES == 8
    assert sei.spec.total_items == 48
    assert pe.spec.total_items == 15


@pytest.mark.django_db
def test_a_pe_sitting_is_scored_by_the_pe_model(sample_job, candidate_of):
    """The sitting must not be handed to the SEI scorer: the scales differ, so
    a 4 would be dropped and the totals would be meaningless."""
    from apps.sei_assessment import pe_scoring
    resume = candidate_of(sample_job)
    pe = SEIAssessment.objects.create(
        resume=resume, instrument=instruments.PE, is_submitted=True,
        answers={str(i): (0 if i in pe_scoring.REVERSED else 4)
                 for i in pe_scoring.ITEMS})

    result = pe.result()

    assert result['category'] == 'Effective'
    assert 'total_percent' not in result


@pytest.mark.django_db
def test_a_four_is_a_valid_answer_on_pe_and_not_on_sei(
        client, sample_job, candidate_of):
    """The save endpoint validates against the sitting's own instrument. With
    one shared rule a real PE answer of 4 would be silently dropped."""
    resume = candidate_of(sample_job)
    for key, top in ((instruments.PE, 4), (instruments.SEI, 4)):
        sitting = SEIAssessment.objects.create(resume=resume, instrument=key)
        otp = sitting.issue_otp()
        sitting.save()
        client.post(reverse('sei_assessment:verify',
                            kwargs={'token': sitting.token}), {'code': otp})
        client.get(reverse('sei_assessment:test', kwargs={'token': sitting.token}))
        client.post(reverse('sei_assessment:save', kwargs={'token': sitting.token}),
                    data=json.dumps({'answers': {'1': top}}),
                    content_type='application/json')
        sitting.refresh_from_db()
        if key == instruments.PE:
            assert sitting.answers == {'1': 4}
        else:
            assert sitting.answers == {}, 'SEI tops out at 3'
