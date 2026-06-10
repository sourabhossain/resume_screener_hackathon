from django.core.management.base import BaseCommand
from django.db.models import Q

from apps.core.models import Resume
from apps.core.services.resume_service import ResumeService


class Command(BaseCommand):
    help = 'Backfill email/phone for resumes that have raw_text but missing contact info.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Show what would be updated without saving.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']

        qs = Resume.objects.exclude(raw_text='').filter(
            raw_text__isnull=False
        ).filter(
            Q(email='') | Q(phone='')
        )

        total = qs.count()
        self.stdout.write(f'Found {total} resumes with missing contact info.')

        fixed_email = fixed_phone = 0

        for resume in qs.iterator():
            old_email, old_phone = resume.email, resume.phone

            if dry_run:
                email, email_pos = ResumeService._extract_email(resume.raw_text)
                phone = ResumeService._extract_phone(resume.raw_text, email_pos)
                if not old_email and email:
                    self.stdout.write(f'  [{resume.id}] {resume.candidate_name}: email → {email}')
                    fixed_email += 1
                if not old_phone and phone:
                    self.stdout.write(f'  [{resume.id}] {resume.candidate_name}: phone → {phone}')
                    fixed_phone += 1
            else:
                ResumeService._fill_contact_info(resume, resume.raw_text)
                resume.refresh_from_db()
                if not old_email and resume.email:
                    fixed_email += 1
                if not old_phone and resume.phone:
                    fixed_phone += 1

        suffix = ' (dry run)' if dry_run else ''
        self.stdout.write(self.style.SUCCESS(
            f'Done{suffix}: {fixed_email} emails and {fixed_phone} phones updated.'
        ))
