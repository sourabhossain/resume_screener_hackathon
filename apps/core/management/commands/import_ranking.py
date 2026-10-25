"""Load a job and its candidates from a screening result sheet.

The folder holds ranking.json and the CV files it names. The sheet's score and
verdict are stored as the screening result, the same as an AI screening would
leave them. A row's optional "ai" block carries part scores and the skill match
from an earlier AI run; nothing calls the AI here. Without --commit nothing is
written.
"""
import json
import os
import re
from datetime import date, datetime, time
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.files import File
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.core.models import Job, Resume
from apps.core.services.document_extractor import DocumentExtractor
from apps.core.services.resume_service import ResumeService
from apps.core.status import change_status
from apps.core.utils import compute_file_hash

MAX_FILE_SIZE = 5 * 1024 * 1024
MAGIC_BYTES = {'.pdf': b'%PDF', '.docx': b'PK\x03\x04'}
MIN_TEXT_CHARS = 40
JOB_FIELDS = ('title', 'description', 'status', 'employment_type', 'location_type', 'location')
EMPTY_VALUES = {'', '-', '—', 'not specified in cv'}

# The sheet's verdict decides the decision, the tier and where the candidate starts.
VERDICTS = (
    ('strong', 'interview', 'top', 'shortlisted'),
    ('moderate', 'talent_pool', 'mid', 'new'),
    ('low', 'reject', 'low', 'rejected'),
)


def _verdict(text):
    lowered = (text or '').strip().lower()
    for prefix, recommendation, tier, status in VERDICTS:
        if lowered.startswith(prefix):
            return recommendation, tier, status
    return None


def _items(text):
    return [part.strip() for part in (text or '').split(';')
            if part.strip().lower() not in EMPTY_VALUES]


def _years(text):
    match = re.search(r'\d+(?:\.\d+)?', text or '')
    return float(match.group(0)) if match else None


def _sentence(text):
    text = ' '.join((text or '').split())
    return text if not text or text[-1] in '.!?' else text + '.'


