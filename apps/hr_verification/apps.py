from django.apps import AppConfig


class HrVerificationConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.hr_verification'
    verbose_name = 'HR verification'

    def ready(self):
        from . import signals  # noqa: F401
