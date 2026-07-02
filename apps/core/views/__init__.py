"""
Core views package.

views.py grew past 950 lines mixing recruiter pages, public careers, user
management, CSV export and media serving. It's now split by concern into the
submodules below. Everything is re-exported here so `from . import views` +
`views.<name>` in urls.py (and external imports like
`from apps.core.views import form_errors_to_messages`) keep working unchanged.
"""
from ..form_utils import form_errors_to_messages  # noqa: F401

from ._helpers import (  # noqa: F401
    _csv_safe,
    _get_active_resume,
    _ordered_active_resumes_queryset,
    _pipeline_stats,
    _superuser_required,
    _validate_user_name_fields,
)
from .audit import audit_log_export_csv, audit_log_list  # noqa: F401
from .dashboard import dashboard, health_check  # noqa: F401
from .jobs import (  # noqa: F401
    job_create,
    job_delete,
    job_detail,
    job_edit,
    job_export_csv,
    job_list,
    pipeline_search,
    pipeline_suggestions,
)
from .resumes import (  # noqa: F401
    resume_bulk_create,
    resume_create,
    resume_delete,
    resume_detail,
    resume_edit,
    resume_note_add,
    resume_note_delete,
    resume_rescreen,
    resume_row_fragment,
    resume_status_fragment,
    resume_status_update,
)
from .careers import careers_apply, careers_list, careers_thanks  # noqa: F401
from .screening import (  # noqa: F401
    _failed_resumes_queryset,
    _needs_review_resumes_queryset,
    needs_review_list,
    screening_failed_list,
    screening_rescreen_bulk,
    talent_pool,
)
from .users import (  # noqa: F401
    user_change_password,
    user_create,
    user_list,
    user_toggle_active,
)
from .media import serve_protected_media  # noqa: F401
from .auth import ToastLoginView  # noqa: F401
