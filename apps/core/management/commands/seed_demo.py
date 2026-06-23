from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.core.models import Job, Resume

DEMO_PREFIX = "[Demo] "


class Command(BaseCommand):
    help = "Insert demo jobs and resumes for local development and QA."

    def add_arguments(self, parser):
        parser.add_argument(
            "--clear",
            action="store_true",
            help=f"Remove jobs titled with '{DEMO_PREFIX}' (resumes cascade). Then exit.",
        )

    def handle(self, *args, **options):
        demo_jobs = Job.all_objects.filter(title__startswith=DEMO_PREFIX)

        if options["clear"]:
            with transaction.atomic():
                deleted, details = demo_jobs.delete()
            self.stdout.write(
                self.style.WARNING(f"Cleared demo data ({deleted} object(s)): {details}")
            )
            return

        if demo_jobs.filter(is_deleted=False).exists():
            self.stdout.write(
                self.style.WARNING(
                    "Demo rows already exist. Run with --clear to remove, then seed again."
                )
            )
            return

        today = timezone.now().date()

        with transaction.atomic():
            job_backend = Job.objects.create(
                title=f"{DEMO_PREFIX}Senior Backend Engineer (Python)",
                description=(
                    "Build APIs and screening pipelines with Django, MySQL, and Redis. "
                    "Prior experience with REST and async tasks (Celery) preferred."
                ),
                status="active",
                posted_date=today - timedelta(days=7),
                closing_date=today + timedelta(days=30),
                required_skills=["Python", "Django", "MySQL", "Redis", "REST APIs"],
                required_experience=4.0,
                required_education=["Bachelor", "Computer Science"],
            )

            job_analyst = Job.objects.create(
                title=f"{DEMO_PREFIX}Junior Data Analyst",
                description=(
                    "Support hiring analytics and reporting. SQL, spreadsheets, "
                    "and basic Python for dashboards."
                ),
                status="active",
                posted_date=today - timedelta(days=3),
                closing_date=today + timedelta(days=14),
                required_skills=["SQL", "Python", "Excel", "Communication"],
                required_experience=1.0,
                required_education=["Bachelor"],
            )

            samples = [
                {
                    "job": job_backend,
                    "candidate_name": "Ayesha Rahman",
                    "raw_text": "6 years backend with Django and FastAPI. Led MySQL migrations.",
                    "final_score": 86.0,
                    "experience_score": 90.0,
                    "education_score": 80.0,
                    "skills_score": 88.0,
                    "matched_skills": ["Python", "Django", "MySQL", "REST APIs"],
                    "missing_skills": ["Redis"],
                    "skills": ["Python", "Django", "MySQL", "Docker"],
                    "education": ["B.Sc. - Computer Science"],
                    "experience_years": 6.0,
                    "screening_status": "completed",
                    "reasoning": "Strong stack match; minor gap on Redis.",
                },
                {
                    "job": job_backend,
                    "candidate_name": "Karim Hossain",
                    "raw_text": "3 years Python, mostly scripting; some Flask exposure.",
                    "final_score": 62.0,
                    "experience_score": 55.0,
                    "education_score": 70.0,
                    "skills_score": 60.0,
                    "matched_skills": ["Python", "REST APIs"],
                    "missing_skills": ["Django", "MySQL", "Redis"],
                    "skills": ["Python", "Flask", "MySQL"],
                    "education": ["B.Sc. - Information Technology"],
                    "experience_years": 3.0,
                    "screening_status": "completed",
                    "reasoning": "Mid fit; limited Django/MySQL depth.",
                },
                {
                    "job": job_backend,
                    "candidate_name": "Nusrat Jahan",
                    "raw_text": "Fresh graduate; internship with Java only.",
                    "final_score": 38.0,
                    "experience_score": 25.0,
                    "education_score": 65.0,
                    "skills_score": 35.0,
                    "matched_skills": [],
                    "missing_skills": ["Python", "Django", "MySQL", "Redis", "REST APIs"],
                    "skills": ["Java", "Spring"],
                    "education": ["B.Sc. - Computer Science & Engineering"],
                    "experience_years": 0.5,
                    "screening_status": "completed",
                    "reasoning": "Low alignment with required Python/Django stack.",
                },
                {
                    "job": job_analyst,
                    "candidate_name": "Farhan Ahmed",
                    "raw_text": "2 years analyst role; SQL and Python for reports.",
                    "final_score": 72.0,
                    "experience_score": 68.0,
                    "education_score": 75.0,
                    "skills_score": 74.0,
                    "matched_skills": ["SQL", "Python", "Excel"],
                    "missing_skills": [],
                    "skills": ["SQL", "Python", "Tableau"],
                    "education": ["BBA - Finance"],
                    "experience_years": 2.0,
                    "screening_status": "completed",
                    "reasoning": "Solid analyst toolkit for junior role.",
                },
            ]

            for row in samples:
                job = row.pop("job")
                Resume.objects.create(job=job, **row)

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {Job.objects.filter(title__startswith=DEMO_PREFIX).count()} demo jobs "
                f"and {Resume.objects.filter(job__title__startswith=DEMO_PREFIX).count()} resumes."
            )
        )