class Command(BaseCommand):
    help = 'Load a job and its ranked candidates from a folder with ranking.json and the CVs.'

    def add_arguments(self, parser):
        parser.add_argument('folder', help='Folder holding ranking.json and the CV files.')
        parser.add_argument('--owner', help='Username recorded as the job owner and scorer.')
        parser.add_argument('--commit', action='store_true', help='Write to the database.')

    def handle(self, *args, folder, owner=None, commit=False, **options):
        root = Path(folder)
        try:
            sheet = json.loads((root / 'ranking.json').read_text(encoding='utf-8'))
        except (OSError, ValueError) as exc:
            raise CommandError(f'Cannot read {root / "ranking.json"}: {exc}')

        job_data = sheet.get('job') or {}
        missing = [key for key in ('title', 'slug', 'description') if not job_data.get(key)]
        if missing:
            raise CommandError(f'ranking.json job is missing: {", ".join(missing)}')
        rows = sheet.get('candidates') or []
        if not rows:
            raise CommandError('ranking.json lists no candidates.')

        user = self._owner(owner)
        checked, problems = [], []
        for row in rows:
            try:
                checked.append(self._check(root, {'applied': job_data.get('applied_date'), **row}))
            except CommandError as exc:
                problems.append(f'#{row.get("rank", "?")} {row.get("name", "?")}: {exc}')
        names = [row['name'].lower() for row in checked]
        problems += [f'{name}: listed twice' for name in {n for n in names if names.count(n) > 1}]
        hashes = [row['hash'] for row in checked if row['hash']]
        if len(hashes) != len(set(hashes)):
            problems.append('the same CV file is used for two candidates')

        for row in checked:
            self.stdout.write(
                f'#{row["rank"]:>3} {row["score"]:>5.1f}  {row["status"]:<12} {row["name"]:<34} '
                f'{row["cv"] or "(no CV)"}  {len(row["text"])} chars')
        if problems:
            raise CommandError('Nothing was written:\n  ' + '\n  '.join(problems))
        if not commit:
            self.stdout.write(self.style.WARNING(
                f'Dry run: {len(checked)} candidates look right. Run again with --commit to write them.'))
            return

        # Equal scores share a place, the same rule as the candidate page and the Excel sheet.
        scores = [row['score'] for row in checked]
        for row in checked:
            row['place'] = 1 + sum(1 for score in scores if score > row['score'])

        with transaction.atomic():
            job = self._job(job_data, user, root)
            created = sum(self._save(job, row, user, len(checked)) for row in checked)
        self.stdout.write(self.style.SUCCESS(
            f'{job.title} ({job.slug}): {created} added, {len(checked) - created} updated.'))

    def _owner(self, username):
        users = get_user_model().objects.filter(is_active=True)
        if username:
            user = users.filter(username=username).first()
            if not user:
                raise CommandError(f'No active user named {username!r}.')
            return user
        user = users.filter(is_superuser=True).order_by('date_joined').first()
        if not user:
            raise CommandError('No superuser to record as the owner; pass --owner.')
        return user

    def _check(self, root, row):
        name = ' '.join(str(row.get('name') or '').split())
        if not name:
            raise CommandError('no name')
        try:
            score = float(row.get('score'))
        except (TypeError, ValueError):
            raise CommandError('no score')
        if not 0 <= score <= 100:
            raise CommandError(f'score {score} is outside 0-100')
        verdict = _verdict(row.get('verdict'))
        if not verdict:
            raise CommandError(f'unknown verdict {row.get("verdict")!r}')
        valid_statuses = {key for key, _ in Resume.RECRUITER_STATUS_CHOICES}
        if row.get('status_after') and row['status_after'] not in valid_statuses:
            raise CommandError(f'unknown status_after {row["status_after"]!r}')
        for item in row.get('interviews') or []:
            try:
                date.fromisoformat(item.get('date') or '')
            except ValueError:
                raise CommandError(f'interview date {item.get("date")!r} is not YYYY-MM-DD')
            if item.get('recommendation') not in ('yes', 'no', 'maybe'):
                raise CommandError(f'interview recommendation {item.get("recommendation")!r} is not yes/no/maybe')
            from apps.interviews.models import CRITERIA_KEYS
            for key, value in (item.get('scores') or {}).items():
                if key not in CRITERIA_KEYS or not isinstance(value, int) or not 1 <= value <= 5:
                    raise CommandError(f'interview score {key}={value!r} is not a known criterion marked 1-5')
        applied = None
        if row.get('applied'):
            try:
                applied = timezone.make_aware(datetime.combine(date.fromisoformat(row['applied']), time(12)))
            except ValueError:
                raise CommandError(f'applied date {row["applied"]!r} is not YYYY-MM-DD')

        cv, text, file_hash = row.get('cv') or '', '', ''
        if cv:
            path = root / cv
            ext = path.suffix.lower()
            if not path.is_file():
                raise CommandError(f'CV file not found: {cv}')
            if ext not in MAGIC_BYTES:
                raise CommandError(f'{cv} is not a PDF or DOCX')
            if path.stat().st_size > MAX_FILE_SIZE:
                raise CommandError(f'{cv} is over 5 MB')
            with path.open('rb') as handle:
                if not handle.read(8).startswith(MAGIC_BYTES[ext]):
                    raise CommandError(f'{cv} is not a valid {ext[1:].upper()} file')
                file_hash = compute_file_hash(handle)
            try:
                text = DocumentExtractor.extract(str(path)) or ''
            except Exception as exc:
                raise CommandError(f'{cv} could not be read: {exc}')
            if len(text.strip()) < MIN_TEXT_CHARS:
                raise CommandError(f'no text could be read from {cv}')

        recommendation, tier, status = verdict
        return {**row, 'name': name, 'score': round(score, 1), 'cv': cv, 'path': root / cv if cv else None,
                'text': text, 'hash': file_hash, 'recommendation': recommendation, 'tier': tier,
                'status': status, 'applied': applied}

    def _job(self, data, user, root):
        job = Job.all_objects.filter(slug=data['slug']).first()
        if job and job.is_deleted:
            raise CommandError(f'Job {data["slug"]} is deleted; restore it first.')
        job = job or Job(slug=data['slug'], owner=user)
        for field in JOB_FIELDS:
            if field in data:
                setattr(job, field, data[field])
        job.save()
        jd = data.get('file')
        if jd and not job.file:
            path = root / jd
            if not path.is_file():
                raise CommandError(f'Job description file not found: {jd}')
            with path.open('rb') as handle:
                job.file.save(os.path.basename(jd), File(handle), save=False)
            job.file_name = os.path.basename(jd)
            job.file_type = path.suffix.lstrip('.').lower()
            job.save(update_fields=['file', 'file_name', 'file_type', 'updated_at'])
        return job

    def _save(self, job, row, user, total):
        resume = Resume.objects.filter(job=job, candidate_name__iexact=row['name']).first()
        created = resume is None
        resume = resume or Resume(job=job, candidate_name=row['name'])

        if row['path'] and resume.file_hash != row['hash']:
            with row['path'].open('rb') as handle:
                resume.file.save(row['path'].name, File(handle), save=False)
            resume.file_name = row['path'].name
            resume.file_type = row['path'].suffix.lstrip('.').lower()
            resume.file_hash = row['hash']
            resume.raw_text = row['text']
        if resume.raw_text:
            email, at = ResumeService._extract_email(resume.raw_text)
            resume.email = resume.email or email
            resume.phone = resume.phone or ResumeService._extract_phone(resume.raw_text, at)[:20]

        position = row.get('position', '').strip()
        resume.reasoning = ' '.join(part for part in (
            f'{_sentence(row.get("verdict"))} Ranked #{row["place"]} of {total} candidates for this role.',
            f'Current / last position: {_sentence(position)}' if position else '',
            f'Strengths: {_sentence(row.get("strengths"))}' if row.get('strengths') else '',
            f'Gaps: {_sentence(row.get("gaps"))}' if row.get('gaps') else '',
        ) if part)
        ai = row.get('ai') or {}
        if ai:
            # The part scores and skill match from one AI screening run; the
            # sheet's final score, decision and analysis stay as they are.
            resume.skills_score = round(ai.get('skill_score') or 0)
            resume.experience_score = round(ai.get('experience_score') or 0)
            resume.education_score = round(ai.get('education_score') or 0)
            resume.certification_score = round(ai.get('certification_score') or 0)
            resume.achievement_score = round(float(ai.get('achievement_score') or 0))
            resume.matched_skills = ai.get('matched_skills') or []
            resume.missing_skills = ai.get('missing_skills') or []
            resume.skills = ai.get('skills') or []
            resume.achievements = ai.get('achievements') or []
        resume.screening_summary = {key: ' '.join(str(row.get(key) or '').split())
                                    for key in ('verdict', 'experience', 'position', 'education',
                                                'certifications', 'strengths', 'gaps')}
        resume.final_score = row['score']
        resume.tier = row['tier']
        resume.recommendation = row['recommendation']
        resume.experience_years = _years(row.get('experience'))
        resume.education = _items(row.get('education'))
        resume.certifications = _items(row.get('certifications'))
        resume.screening_status = 'completed'
        resume.verification_status = 'skipped'
        resume.score_manually_edited = False
        resume.score_edited_at = None
        resume.score_edited_by = None
        resume.save()
        if row['applied']:
            # created_at is the Applied date; auto_now_add only allows it through update().
            Resume.objects.filter(pk=resume.pk).update(created_at=row['applied'])

        # A recruiter may already have moved the candidate on; that stands.
        if (resume.recruiter_status or 'new') == 'new' and row['status'] != 'new':
            change_status(resume, row['status'], user=user, reason='Set from the screening result')
        # Completed interviews first: a move to Withdrawn or Rejected cancels
        # (and emails about) scheduled ones only.
        for item in row.get('interviews') or []:
            self._interview(resume, item, user)
        if row.get('status_after') and (resume.recruiter_status or 'new') in (row['status'], 'new'):
            change_status(resume, row['status_after'], user=user, reason='Set from the interview result')
        return created

    def _interview(self, resume, item, user):
        """A finished interview with the owner's submitted recommendation; nobody is emailed."""
        from apps.interviews.models import Interview, InterviewEvaluation

        day = date.fromisoformat(item['date'])
        interview = Interview.objects.filter(resume=resume, phase=str(item.get('phase', '1')),
                                             scheduled_date=day).first()
        interview = interview or Interview(resume=resume, phase=str(item.get('phase', '1')), scheduled_date=day)
        interview.mode = item.get('mode') or Interview.IN_PERSON
        interview.status = Interview.COMPLETED
        interview.notify_candidate = False
        interview.save()

        evaluation = (InterviewEvaluation.objects.filter(interview=interview, evaluator=user).first()
                      or InterviewEvaluation(interview=interview, evaluator=user))
        evaluation.interviewer_name = user.get_full_name() or user.username
        evaluation.interviewer_email = user.email
        evaluation.recommendation = item['recommendation']
        evaluation.scores = item.get('scores') or {}
        evaluation.impression = item.get('impression', '')
        evaluation.additional_notes = item.get('notes', '')
        evaluation.is_submitted = True
        evaluation.submitted_at = timezone.make_aware(datetime.combine(day, time(17)))
        evaluation.save()
