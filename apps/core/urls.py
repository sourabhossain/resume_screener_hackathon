"""
URL patterns for the core app.
"""
from django.urls import path
from . import views

app_name = 'core'

urlpatterns = [
    # Dashboard
    path('', views.dashboard, name='dashboard'),
    path('health/', views.health_check, name='health_check'),

    # Public candidate (careers) pages — no login required
    path('careers/', views.careers_list, name='careers'),
    path('careers/<slug:slug>/', views.careers_apply, name='careers_apply'),
    path('careers/<slug:slug>/thank-you/', views.careers_thanks, name='careers_thanks'),

    # Job URLs — public-facing identifier is the slug, not the numeric id
    path('jobs/', views.job_list, name='job_list'),
    path('jobs/create/', views.job_create, name='job_create'),
    path('jobs/<slug:slug>/', views.job_detail, name='job_detail'),
    path('jobs/<slug:slug>/edit/', views.job_edit, name='job_edit'),
    path('jobs/<slug:slug>/delete/', views.job_delete, name='job_delete'),

    # Resume URLs — opaque uuid instead of the numeric id
    path('jobs/<slug:job_slug>/resumes/search/', views.pipeline_search, name='pipeline_search'),
    path('jobs/<slug:job_slug>/resumes/suggestions/', views.pipeline_suggestions, name='pipeline_suggestions'),
    path('jobs/<slug:job_slug>/resumes/add/', views.resume_create, name='resume_create'),
    path('jobs/<slug:job_slug>/resumes/bulk/', views.resume_bulk_create, name='resume_bulk_create'),
    path('resumes/<uuid:uuid>/', views.resume_detail, name='resume_detail'),
    path('resumes/<uuid:uuid>/edit/', views.resume_edit, name='resume_edit'),
    path('resumes/<uuid:uuid>/delete/', views.resume_delete, name='resume_delete'),
    path('resumes/<uuid:uuid>/rescreen/', views.resume_rescreen, name='resume_rescreen'),
    path('resumes/<uuid:uuid>/status/', views.resume_status_fragment, name='resume_status_fragment'),
    path('resumes/<uuid:uuid>/row/', views.resume_row_fragment, name='resume_row_fragment'),

    # Resume notes
    path('resumes/<uuid:uuid>/notes/add/', views.resume_note_add, name='resume_note_add'),
    path('resumes/<uuid:uuid>/notes/<int:note_id>/delete/', views.resume_note_delete, name='resume_note_delete'),

    # Recruiter status update
    path('resumes/<uuid:uuid>/status-update/', views.resume_status_update, name='resume_status_update'),

    # Talent pool
    path('talent-pool/', views.talent_pool, name='talent_pool'),

    # Needs review — detector could not confidently assign a job family
    path('needs-review/', views.needs_review_list, name='needs_review'),

    # Screening failed — bulk re-screen
    path('screening-failed/', views.screening_failed_list, name='screening_failed'),
    path('screening-failed/rescreen/', views.screening_rescreen_bulk, name='screening_rescreen_bulk'),

    # CSV export
    path('jobs/<slug:slug>/export/', views.job_export_csv, name='job_export_csv'),

    # Bulk CV download (streaming ZIP)
    path('jobs/<slug:slug>/resumes/download/', views.download_resumes_zip, name='download_resumes_zip'),

    # User management — superuser only
    path('users/', views.user_list, name='user_list'),
    path('users/create/', views.user_create, name='user_create'),
    path('users/<int:pk>/password/', views.user_change_password, name='user_change_password'),
    path('users/<int:pk>/toggle/', views.user_toggle_active, name='user_toggle_active'),
]
