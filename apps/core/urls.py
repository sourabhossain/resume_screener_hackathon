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
]
