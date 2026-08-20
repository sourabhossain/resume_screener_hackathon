from django.apps import AppConfig


class EmployeeFormConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.employee_form'
    verbose_name = 'Employee Form'

    def ready(self):
        # Registers the post_delete receiver that removes stored documents, and
        # the deploy-time settings guards.
        from . import checks, signals  # noqa: F401
