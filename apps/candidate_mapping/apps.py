from django.apps import AppConfig


class CandidateMappingConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.candidate_mapping'
    verbose_name = 'Candidate mapping'

    def ready(self):
        from . import signals  # noqa: F401
