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

    # Job URLs
    path('jobs/', views.job_list, name='job_list'),
    path('jobs/create/', views.job_create, name='job_create'),
    path('jobs/<int:pk>/', views.job_detail, name='job_detail'),
    path('jobs/<int:pk>/edit/', views.job_edit, name='job_edit'),
    path('jobs/<int:pk>/delete/', views.job_delete, name='job_delete'),
    
    # Resume URLs
    path('jobs/<int:job_pk>/resumes/add/', views.resume_create, name='resume_create'),
    path('jobs/<int:job_pk>/resumes/bulk/', views.resume_bulk_create, name='resume_bulk_create'),
    path('resumes/<int:pk>/', views.resume_detail, name='resume_detail'),
    path('resumes/<int:pk>/edit/', views.resume_edit, name='resume_edit'),
    path('resumes/<int:pk>/delete/', views.resume_delete, name='resume_delete'),
    path('resumes/<int:pk>/rescreen/', views.resume_rescreen, name='resume_rescreen'),
    path('resumes/<int:pk>/status/', views.resume_status_fragment, name='resume_status_fragment'),
    path('resumes/<int:pk>/row/', views.resume_row_fragment, name='resume_row_fragment'),
]
