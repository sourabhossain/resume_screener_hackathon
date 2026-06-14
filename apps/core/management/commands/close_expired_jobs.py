from django.core.management.base import BaseCommand

from apps.core.tasks import close_expired_jobs


class Command(BaseCommand):
    help = "Close active jobs whose application deadline (closing_date) has passed."

    def handle(self, *args, **options):
        result = close_expired_jobs()
        self.stdout.write(self.style.SUCCESS(
            f"Closed {result['closed']} expired job(s)."
        ))
