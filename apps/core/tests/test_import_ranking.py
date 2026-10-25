"""Loading a job and its ranked candidates from a recruiter's sheet."""
import json

import pymupdf
import pytest
from django.core import mail
from django.core.management import CommandError, call_command

from apps.core.models import Job, Resume, StatusChange


def _cv(path, name):
    doc = pymupdf.open()
    page = doc.new_page()
    for i, line in enumerate([name, f'{name.split()[0].lower()}.cv2024@example.com', '+8801711000000',
                              'Head of Sales, payments and merchant acquisition', 'MBA in Marketing']):
        page.insert_text((72, 100 + 24 * i), line, fontsize=14)
    path.write_bytes(doc.tobytes())


def _row(rank, name, score, verdict, **extra):
    return {'rank': rank, 'name': name, 'score': score, 'verdict': verdict, 'experience': '20+ yrs',
            'position': 'Head of Sales, Example Ltd.', 'education': 'MBA-IBA; BUET',
            'certifications': 'AML/CFT; Power BI', 'strengths': 'Merchant acquisition at scale',
            'gaps': 'No payment-gateway exposure', 'cv': f'{name}.pdf', **extra}


@pytest.fixture
def bundle(tmp_path, admin_user):
    ai = {'skill_score': 75.0, 'experience_score': 88.4, 'education_score': 90, 'certification_score': 50,
          'achievement_score': 70, 'matched_skills': ['Merchant acquisition'], 'missing_skills': ['Payment gateway'],
          'skills': ['Sales leadership'], 'achievements': ['Grew merchants 10x'], 'final_score': 64}
    rows = [_row(1, 'Asha Rahman', 91.5, 'Strong Fit - Shortlist for Interview', ai=ai),
            _row(2, 'Nabil Hasan', 70.6, 'Moderate Fit - Backup / Secondary Review', certifications='—'),
            _row(3, 'Rafiq Uddin', 50.8, 'Low Fit - Reject')]
    for row in rows:
        _cv(tmp_path / row['cv'], row['name'])
    job = {'title': 'Head of Sales (SSLCOMMERZ)', 'slug': 'head-of-sales-sslcommerz', 'status': 'closed',
           'employment_type': 'full_time', 'location_type': 'on_site', 'location': 'Dhaka, Bangladesh',
           'description': '## Key Responsibilities\n\n- Merchant acquisition', 'applied_date': '2026-10-01'}
    (tmp_path / 'ranking.json').write_text(json.dumps({'job': job, 'candidates': rows}))
    return tmp_path


def _import(bundle, *flags):
    call_command('import_ranking', str(bundle), *flags)


@pytest.mark.django_db
def test_a_dry_run_writes_nothing(bundle):
    _import(bundle)
    assert not Job.all_objects.filter(slug='head-of-sales-sslcommerz').exists()
    assert not Resume.all_objects.exists()


@pytest.mark.django_db
def test_the_sheet_is_loaded_as_it_stands_and_nobody_is_emailed(bundle, admin_user):
    _import(bundle, '--commit')

    job = Job.objects.get(slug='head-of-sales-sslcommerz')
    assert job.status == 'closed' and job.owner == admin_user
    asha, nabil, rafiq = (Resume.objects.get(job=job, candidate_name=n)
                          for n in ('Asha Rahman', 'Nabil Hasan', 'Rafiq Uddin'))
    assert (asha.final_score, asha.tier, asha.recommendation, asha.recruiter_status) == (
        91.5, 'top', 'interview', 'shortlisted')
    assert (nabil.tier, nabil.recommendation, nabil.recruiter_status) == ('mid', 'talent_pool', 'new')
    assert (rafiq.tier, rafiq.recommendation, rafiq.recruiter_status) == ('low', 'reject', 'rejected')
    assert asha.email == 'asha.cv2024@example.com' and asha.phone == '+8801711000000'
    assert asha.education == ['MBA-IBA', 'BUET'] and nabil.certifications == []
    assert asha.experience_years == 20 and not asha.score_manually_edited and asha.score_edited_by is None
    assert asha.screening_status == 'completed' and asha.verification_status == 'skipped'
    assert 'Ranked #1 of 3 candidates for this role.' in asha.reasoning
    assert 'Gaps: No payment-gateway exposure.' in asha.reasoning
    assert asha.file and asha.file_hash and 'Head of Sales' in asha.raw_text
    from django.utils import timezone
    assert timezone.localtime(asha.created_at).date().isoformat() == '2026-10-01'
    assert (asha.skills_score, asha.experience_score, asha.education_score, asha.certification_score) == (
        75, 88, 90, 50)
    assert asha.matched_skills == ['Merchant acquisition'] and asha.missing_skills == ['Payment gateway']
    assert asha.final_score == 91.5 and nabil.skills_score is None
    assert asha.screening_summary == {
        'verdict': 'Strong Fit - Shortlist for Interview', 'experience': '20+ yrs',
        'position': 'Head of Sales, Example Ltd.', 'education': 'MBA-IBA; BUET', 'certifications': 'AML/CFT; Power BI',
        'strengths': 'Merchant acquisition at scale', 'gaps': 'No payment-gateway exposure'}
    assert mail.outbox == []


@pytest.mark.django_db
def test_running_it_again_updates_rather_than_duplicates(bundle):
    _import(bundle, '--commit')
    asha = Resume.objects.get(candidate_name='Asha Rahman')
    from apps.core.status import change_status
    change_status(asha, 'interviewing')

    _import(bundle, '--commit')

    assert Resume.objects.count() == 3
    asha.refresh_from_db()
    assert asha.recruiter_status == 'interviewing'
    assert StatusChange.objects.filter(resume__candidate_name='Rafiq Uddin').count() == 1


@pytest.mark.django_db
def test_a_missing_cv_stops_the_whole_import(bundle):
    (bundle / 'Nabil Hasan.pdf').unlink()
    with pytest.raises(CommandError, match='CV file not found'):
        _import(bundle, '--commit')
    assert not Resume.all_objects.exists()


@pytest.mark.django_db
def test_finished_interviews_are_recorded_without_any_email(bundle, admin_user):
    sheet = json.loads((bundle / 'ranking.json').read_text())
    sheet['candidates'][0].update(status_after='interviewing', interviews=[
        {'date': '2026-10-12', 'recommendation': 'yes', 'impression': 'Good'}])
    sheet['candidates'][1].update(status_after='withdrawn', interviews=[
        {'date': '2026-10-13', 'recommendation': 'no', 'impression': 'Poor',
         'notes': 'Currently not interested in pursuing the opportunity.'}])
    (bundle / 'ranking.json').write_text(json.dumps(sheet))

    _import(bundle, '--commit')
    _import(bundle, '--commit')

    from apps.interviews.models import Interview, InterviewEvaluation
    asha = Resume.objects.get(candidate_name='Asha Rahman')
    nabil = Resume.objects.get(candidate_name='Nabil Hasan')
    assert (asha.recruiter_status, nabil.recruiter_status) == ('interviewing', 'withdrawn')
    assert Interview.objects.count() == 2 and InterviewEvaluation.objects.count() == 2
    interview = Interview.objects.get(resume=nabil)
    assert interview.status == 'completed' and str(interview.scheduled_date) == '2026-10-13'
    evaluation = interview.evaluations.get()
    assert evaluation.is_submitted and evaluation.evaluator == admin_user and evaluation.recommendation == 'no'
    assert evaluation.impression_label == 'Poor' and evaluation.total_score is None
    assert mail.outbox == []


@pytest.mark.django_db
def test_an_interview_page_without_criteria_scores_shows_the_recommendation(bundle, admin_user, client):
    sheet = json.loads((bundle / 'ranking.json').read_text())
    sheet['candidates'][0]['interviews'] = [{'date': '2026-10-12', 'recommendation': 'yes', 'impression': 'Good'}]
    (bundle / 'ranking.json').write_text(json.dumps(sheet))
    _import(bundle, '--commit')
    from apps.interviews.models import Interview
    client.force_login(admin_user)
    html = client.get(f'/interviews/{Interview.objects.get().pk}/').content.decode()
    assert 'Yes - Next round' in html and 'Impression: Good' in html
    assert 'None' not in html.split('</header>')[-1]
    resume_page = client.get(f'/resumes/{Resume.objects.get(candidate_name="Asha Rahman").uuid}/').content.decode()
    assert '1 of 1 submitted' in resume_page and 'Yes - Next round' in resume_page


@pytest.mark.django_db
def test_interview_marks_are_stored_and_bad_marks_stop_the_import(bundle):
    from apps.interviews.models import CRITERIA_KEYS, InterviewEvaluation
    sheet = json.loads((bundle / 'ranking.json').read_text())
    sheet['candidates'][0]['interviews'] = [{'date': '2026-10-12', 'recommendation': 'yes',
                                             'scores': {key: 4 for key in CRITERIA_KEYS}}]
    (bundle / 'ranking.json').write_text(json.dumps(sheet))
    _import(bundle, '--commit')
    evaluation = InterviewEvaluation.objects.get()
    assert (evaluation.total_score, evaluation.percentage, evaluation.impression_label) == (80, 80, 'Good')

    sheet['candidates'][0]['interviews'][0]['scores']['adaptability'] = 6
    (bundle / 'ranking.json').write_text(json.dumps(sheet))
    with pytest.raises(CommandError, match='adaptability=6'):
        _import(bundle, '--commit')
